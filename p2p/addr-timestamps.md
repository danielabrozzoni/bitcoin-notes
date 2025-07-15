<!-- desc: How address timestamps are initialized, updated, and used to evaluate freshness and "terribleness". -->
# How Address Timestamps Work in Bitcoin Core

Address timestamps are included in the ADDR message, and saved in the Addrman. We interpret the timestamp of an address as a `last_seen` (see the log message in `CConman::ConnectNode` that explicitly log `lastseen=`)

Timestamps are used to decide:
- Whether we should relay the addresses we receive - we don't want to relay addresses that are older than 10 minutes
- The timestamp is taken into account when we want to decide if an address `IsTerrible`. Terrible addresses are not sent in response to `GETADDR`, and the metric is useful in the Addrman when deciding whether to overwrite an address or not (being  terrible is one of the two or conditions to allow it to be overwritten). The conditions for being terrible are:
  - Addresses tried in the last minute can't be terrible
  - An address is considered terrible if the address timestamp is in the future (10 minutes wiggle room admitted) or older than 30 days
  - An address is considered terrible if we tried connecting to it for at least `ADDRMAN_RETRIES` attempts and never had a success
  - An address is considered terrible if in the last week we had more than `ADDRMAN_MAX_FAILURES` failures

When nodes self-announce, they do so with the current node time as the timestamp.

Nodes often slightly change the timestamps of the addrs received before saving them:
- When receiving an ADDR message, if the timestamp is less than 1000000000s or more than current_time + 10 minutes, we change the timestamp to be current time minus 5 days.
  - (I suppose) it's because we don't want to save obviously invalid timestamps, so we change it to have a reasonable timestamp, old enough that it won't get relayed to peers (>10 minutes), but fresh enough that it won't get terrible for at least another 25 days
- When receiving an address from a seed, we give it a timestamp of between one and two weeks ago (`ConvertSeeds`)
- When receiving an address from a dns node, we give it a random timestamp between three and seven days old (net.cpp, L2340, after "Loading addresses from DNS seed")
- When we add an address to the addrman or update its timestamp, we remove a time_penalty from the timestamp. The time_penalty is 0 if the address comes from a self announcement, otherwise, it's 2h (net_processing:3874).
  - I suppose the 2h time_penalty is to take into account all the time the address traveled around the network before reaching us (?)

Nodes also routinely update the addresses timestamps in their addrman:
- When we connect to a node, we update its `nTime` if our is older than 20min (`AddrManImpl::Connected_`)
- When `AddrManImpl::AddSingle` is called
- If the address is already in the addrman: if the address timestamp is older than `update_interval` (1h for currently online nodes, 24h otherwise), we update it (maybe with `time_penalty`, as specified above)
- If the address is not in the addrman: insert it, maybe manipulate the timestamp with `time_penalty`

## Timestamps lifecycle

### Step 1: Initialization:
- If from seed node, we set the timestamp to 1-2 weeks ago
- If from DNS seed, we set the timestamp to 3-7 days old
- If received with ADDR message
  - If the nTime is not before 100000000 seconds or 10 minutes in the future, we use the message nTime, minus time_penalty (0 if self-announcement, otherwise 2h)
  - If the nTime is before 100000000 seconds or more than 10 minutes in the future, we set it to now - 5 days

### Step 2: Update
- When connected, if the timestamp is older than 20 minutes, update it
- Update when adding to the addrman new table in `AddrmanImpl::AddSingle`

### Step 3: Usage
- When receiving an address without a GETADDR, we decide whether to relay the address or not based on the timestamp (if older than 10 minutes)
- We use them in `IsTerrible` -> address is terrible if timestamp is older than 30 days, or in the future


# What happens if we receive an ADDR with 0 as timestamp?
- Nodes would set the timestamp to five days ago: https://github.com/bitcoin/bitcoin/blob/33dfbbdff69dee2f1a27f69f5f7a123d0d47ef42/src/net_processing.cpp#L3924
- Timestamp would get updated when we connect to the node


