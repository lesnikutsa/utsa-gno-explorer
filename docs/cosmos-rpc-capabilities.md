# Cosmos RPC capability model

Cosmos network configuration declares identity, native assets, address prefixes, and
upstream pools, but never labels a node as archive or pruned. Block history,
transaction indexing, and historical application state are independent capabilities.
Block history is proven only by a successful direct request.
A pruning response is an observation for that request and the existing bounded
failover tries the other configured RPCs. `earliest_block_height=0` is not archive
proof; a lower bound is returned only when an RPC provides one reliably.

Status accepts identity-validated syncing nodes and exposes their local progress.
Operational states are `healthy`, `syncing`, `degraded`, and `unavailable`; overview
sections fail independently. The observed height is the greatest local height among
checked RPCs. A synchronized height is an ETA reference only when no checked catching-
up node is already ahead of it. That contradictory state proves blocks up to the
observed height exist, so they are looked up directly, but it cannot support a safe
network-wide ETA. If every usable RPC is catching up, available local
blocks remain usable, higher requests are `node_not_synced`, and no network-wide future
claim or ETA is made.

## Block API

`GET /api/networks/{network_id}/blocks?limit=10` returns a descending, duplicate-free
metadata window. The limit defaults to 10 and is restricted to 1--20. It also returns
the observed height, catch-up state, and confirmed height when known. A head jump
replaces the bounded window; the service never walks intermediate history. The call
uses CometBFT `/blockchain`, not full transaction-bearing blocks.

Status and identical metadata windows use the existing 2-second request-driven,
single-flight cache. Their keys include the network, observed head, and window limit;
an expired status entry that observes a new head therefore loads a new window.

`GET /api/networks/{network_id}/blocks/{height}` directly looks up a positive signed
64-bit height and reports `available`, `future`, `node_not_synced`, or
`history_unavailable`. Unknown networks return 404 and invalid input returns 422.
Wrong-chain, malformed, and transport failures are controlled 503 responses rather
than false missing-block results. Upstream URLs and exception details are not public.
Direct historical lookup considers every identity-checked configured RPC that has
reached the target, even when it is too far behind to serve as a live-head candidate.
Successfully validated direct blocks use the same 2-second cache and single-flight,
keyed by network and height. Failed lookups are not cached. Reported history bounds
must be positive signed 64-bit heights consistent with the requested height; invalid
bounds are upstream failures rather than public history facts.

```json
{"network_id":"atomone-mainnet","chain_id":"atomone-1","state":"node_not_synced","current_height":100,"target_height":101,"catching_up":true,"block":null,"lowest_available_height":null,"eta":null,"eta_unavailable_reason":null}
```

```json
{"network_id":"atomone-mainnet","chain_id":"atomone-1","state":"history_unavailable","current_height":200,"target_height":10,"catching_up":false,"block":null,"lowest_available_height":50,"eta":null,"eta_unavailable_reason":null}
```

## Height ETA

A future-height estimate requests up to 101 consecutive metadata headers (100 completed
intervals). Only positive adjacent-height intervals participate. The fastest and
slowest 10% (at least one on each side) are trimmed, and at least 20 intervals must
remain. A sample needs no more than six `/blockchain` requests per attempted RPC. It is
cached for 2 seconds by network and confirmed head, independently of target height,
using the shared single-flight cache. Errors are not cached. All calls are
request-driven; there are no background polls.

The 101-header window is a maximum, not a requirement. When an RPC provides a
trustworthy pruning boundary, the contiguous suffix ending at the confirmed head is
used and requests do not continue below that boundary. A sufficiently large suffix
produces an ETA; a confirmed shorter suffix produces `insufficient_sample`. Transport,
identity, and malformed-response errors are not interpreted as pruning and remain
controlled upstream failures after bounded failover.

For `/blockchain`, CometBFT may report the retained boundary as `min height B can't be
greater than max height N` after its range filter raises the requested minimum to B.
This exact, range-consistent form confirms the boundary while preserving metadata
already collected from higher pages. Arbitrary JSON-RPC errors do not confirm pruning.

The immutable estimate is the last confirmed block time plus remaining blocks times
the trimmed mean. It is not re-anchored to request time. A passed estimate becomes
`overdue_awaiting` without moving its date. At a latest-block age greater than 300
seconds, the network appears stalled and ETA is paused. Fewer than 20 usable intervals
produces `insufficient_sample`; date arithmetic overflow produces `date_out_of_range`.

```json
{"network_id":"atomone-mainnet","chain_id":"atomone-1","state":"future","current_height":200,"target_height":210,"catching_up":false,"block":null,"lowest_available_height":null,"eta":{"current_height":200,"target_height":210,"remaining_blocks":10,"average_interval_seconds":5.2,"sample_interval_count":80,"sample_start_height":100,"sample_end_height":200,"estimated_at":"2026-08-30T12:00:52Z","approximate":true,"status":"estimated"},"eta_unavailable_reason":null}
```

ETA is approximate, not a promise of an update time. A planned upgrade at height H can
leave H-1 as the last completed block until new software starts. Governance upgrade
plan discovery is outside this API.

Overview status/live-head and block/ETA cache entries use a 2-second TTL. Other
overview sections use 5 seconds and market data uses 30 seconds. Cache operation is
bounded and single-flight.

The slashing `allowed_missed_threshold` is the protocol window limit derived with the
SDK `RoundInt64` rule, including round-half-to-even behavior. Punishment is evaluated
only after the SDK minimum observation period and when the counter exceeds that limit.
Thus `remaining_misses_before_threshold` is distance to the counter limit, not a
guaranteed number of blocks before jail.

The future UI may maintain an initial 10-block rolling window, prepend new blocks, and
replace it after a large head jump. Future transaction views may seek up to 20 recent
transactions through a bounded scan and perform exact hash lookup directly; they must
not imply nonexistence when the RPC transaction index cannot find a transaction.
Account current state and balances remain independent of transaction history, and no
blocks or transactions view requires Next/Previous pagination.

The Blocks/Search UI will present UTC and local estimate times, a browser-side
countdown, and an explicit **Estimated** label without polling RPC every second.
Future governance integration may derive an Upcoming Upgrade from a passed proposal
containing `MsgSoftwareUpgrade`; extracting those plans remains outside this API.
