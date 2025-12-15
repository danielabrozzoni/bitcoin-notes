<!--desc: Short explanation of when ADDR/GETADDR are sent, to serve as a spec for the simulation -->
# How often do nodes partecipate in addr relay?

These notes are going to serve as a specification for the addr relay simulation.

We want to replicate the p2p addr relay mechanisms. As such, we need to understand how/when ADDR/GETADDR messages are sent.

## 1. GETADDR request

We send a GETADDR when adding a new peer, if:
- the connection is outbound
- we are not in block only mode

https://github.com/bitcoin/bitcoin/blob/2210feb4466eff1455468f0a25045fce4b89c55d/src/net_processing.cpp#L3590-L3609

## 2. GETADDR response

If we receive a GETADDR, we query our addrman cache for addresses, and for each address we call `PushAddress`. This will add the addresses to the `m_addrs_to_send` queue.

## 3. Self announcement

In MaybeSendAddr (todo: this is another point, expand on how timers set/used), if `m_next_local_addr_send` expired, we `PushAddress` with our self announcement.

## 4. We receive an ADDR

If we receive an ADDR message that:
- Contains less than 10 addresses
- Is not a reponse to a GETADDR request

For each address in the message, if:
- The address timestamp is less than 10minutes ago (to prevent addr relay flooding)

Then we call `RelayAddress` on the address. This function:
- Picks the peers to relay the address to.
  - Makes sure that we relay to the same peers for 24 hours.
  - Will make sure not to relay the address to the same peer who sent it to us in the first place.
  - Reachable addresses are relayed to 2 peers, unreachable to 1 or 2 peers.
- Calls `PushAddress`

# MaybeSendAddr 

MaybeSendAddr takes care of sending the addresses added to the queue in points 2, 3, 4. It is called by SendMessages, which is called routinely in the `ThreadMessageHandler`.

https://github.com/bitcoin/bitcoin/blob/2210feb4466eff1455468f0a25045fce4b89c55d/src/net.cpp#L3079
