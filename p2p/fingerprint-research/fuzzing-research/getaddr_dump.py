#!/usr/bin/env python3
# Copyright (c) 2026-present The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Connect to a Bitcoin P2P peer, request addresses, and dump the response.

This is intentionally standalone and dependency-free. It performs the Bitcoin
P2P version/verack handshake, sends getaddr, waits for an addr/addrv2 response
with more than 10 entries, and writes each received entry as a plain text line:

    addr timestamp services
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import logging
import pathlib
import random
import re
import secrets
import socket
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO


MAGIC_BYTES = {
    "mainnet": bytes.fromhex("f9beb4d9"),
    "testnet4": bytes.fromhex("1c163f28"),
    "regtest": bytes.fromhex("fabfb5da"),
    "signet": bytes.fromhex("0a03cf40"),
}

DEFAULT_PORTS = {
    "mainnet": 8333,
    "testnet4": 48333,
    "regtest": 18444,
    "signet": 38333,
}

P2P_VERSION = 70016
NODE_NETWORK = 1 << 0
NODE_WITNESS = 1 << 3
USER_AGENT = b"/getaddr-dump:0.1.0/"
MAX_PROTOCOL_MESSAGE_LENGTH = 4_000_000
ADDR_THRESHOLD = 10
EXPECTED_GETADDR_RESPONSE_SIZE = 1000
TIMESTAMP_RANDOMIZATION_RANGES = [
    ("0-5 seconds", 5),
    ("0-5 minutes", 5 * 60),
    *(("0-{} hours".format(hours), hours * 60 * 60) for hours in range(5, 6)),
    ("0-5 days", 5 * 24 * 60 * 60),
]
GREEN = "\033[32m"
RESET = "\033[0m"

# Fill these four slots, then run:
#
#     ./getaddr_dump.py --tor
#
# Each peer gets its own output file under --output-dir. Set "proxy" to None
# for a direct clearnet connection, "tor" for the Tor SOCKS proxy selected by
# --tor/--proxy, or a specific SOCKS5 proxy string like "127.0.0.1:9150".
HARDCODED_PEERS = [
    {"name": "A-clearnet", "host": "PUT_HOST_HERE", "port": 8333, "network": "mainnet", "proxy": ""},
    {"name": "A-tor", "host": "PUT_HOST_HERE", "port": 8333, "network": "mainnet", "proxy": "tor"},
    {"name": "B-clearnet", "host": "PUT_HOST_HERE", "port": 8333, "network": "mainnet", "proxy": ""},
    {"name": "B-tor", "host": "PUT_HOST_HERE", "port": 8333, "network": "mainnet", "proxy": "tor"},
]

ADDRV2_NETWORKS = {
    1: ("ipv4", 4),
    2: ("ipv6", 16),
    3: ("torv2", 10),
    4: ("torv3", 32),
    5: ("i2p", 32),
    6: ("cjdns", 16),
}


@dataclass
class Message:
    command: str
    payload: bytes


@dataclass
class DumpResult:
    job: dict
    entries: list[dict]


class ProtocolError(Exception):
    pass


class SocksError(Exception):
    pass


def hash256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def ser_compact_size(value: int) -> bytes:
    if value < 0:
        raise ValueError("compact size cannot be negative")
    if value < 253:
        return struct.pack("<B", value)
    if value <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", value)
    if value <= 0xFFFF_FFFF:
        return b"\xfe" + struct.pack("<I", value)
    return b"\xff" + struct.pack("<Q", value)


def deser_compact_size(stream: BinaryIO) -> int:
    first = read_exact(stream, 1)[0]
    if first < 253:
        return first
    if first == 253:
        return struct.unpack("<H", read_exact(stream, 2))[0]
    if first == 254:
        return struct.unpack("<I", read_exact(stream, 4))[0]
    return struct.unpack("<Q", read_exact(stream, 8))[0]


def ser_string(value: bytes) -> bytes:
    return ser_compact_size(len(value)) + value


def read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError(f"connection closed with {remaining} of {size} bytes left to read")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def parse_host_port(value: str, default_port: int) -> tuple[str, int]:
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if not rest:
            return host, default_port
        if not rest.startswith(":"):
            raise ValueError(f"invalid host:port value: {value}")
        return host, int(rest[1:])

    host, sep, port = value.rpartition(":")
    if sep and ":" not in host:
        return host, int(port)
    return value, default_port


