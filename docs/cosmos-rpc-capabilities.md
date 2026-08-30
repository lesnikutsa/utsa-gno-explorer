# Cosmos RPC capability model

Cosmos network configuration declares identity and upstream pools, but never labels a
node as archive or pruned. Block history is proven only by a successful direct request.
A pruning response is an observation for that request and the existing bounded
failover tries the other configured RPCs. `earliest_block_height=0` is not archive
proof; a lower bound is returned only when an RPC provides one reliably.

Status accepts identity-validated syncing nodes and exposes their local progress. A
fresh confirmed head is the greatest height among checked, synchronized RPCs rather
than the first or fastest node. If every usable RPC is catching up, available local
blocks remain usable, higher requests are `node_not_synced`, and no network-wide future
claim or ETA is made.

## Block API

`GET /api/networks/{network_id}/blocks?limit=10` returns a descending, duplicate-free
metadata window. The limit defaults to 10 and is restricted to 1--20. It also returns
the observed height, catch-up state, and confirmed height when known. A head jump
replaces the bounded window; the service never walks intermediate history. The call
uses CometBFT `/blockchain`, not full transaction-bearing blocks.

`GET /api/networks/{network_id}/blocks/{height}` directly looks up a positive signed
64-bit height and reports `available`, `future`, `node_not_synced`, or
`history_unavailable`. Unknown networks return 404 and invalid input returns 422.
Wrong-chain, malformed, and transport failures are controlled 503 responses rather
than false missing-block results. Upstream URLs and exception details are not public.

```json
{"network_id":"atomone-mainnet","chain_id":"atomone-1","state":"node_not_synced","current_height":100,"target_height":101,"catching_up":true,"block":null,"lowest_available_height":null,"eta":null,"eta_unavailable_reason":null}
```

```json
{"network_id":"atomone-mainnet","chain_id":"atomone-1","state":"history_unavailable","current_height":200,"target_height":10,"catching_up":false,"block":null,"lowest_available_height":50,"eta":null,"eta_unavailable_reason":null}
```

## Height ETA

A future-height estimate uses up to 101 consecutive metadata headers (100 completed
intervals). Only positive adjacent-height intervals participate. The fastest and
slowest 10% (at least one on each side) are trimmed, and at least 20 intervals must
remain. A sample needs no more than six `/blockchain` requests per attempted RPC. It is
cached for 2 seconds by network and confirmed head, independently of target height,
using the shared single-flight cache. Errors are not cached. All calls are
request-driven; there are no background polls.

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
