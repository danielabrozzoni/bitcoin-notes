<!-- desc: When and why nodes send GETADDR, and how responses are rate-limited. -->
# GETADDR Behavior: When Nodes Ask for Addresses
When we connect to a new peer, we might decide to send a GETADDR to help populate/update our addrman (see `net_processing:L3535-L3550` and `SetupAddressRelay`).

How many addresses we can receive from a peer is governed by `m_addr_token_bucket`. It is initially set to one, to permit self-announcement, but we increase it by `MAX_ADDR_TO_SEND` when we ask for a `GETADDR`.