def socks5_connect(
    proxy: tuple[str, int],
    host: str,
    port: int,
    socks_timeout: float,
    username: str | None = None,
    password: str | None = None,
) -> socket.socket:
    sock = socket.create_connection(proxy, timeout=socks_timeout)
    sock.settimeout(socks_timeout)

    try:
        stream = sock.makefile("rb", buffering=0)
        if username is None:
            sock.sendall(b"\x05\x01\x00")
        else:
            sock.sendall(b"\x05\x02\x00\x02")
        version, method = read_exact(stream, 2)
        if version != 5:
            raise SocksError(f"invalid SOCKS5 negotiation response version: {version}")
        if username is None:
            if method != 0:
                raise SocksError(f"SOCKS5 proxy rejected no-auth negotiation: method={method}")
        elif method == 2:
            encoded_username = username.encode()
            encoded_password = (password or "").encode()
            if len(encoded_username) > 255 or len(encoded_password) > 255:
                raise SocksError("SOCKS5 username/password must be at most 255 bytes each")
            sock.sendall(
                b"\x01"
                + bytes([len(encoded_username)])
                + encoded_username
                + bytes([len(encoded_password)])
                + encoded_password
            )
            auth_version, auth_status = read_exact(stream, 2)
            if auth_version != 1 or auth_status != 0:
                raise SocksError(f"SOCKS5 username/password authentication failed: status={auth_status}")
        else:
            raise SocksError(f"SOCKS5 proxy rejected username/password negotiation: method={method}")

        encoded_host = host.encode("idna")
        if len(encoded_host) > 255:
            raise SocksError(f"SOCKS5 hostname too long: {host}")
        # Match Bitcoin Core's SOCKS5 implementation: send ATYP=DOMAINNAME
        # even for IPv4/IPv6 literals.
        address = b"\x03" + bytes([len(encoded_host)]) + encoded_host

        request = b"\x05\x01\x00" + address + struct.pack(">H", port)
        sock.sendall(request)

        header = read_exact(stream, 4)
        if header[0] != 5:
            raise SocksError(f"invalid SOCKS5 response version: {header[0]}")
        if header[1] != 0:
            raise SocksError(f"SOCKS5 connect failed with reply code {header[1]}")

        atyp = header[3]
        if atyp == 1:
            read_exact(stream, 4)
        elif atyp == 3:
            read_exact(stream, read_exact(stream, 1)[0])
        elif atyp == 4:
            read_exact(stream, 16)
        else:
            raise SocksError(f"invalid SOCKS5 address type in response: {atyp}")
        read_exact(stream, 2)
    except Exception:
        sock.close()
        raise

    return sock


