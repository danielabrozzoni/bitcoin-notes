# GETADDR Fingerprinting Before and After Timestamp Randomization

I connected to four interfaces belonging to two nodes. I will call them node A and node B. Each node exposes one clearnet interface and one Tor interface:

```text
A-clearnet
A-tor
B-clearnet
B-tor
```

For each interface, I send a `GETADDR` message and record the returned addresses and timestamps. I then compare the clearnet/Tor responses and count:

- how many addresses appear in both responses
- how many addresses appear in both responses with the same timestamp

## Baseline: No Randomization

Without timestamp randomization, it is pretty obvious which interfaces belong together.

```text
pair                   same_addr  addr+ts_exact
---------------------  ---------  -------------
A-clearnet <-> A-tor   9          9
A-clearnet <-> B-tor   6          0
B-clearnet <-> A-tor   5          0
B-clearnet <-> B-tor   24         19
```

The important column is `addr+ts_exact`: addresses that appear in both responses with exactly the same timestamp. For unrelated node pairs, this is zero in this run. It can sometimes be a low nonzero number, but here it cleanly separates the matching interfaces.

For interfaces belonging to the same node, the signal is clearly nonzero. In node A's case, all shared addresses also have the same timestamp. In node B's case, 19 out of 24 shared addresses do.

## Timestamp Randomization

Next, I tested a timestamp-randomization strategy. The rule is to randomize only timestamps for addresses whose network is different from the requester network:

- If a clearnet peer asks for addresses, randomize Tor-address timestamps.
- If a Tor peer asks for addresses, randomize clearnet-address timestamps.

The randomization only subtracts time, so timestamps become older and do not move into the future.

I tested several randomization ranges:

```text
0-5 seconds
0-5 minutes
0-5 hours
0-5 days
```

For each range, I compare timestamps using that same range. For example, with `0-5 hours`, two timestamps count as matching if they are within 5 hours of each other.

## Results

```text
GETADDR timestamp comparison: A-clearnet <-> A-tor
range             same_addr  addr+ts_in_range  false_pos
----------------  ---------  ----------------  ---------
no randomization  9          9                 0
0-5 seconds       9          9                 0
0-5 minutes       9          9                 0
0-5 hours         9          9                 0
0-5 days          9          9                 0
```

```text
GETADDR timestamp comparison: A-clearnet <-> B-tor
range             same_addr  addr+ts_in_range  false_pos
----------------  ---------  ----------------  ---------
no randomization  6          0                 0
0-5 seconds       6          0                 0
0-5 minutes       6          0                 0
0-5 hours         6          0                 0
0-5 days          6          4                 4
```

```text
GETADDR timestamp comparison: B-clearnet <-> A-tor
range             same_addr  addr+ts_in_range  false_pos
----------------  ---------  ----------------  ---------
no randomization  5          0                 0
0-5 seconds       5          0                 0
0-5 minutes       5          0                 0
0-5 hours         5          2                 2
0-5 days          5          4                 4
```

```text
GETADDR timestamp comparison: B-clearnet <-> B-tor
range             same_addr  addr+ts_in_range  false_pos
----------------  ---------  ----------------  ---------
no randomization  24         19                0
0-5 seconds       24         19                0
0-5 minutes       24         19                0
0-5 hours         24         19                0
0-5 days          24         22                3
```

## Interpretation

Timestamp randomization may remove exact timestamp equality as a fingerprint, but comparing timestamps by range still has a tradeoff. Same-node pairs remain identifiable, while wider ranges create more accidental matches.

For pairs that are actually the same node, randomization does not meaningfully increase the signal. `addr+ts_in_range` stays the same for A-clearnet/A-tor, and mostly stays the same for B-clearnet/B-tor. This is expected: these pairs already had matching address timestamps before randomization.

For unrelated interfaces, widening the accepted timestamp range creates false positives. These are addresses that did not have the same timestamp originally, but become close enough under the range comparison.

The clearest examples are in the `0-5 days` range:

```text
A-clearnet <-> B-tor: 4 false positives
B-clearnet <-> A-tor: 4 false positives
```

The B-clearnet/B-tor pair also gets 3 additional in-range matches at `0-5 days`.

More data is needed, but this run suggests that very small ranges are not enough, while day-scale randomization may make timestamps older than necessary. Randomizing by a few hours looks like a more reasonable balance.
