<!-- desc: When, why, and how Bitcoin nodes send ADDR messages to peers -->
# ADDR Message Logic in Bitcoin Core

Every node routinely sends messages to its peers through `PeerManagerImpl::SendMessages`. The function `PeerManagerImpl::MaybeSendAddr`, called by `SendMessages`, governs the sending of ADDR messages.
For every Peer connected, we keep a queue of addresses that we should send them (m_addrs_to_send).

The logic that empties the queue and sends the addresses to the `Peer` is in `PeerManagerImpl::MaybeSendAddr`:
- Addresses are sent only if `addr_relay` to the peer is enabled
- Addresses are sent only if the `m_next_addr_send timer` has expired, preventing spam. Once addresses are sent, the timer is reset to `current_time` + ~30 seconds.
- Addresses are filtered to avoid sending ones the peer already knows (`m_addr_known`). After filtering, the function sends the addresses and updates the peer's known list with the new addresses.

The queue is filled using `PushAddress`, which includes checks to avoid duplicates and ensures the queue doesn’t exceed `MAX_ADDR_TO_SEND` elements.

Nodes send addresses to peers in four scenarios:
1. Routine self-announcements.
2. Relaying some of the addresses they receive.
3. Replying to GETADDR requests.
4. Special case, seed nodes (TODO)


## 1. Self announcements:
For every peer, the node tracks `m_next_local_addr_send`, which determines when to re-announce itself to that peer. If it’s time to self-announce, the current time is used as the address timestamp, and `m_next_local_addr_send` is reset to current_time + ~24 hours.

This self-announcement logic is in `PeerManagerImpl::MaybeSendAddr`, where the node’s local address is added to the `m_addrs_to_send` queue; which, a few lines below, gets sent to the peer.

## 2. ADDR relay:
For every address in a ADDR message, if
- the address timestamp isn't more than 10 minutes old,
- the ADDR is not in response to a GETADDR request,
- the size of the ADDR message is <10,
- the address is routable

then the node might relay the address.

This is handled by `RelayAddress`, which includes additional checks:
- Addresses that are both unreachable and non-relayable aren’t sent.
- The fn decides to which peers we should send the address, the number of peers depends on whether the address is reachable and relayable.

If all conditions are met, `RelayAddress` calls `PushAddress` to add the address to the chosen peers’ queues.

## 3. Replying to GETADDR requests:

We execute some logic to protect us from spamming and fingerprinting attacks:
- We don't reply to inbound peers
- We ignore repeated GETADDR messages

If the peer passes these checks, we send back the addresses in the addr cache