def pack_network_address(host: str, port: int, services: int = 0) -> bytes:
    """Serialize CAddress without a timestamp, as used inside VERSION messages."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = ipaddress.ip_address("0.0.0.0")
    if ip.version == 4:
        ip_bytes = b"\x00" * 10 + b"\xff" * 2 + ip.packed
    else:
        ip_bytes = ip.packed
    return struct.pack("<Q", services) + ip_bytes + struct.pack(">H", port)


def build_version_payload(host: str, port: int) -> bytes:
    services = NODE_NETWORK | NODE_WITNESS
    timestamp = int(time.time())
    nonce = secrets.randbits(64)
    payload = [
        struct.pack("<iQq", P2P_VERSION, services, timestamp),
        # Bitcoin VERSION payloads include addr_recv and addr_from CAddress
        # fields. They are not separate messages; they are required fields in
        # msg_version.serialize() in Bitcoin Core's test framework.
        pack_network_address(host, port),
        pack_network_address("0.0.0.0", 0, services),
        struct.pack("<Q", nonce),
        ser_string(USER_AGENT),
        struct.pack("<i", -1),
        b"\x00",  # relay=false; we only want the getaddr response.
    ]
    return b"".join(payload)


def make_message(command: str, payload: bytes, magic: bytes) -> bytes:
    command_bytes = command.encode("ascii")
    if len(command_bytes) > 12:
        raise ValueError(f"command too long: {command}")
    header = (
        magic
        + command_bytes.ljust(12, b"\x00")
        + struct.pack("<I", len(payload))
        + hash256(payload)[:4]
    )
    return header + payload


def send_message(sock: socket.socket, command: str, payload: bytes, magic: bytes) -> None:
    logging.debug("send %s (%d bytes)", command, len(payload))
    sock.sendall(make_message(command, payload, magic))


def read_message(stream: BinaryIO, magic: bytes) -> Message:
    header = read_exact(stream, 24)
    recv_magic = header[:4]
    if recv_magic != magic:
        raise ProtocolError(f"unexpected network magic {recv_magic.hex()}, expected {magic.hex()}")

    raw_command = header[4:16]
    command = raw_command.rstrip(b"\x00").decode("ascii", errors="replace")
    payload_len = struct.unpack("<I", header[16:20])[0]
    checksum = header[20:24]

    if payload_len > MAX_PROTOCOL_MESSAGE_LENGTH:
        raise ProtocolError(f"{command} payload too large: {payload_len} bytes")

    payload = read_exact(stream, payload_len)
    actual_checksum = hash256(payload)[:4]
    if actual_checksum != checksum:
        raise ProtocolError(f"{command} checksum mismatch")

    logging.debug("recv %s (%d bytes)", command, payload_len)
    return Message(command, payload)


def ipv6_or_mapped_addr(raw_addr: bytes) -> tuple[str, str]:
    if raw_addr.startswith(b"\x00" * 10 + b"\xff" * 2):
        return str(ipaddress.IPv4Address(raw_addr[12:])), "ipv4"
    return str(ipaddress.IPv6Address(raw_addr)), "ipv6"


def torv2_addr(raw_addr: bytes) -> str:
    return base64.b32encode(raw_addr).decode("ascii").lower() + ".onion"


def torv3_addr(raw_addr: bytes) -> str:
    prefix = b".onion checksum"
    version = b"\x03"
    checksum = hashlib.sha3_256(prefix + raw_addr + version).digest()[:2]
    return base64.b32encode(raw_addr + checksum + version).decode("ascii").lower() + ".onion"


def i2p_addr(raw_addr: bytes) -> str:
    return base64.b32encode(raw_addr).decode("ascii").lower().rstrip("=") + ".b32.i2p"


def format_addr(host: str, port: int) -> str:
    try:
        if ipaddress.ip_address(host).version == 6:
            return f"[{host}]:{port}"
    except ValueError:
        pass
    return f"{host}:{port}"


def parse_addr_payload(payload: bytes) -> list[dict]:
    import io

    stream = io.BytesIO(payload)
    count = deser_compact_size(stream)
    entries = []
    for _ in range(count):
        timestamp = struct.unpack("<I", read_exact(stream, 4))[0]
        services = struct.unpack("<Q", read_exact(stream, 8))[0]
        raw_addr = read_exact(stream, 16)
        host, network = ipv6_or_mapped_addr(raw_addr)
        port = struct.unpack(">H", read_exact(stream, 2))[0]
        entries.append(
            {
                "addr": format_addr(host, port),
                "timestamp": timestamp,
                "other": {
                    "host": host,
                    "port": port,
                    "services": services,
                    "network": network,
                    "message": "addr",
                },
            }
        )

    if stream.read(1):
        raise ProtocolError("addr payload has trailing bytes")
    return entries


def parse_addrv2_payload(payload: bytes) -> list[dict]:
    import io

    stream = io.BytesIO(payload)
    count = deser_compact_size(stream)
    entries = []
    for _ in range(count):
        timestamp = struct.unpack("<I", read_exact(stream, 4))[0]
        services = deser_compact_size(stream)
        network_id = read_exact(stream, 1)[0]
        address_len = deser_compact_size(stream)
        raw_addr = read_exact(stream, address_len)
        port = struct.unpack(">H", read_exact(stream, 2))[0]

        network_name, expected_len = ADDRV2_NETWORKS.get(network_id, (f"unknown-{network_id}", None))
        if expected_len is not None and address_len != expected_len:
            raise ProtocolError(
                f"addrv2 {network_name} address has length {address_len}, expected {expected_len}"
            )

        host = raw_addr.hex()
        if network_id == 1:
            host = str(ipaddress.IPv4Address(raw_addr))
        elif network_id in (2, 6):
            host = str(ipaddress.IPv6Address(raw_addr))
        elif network_id == 3:
            host = torv2_addr(raw_addr)
        elif network_id == 4:
            host = torv3_addr(raw_addr)
        elif network_id == 5:
            host = i2p_addr(raw_addr)

        entries.append(
            {
                "addr": format_addr(host, port),
                "timestamp": timestamp,
                "other": {
                    "host": host,
                    "port": port,
                    "services": services,
                    "network": network_name,
                    "network_id": network_id,
                    "message": "addrv2",
                    "raw_addr": raw_addr.hex(),
                },
            }
        )

    if stream.read(1):
        raise ProtocolError("addrv2 payload has trailing bytes")
    return entries


def write_entries(path: str, entries: list[dict]) -> None:
    output_path = pathlib.Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf8") as output:
        for entry in entries:
            output.write(f"{entry['addr']} {entry['timestamp']} {entry['other']['services']}\n")


def split_formatted_addr(addr: str) -> tuple[str, int | None]:
    if addr.startswith("["):
        host, sep, rest = addr[1:].partition("]")
        if sep and rest.startswith(":"):
            return host, int(rest[1:])
        return host, None

    host, sep, port = addr.rpartition(":")
    if sep and ":" not in host:
        return host, int(port)
    return addr, None


def infer_addr_network(host: str) -> str:
    if is_onion_host(host):
        return "tor"
    if host.endswith(".b32.i2p"):
        return "i2p"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    return "ipv4" if ip.version == 4 else "ipv6"


def read_entries(path: str) -> list[dict]:
    entries = []
    with pathlib.Path(path).open("r", encoding="utf8") as input_file:
        for line_num, line in enumerate(input_file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                addr, timestamp, services = line.split()
            except ValueError as err:
                raise ValueError(f"{path}:{line_num}: expected 'addr timestamp services'") from err

            host, port = split_formatted_addr(addr)
            entries.append(
                {
                    "addr": addr,
                    "timestamp": int(timestamp),
                    "other": {
                        "host": host,
                        "port": port,
                        "services": int(services),
                        "network": infer_addr_network(host),
                        "message": "file",
                    },
                }
            )
    return entries


def handshake(
    sock: socket.socket,
    stream: BinaryIO,
    host: str,
    port: int,
    magic: bytes,
    prefer_addrv2: bool,
) -> None:
    send_message(sock, "version", build_version_payload(host, port), magic)

    got_version = False
    got_verack = False
    deadline = time.monotonic() + sock.gettimeout()

    while not (got_version and got_verack):
        if time.monotonic() > deadline:
            raise TimeoutError("timed out during handshake")

        message = read_message(stream, magic)
        if message.command == "version":
            got_version = True
            if prefer_addrv2:
                send_message(sock, "sendaddrv2", b"", magic)
            send_message(sock, "verack", b"", magic)
        elif message.command == "verack":
            got_verack = True
        elif message.command == "ping":
            send_message(sock, "pong", message.payload, magic)
        else:
            logging.debug("ignoring %s during handshake", message.command)


def request_addr(
    sock: socket.socket,
    stream: BinaryIO,
    magic: bytes,
    timeout: float,
) -> list[dict]:
    send_message(sock, "getaddr", b"", magic)

    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for addr/addrv2 with more than {ADDR_THRESHOLD} entries")

        message = read_message(stream, magic)
        if message.command == "ping":
            send_message(sock, "pong", message.payload, magic)
            continue
        if message.command == "addr":
            entries = parse_addr_payload(message.payload)
        elif message.command == "addrv2":
            entries = parse_addrv2_payload(message.payload)
        else:
            logging.debug("ignoring %s while waiting for getaddr response", message.command)
            continue

        logging.info("received %s with %d entries", message.command, len(entries))
        if len(entries) <= ADDR_THRESHOLD:
            logging.warning(
                "ignoring %s with only %d entries; waiting for more than %d",
                message.command,
                len(entries),
                ADDR_THRESHOLD,
            )
            continue
        if len(entries) != EXPECTED_GETADDR_RESPONSE_SIZE:
            logging.warning(
                "expected %d entries in getaddr response, got %d",
                EXPECTED_GETADDR_RESPONSE_SIZE,
                len(entries),
            )
        return entries


def safe_output_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "peer"


def is_onion_host(host: str) -> bool:
    return host.lower().endswith(".onion")


def compare_response_pair(clearnet: dict, onion: dict) -> dict:
    clearnet_addrs = {entry["addr"] for entry in clearnet["entries"]}
    onion_addrs = {entry["addr"] for entry in onion["entries"]}
    clearnet_addr_timestamps = {(entry["addr"], entry["timestamp"]) for entry in clearnet["entries"]}
    onion_addr_timestamps = {(entry["addr"], entry["timestamp"]) for entry in onion["entries"]}

    return {
        "clearnet_name": clearnet["name"],
        "onion_name": onion["name"],
        "same_addr": len(clearnet_addrs & onion_addrs),
        "same_addr_timestamp": len(clearnet_addr_timestamps & onion_addr_timestamps),
    }


def node_network_class(response: dict) -> str:
    return "onion" if is_onion_host(response["host"]) else "clearnet"


def entry_network_class(entry: dict) -> str:
    network = entry["other"].get("network", "")
    if network.startswith("tor") or is_onion_host(entry["other"].get("host", "")):
        return "onion"
    if network in ("ipv4", "ipv6"):
        return "clearnet"
    return network


def randomized_entries_for_response(response: dict, max_delta_seconds: int, rng: random.Random) -> list[dict]:
    node_class = node_network_class(response)
    randomized_entries = []
    for entry in response["entries"]:
        randomized_entry = dict(entry)
        randomized_entry["randomized_timestamp"] = entry["timestamp"]
        if entry_network_class(entry) != node_class:
            randomized_entry["randomized_timestamp"] -= rng.randint(1, max_delta_seconds)
        randomized_entries.append(randomized_entry)
    return randomized_entries


def entries_by_addr(entries: list[dict]) -> dict[str, list[dict]]:
    by_addr = {}
    for entry in entries:
        by_addr.setdefault(entry["addr"], []).append(entry)
    return by_addr


def compare_randomized_response_pair(
    clearnet: dict,
    onion: dict,
    max_delta_seconds: int,
    rng: random.Random,
    include_trace: bool = False,
) -> dict:
    clearnet_addrs = {entry["addr"] for entry in clearnet["entries"]}
    onion_addrs = {entry["addr"] for entry in onion["entries"]}
    exact_matches = {
        (entry["addr"], entry["timestamp"], entry["timestamp"])
        for entry in clearnet["entries"]
    } & {
        (entry["addr"], entry["timestamp"], entry["timestamp"])
        for entry in onion["entries"]
    }

    randomized_clearnet = entries_by_addr(randomized_entries_for_response(clearnet, max_delta_seconds, rng))
    randomized_onion = entries_by_addr(randomized_entries_for_response(onion, max_delta_seconds, rng))

    range_matches = set()
    timestamp_changes = []
    for addr in randomized_clearnet.keys() & randomized_onion.keys():
        for clearnet_entry in randomized_clearnet[addr]:
            for onion_entry in randomized_onion[addr]:
                timestamp_delta = abs(
                    clearnet_entry["randomized_timestamp"] - onion_entry["randomized_timestamp"]
                )
                in_range = timestamp_delta <= max_delta_seconds
                if in_range:
                    range_matches.add((addr, clearnet_entry["timestamp"], onion_entry["timestamp"]))
                if include_trace:
                    timestamp_changes.append(
                        {
                            "addr": addr,
                            "clearnet_initial": clearnet_entry["timestamp"],
                            "clearnet_randomized": clearnet_entry["randomized_timestamp"],
                            "onion_initial": onion_entry["timestamp"],
                            "onion_randomized": onion_entry["randomized_timestamp"],
                            "delta_after": timestamp_delta,
                            "match": "yes" if in_range else "no",
                        }
                    )

    stats = {
        "same_addr": len(clearnet_addrs & onion_addrs),
        "same_addr_timestamp": len(range_matches),
        "false_positives": len(range_matches - exact_matches),
    }
    if include_trace:
        stats["timestamp_changes"] = sorted(timestamp_changes, key=lambda row: row["addr"])
    return stats


def initial_timestamp_changes(clearnet: dict, onion: dict) -> list[dict]:
    clearnet_by_addr = entries_by_addr(clearnet["entries"])
    onion_by_addr = entries_by_addr(onion["entries"])
    timestamp_changes = []
    for addr in clearnet_by_addr.keys() & onion_by_addr.keys():
        for clearnet_entry in clearnet_by_addr[addr]:
            for onion_entry in onion_by_addr[addr]:
                timestamp_delta = abs(clearnet_entry["timestamp"] - onion_entry["timestamp"])
                timestamp_changes.append(
                    {
                        "addr": addr,
                        "clearnet_initial": clearnet_entry["timestamp"],
                        "clearnet_randomized": clearnet_entry["timestamp"],
                        "onion_initial": onion_entry["timestamp"],
                        "onion_randomized": onion_entry["timestamp"],
                        "delta_after": timestamp_delta,
                        "match": "yes" if timestamp_delta == 0 else "no",
                    }
                )
    return sorted(timestamp_changes, key=lambda row: row["addr"])


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    widths = [
        max(len(str(value)) for value in [header] + [row[column] for row in rows])
        for column, header in enumerate(headers)
    ]
    separator = "  ".join("-" * width for width in widths)
    print("  ".join(header.ljust(widths[column]) for column, header in enumerate(headers)))
    print(separator)
    for row in rows:
        print("  ".join(str(value).ljust(widths[column]) for column, value in enumerate(row)))


def format_timestamp_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def print_comparison_stats(results: list[dict], timestamp_randomization_rounds: int, verbose: bool = False) -> None:
    clearnet_results = [result for result in results if not is_onion_host(result["host"])]
    onion_results = [result for result in results if is_onion_host(result["host"])]

    if not clearnet_results or not onion_results:
        print("No clearnet/onion response pairs to compare.")
        return

    for clearnet in clearnet_results:
        for onion in onion_results:
            pair = f"{clearnet['name']} <-> {onion['name']}"
            stats = compare_response_pair(clearnet, onion)

            print(f"\nGETADDR timestamp comparison: {pair}")
            randomized_rows = [
                [
                    "no randomization",
                    stats["same_addr"],
                    stats["same_addr_timestamp"],
                    0,
                ]
            ]
            verbose_rows = []
            range_order = {"no randomization": 0}
            range_order.update({label: index for index, (label, _) in enumerate(TIMESTAMP_RANDOMIZATION_RANGES, start=1)})
            if verbose:
                for row in initial_timestamp_changes(clearnet, onion):
                    row["range"] = "no randomization"
                    verbose_rows.append(row)

            for label, max_delta_seconds in TIMESTAMP_RANDOMIZATION_RANGES:
                for _ in range(timestamp_randomization_rounds):
                    rng = random.Random()
                    stats = compare_randomized_response_pair(
                        clearnet,
                        onion,
                        max_delta_seconds,
                        rng,
                        include_trace=verbose,
                    )
                    randomized_rows.append(
                        [
                            label,
                            stats["same_addr"],
                            stats["same_addr_timestamp"],
                            stats["false_positives"],
                        ]
                    )
                    if verbose:
                        for row in stats["timestamp_changes"]:
                            row["range"] = label
                            verbose_rows.append(row)
            print_table(
                ["range", "same_addr", "addr+ts_in_range", "false_pos"],
                randomized_rows,
            )
            if verbose:
                print(f"\nGETADDR timestamp changes: {pair}")
                verbose_table_rows = [
                    [
                        row["addr"],
                        row["range"],
                        format_timestamp_utc(row["clearnet_initial"]),
                        format_timestamp_utc(row["clearnet_randomized"]),
                        format_timestamp_utc(row["onion_initial"]),
                        format_timestamp_utc(row["onion_randomized"]),
                        row["delta_after"],
                        row["match"],
                    ]
                    for row in sorted(verbose_rows, key=lambda row: (row["addr"], range_order[row["range"]]))
                ]
                print_table(
                    [
                        "addr",
                        "range",
                        "clearnet_initial_utc",
                        "clearnet_after_utc",
                        "onion_initial_utc",
                        "onion_after_utc",
                        "delta_after",
                        "match",
                    ],
                    verbose_table_rows,
                )


def connect_peer(
    *,
    host: str,
    port: int,
    network: str,
    timeout: float,
    socks_timeout: float,
    proxy: str | None,
    socks_username: str | None = None,
    socks_password: str | None = None,
) -> tuple[socket.socket, str, int]:
    if proxy:
        proxy_addr = parse_host_port(proxy, 9050)
        logging.info("connecting to %s:%d on %s through SOCKS5 proxy %s:%d", host, port, network, *proxy_addr)
        return socks5_connect(proxy_addr, host, port, socks_timeout, socks_username, socks_password), host, port

    logging.info("connecting to %s:%d on %s", host, port, network)
    sock = socket.create_connection((host, port), timeout=timeout)
    version_host, version_port = sock.getpeername()[:2]
    return sock, version_host, version_port


def dump_peer(
    *,
    host: str,
    port: int,
    network: str,
    output: str,
    timeout: float,
    socks_timeout: float,
    proxy: str | None,
    prefer_addrv2: bool,
    socks_username: str | None = None,
    socks_password: str | None = None,
) -> list[dict]:
    magic = MAGIC_BYTES[network]
    sock, version_host, version_port = connect_peer(
        host=host,
        port=port,
        network=network,
        timeout=timeout,
        socks_timeout=socks_timeout,
        proxy=proxy,
        socks_username=socks_username,
        socks_password=socks_password,
    )

    with sock:
        sock.settimeout(timeout)
        stream = sock.makefile("rb", buffering=0)
        handshake(sock, stream, version_host, version_port, magic, prefer_addrv2)
        logging.info("handshake complete with %s:%d", host, port)
        entries = request_addr(
            sock=sock,
            stream=stream,
            magic=magic,
            timeout=timeout,
        )

    write_entries(output, entries)
    logging.info("wrote %d address entries from %s:%d to %s", len(entries), host, port, output)
    return entries


def is_retryable_error(err: Exception) -> bool:
    return isinstance(err, (TimeoutError, SocksError, ConnectionError, OSError, EOFError))


def retry_socks_credentials(job: dict, attempt: int) -> tuple[str | None, str | None]:
    if not job["proxy"]:
        return None, None
    token = secrets.token_hex(8)
    return f"getaddr-{job['name']}-{attempt}-{token}", secrets.token_hex(8)


def dump_peer_attempt(job: dict, attempt: int, max_attempts: int) -> DumpResult:
    socks_username, socks_password = retry_socks_credentials(job, attempt)
    logging.info(
        "dumping %s:%d, attempt %d/%d%s",
        job["host"],
        job["port"],
        attempt,
        max_attempts,
        " with SOCKS stream isolation" if socks_username else "",
    )
    entries = dump_peer(
        host=job["host"],
        port=job["port"],
        network=job["network"],
        output=job["output"],
        timeout=job["timeout"],
        socks_timeout=job["socks_timeout"],
        proxy=job["proxy"],
        prefer_addrv2=job["prefer_addrv2"],
        socks_username=socks_username,
        socks_password=socks_password,
    )
    print(f"{GREEN}done: {job['name']} getaddr recorded ({len(entries)} addresses){RESET}")
    return DumpResult(job=job, entries=entries)


def dump_peer_with_retries(job: dict, max_attempts: int, retry_delay: float) -> DumpResult:
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return dump_peer_attempt(job, attempt, max_attempts)
        except Exception as err:
            last_err = err
            if not is_retryable_error(err) or attempt == max_attempts:
                raise
            logging.warning(
                "retryable error dumping %s:%d on attempt %d/%d: %s; retrying after %.1fs",
                job["host"],
                job["port"],
                attempt,
                max_attempts,
                err,
                retry_delay,
            )
            time.sleep(retry_delay)

    raise RuntimeError(f"unreachable retry state: {last_err}")


def hardcoded_peer_jobs(args: argparse.Namespace) -> list[dict]:
    jobs = []
    default_proxy = args.proxy
    if args.tor:
        default_proxy = default_proxy or "127.0.0.1:9050"

    for peer in HARDCODED_PEERS:
        host = peer["host"]
        if not host:
            continue

        network = peer.get("network", args.network)
        port = peer.get("port") or DEFAULT_PORTS[network]
        peer_proxy = peer.get("proxy")
        if peer_proxy == "tor":
            peer_proxy = default_proxy or "127.0.0.1:9050"

        name = safe_output_name(peer.get("name") or host)
        output = pathlib.Path(args.output_dir) / f"{name}_getaddr.txt"
        jobs.append(
            {
                "host": host,
                "name": name,
                "port": port,
                "network": network,
                "output": str(output),
                "timeout": args.timeout,
                "socks_timeout": args.socks_timeout,
                "proxy": peer_proxy,
                "prefer_addrv2": not args.no_addrv2,
            }
        )

    if not jobs:
        raise ValueError("fill HARDCODED_PEERS with four host values, or pass a host on the command line")
    return jobs


def run_hardcoded_jobs(jobs: list[dict], max_attempts: int, retry_delay: float) -> tuple[list[dict], int]:
    pending = list(jobs)
    failures = 0
    results = []
    last_errors = {}

    for attempt in range(1, max_attempts + 1):
        if not pending:
            break
        if attempt > 1:
            logging.info("waiting %.1fs before retry round %d/%d", retry_delay, attempt, max_attempts)
            time.sleep(retry_delay)

        retry_later = []
        for job in pending:
            try:
                result = dump_peer_attempt(job, attempt, max_attempts)
                results.append(
                    {
                        "name": result.job["name"],
                        "host": result.job["host"],
                        "output": result.job["output"],
                        "entries": result.entries,
                    }
                )
            except Exception as err:
                last_errors[job["name"]] = err
                if is_retryable_error(err) and attempt < max_attempts:
                    logging.warning(
                        "retryable error dumping %s:%d on attempt %d/%d: %s; deferring until next retry round",
                        job["host"],
                        job["port"],
                        attempt,
                        max_attempts,
                        err,
                    )
                    retry_later.append(job)
                else:
                    failures += 1
                    logging.exception("failed to dump getaddr response from %s:%d: %s", job["host"], job["port"], err)
        pending = retry_later

    for job in pending:
        failures += 1
        logging.error(
            "failed to dump getaddr response from %s:%d after %d attempts: %s",
            job["host"],
            job["port"],
            max_attempts,
            last_errors.get(job["name"]),
        )

    return results, failures


def read_job_result(job: dict) -> dict:
    entries = read_entries(job["output"])
    logging.info("read %d address entries for %s from %s", len(entries), job["name"], job["output"])
    return {
        "name": job["name"],
        "host": job["host"],
        "output": job["output"],
        "entries": entries,
    }


def read_hardcoded_job_results(jobs: list[dict]) -> tuple[list[dict], int]:
    results = []
    failures = 0
    for job in jobs:
        try:
            results.append(read_job_result(job))
        except Exception as err:
            failures += 1
            logging.exception("failed to read getaddr response for %s from %s: %s", job["name"], job["output"], err)
    return results, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to a Bitcoin P2P node, send getaddr, and dump addr entries as plain text."
    )
    parser.add_argument(
        "host",
        nargs="?",
        help="Bitcoin P2P host to connect to; omitted means use HARDCODED_PEERS",
    )
    parser.add_argument("-p", "--port", type=int, help="Bitcoin P2P port; defaults from --network")
    parser.add_argument(
        "-n",
        "--network",
        choices=sorted(MAGIC_BYTES),
        default="mainnet",
        help="Bitcoin network magic to use",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="getaddr_response.txt",
        help="output path for plain text lines",
    )
    parser.add_argument(
        "--output-dir",
        default="getaddr_responses",
        help="directory for HARDCODED_PEERS output files",
    )
    download_group = parser.add_mutually_exclusive_group()
    download_group.add_argument(
        "--download",
        dest="download",
        action="store_true",
        default=True,
        help="download fresh getaddr responses before comparing; this is the default",
    )
    download_group.add_argument(
        "--no-download",
        dest="download",
        action="store_false",
        help="read existing response files and only run comparisons",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="socket and getaddr response timeout in seconds",
    )
    parser.add_argument(
        "--socks-timeout",
        type=float,
        default=90.0,
        help="SOCKS5 connect timeout in seconds for proxied peers",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=8,
        help="maximum attempts per peer after retryable timeouts",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=10.0,
        help="seconds to wait between timeout retries",
    )
    parser.add_argument(
        "--timestamp-randomization-rounds",
        type=int,
        default=5,
        help="number of timestamp randomization rounds to run for each range",
    )
    parser.add_argument(
        "--no-addrv2",
        action="store_true",
        help="do not advertise sendaddrv2 before getaddr",
    )
    parser.add_argument(
        "--proxy",
        help="SOCKS5 proxy as host:port, for example 127.0.0.1:9050 for Tor",
    )
    parser.add_argument(
        "--tor",
        action="store_true",
        help="shortcut for --proxy 127.0.0.1:9050",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timestamp_randomization_rounds < 1:
        raise ValueError("--timestamp-randomization-rounds must be at least 1")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    proxy = args.proxy
    if args.tor:
        proxy = proxy or "127.0.0.1:9050"

    if args.host:
        port = args.port if args.port is not None else DEFAULT_PORTS[args.network]
        job = {
            "name": safe_output_name(args.host),
            "host": args.host,
            "port": port,
            "network": args.network,
            "output": args.output,
            "timeout": args.timeout,
            "socks_timeout": args.socks_timeout,
            "proxy": proxy,
            "prefer_addrv2": not args.no_addrv2,
        }
        if args.download:
            dump_peer_with_retries(
                job,
                max_attempts=args.max_attempts,
                retry_delay=args.retry_delay,
            )
        else:
            result = read_job_result(job)
            print(f"{GREEN}done: {job['name']} getaddr read ({len(result['entries'])} addresses){RESET}")
        return 0

    jobs = hardcoded_peer_jobs(args)
    if args.download:
        results, failures = run_hardcoded_jobs(
            jobs,
            max_attempts=args.max_attempts,
            retry_delay=args.retry_delay,
        )
    else:
        results, failures = read_hardcoded_job_results(jobs)
    print_comparison_stats(results, args.timestamp_randomization_rounds, verbose=args.verbose)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
