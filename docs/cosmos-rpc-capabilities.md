# Cosmos RPC capability model

Cosmos network configuration declares identity, native assets, address prefixes, and
upstream pools. It does not declare a node as archive or pruned. Block history,
transaction indexing, and historical application state are independent capabilities.
Block history is proven only by the successful direct request being served; a pruning
error is a safe observation, not persistent network metadata.

Node status accepts an identity-validated syncing RPC and exposes its local progress.
Normal data operations continue to require and prefer a synchronized RPC. Operational
states are `healthy`, `syncing`, `degraded`, and `unavailable`. Overview sections fail
independently so status and local height remain visible while optional modules fail.

Status and live-head cache entries use a 2-second TTL. Chain parameters, supply,
staking, slashing, and validator data use a 5-second TTL. CoinGecko market data uses a
30-second TTL. Caches are request-driven and single-flight; there are no background
pollers or capability probes.

The slashing `allowed_missed_threshold` is the protocol window limit derived with the
SDK `RoundInt64` rule. A validator is evaluated for punishment only after the SDK's
minimum observation period and when its counter exceeds that limit. Consequently,
`remaining_misses_before_threshold` is distance to the counter limit, not a guaranteed
number of blocks before jail.

Future block views will maintain an initial 10-block rolling window, prepend new
blocks, and replace the window after large height jumps rather than fetching every
intermediate block. Old heights use direct lookup. Future transaction views will seek
up to 20 recent transactions through a bounded scan and perform exact hash lookup
directly. They will not imply nonexistence when the connected RPC index cannot find a
transaction. Account current state and balances remain independent of transaction
history, and no blocks or transactions view requires Next/Previous pagination.

## Height ETA contract for Blocks and Search

The next Blocks/Search phase must treat a height above a confirmed synchronized head
as **Block not produced yet** and show the current confirmed height, target height,
blocks remaining, estimated block time, average block interval, sample size, estimated
UTC datetime, the user's local datetime, a countdown, and an explicit **Estimated**
label.

The estimate must use approximately 100 recent completed block intervals. Only
positive intervals participate, anomalously fast and slow samples are removed with a
bounded trimmed calculation, and a single latest interval is never sufficient. The
estimate is recomputed when a new block arrives. The one-second countdown runs in the
browser without making one RPC request per second, and samples are not persisted as a
large database history. If too few valid samples remain, no ETA is shown.

If the latest block age exceeds a safe stall threshold, ETA is paused and the view
shows **Network appears stalled**, latest height, time since the latest block, and
**ETA paused**. With only a catching-up RPC and no synchronized reference endpoint,
the UI must instead say **Current RPC has only synchronized to height X** and must not
claim the target is unproduced or calculate a future-block ETA. With a synchronized
reference, a target at or below its height but above the local syncing height is
`node_not_synced`; only a target above the reference height is eligible for ETA.

Future governance integration may derive an Upcoming Upgrade from a passed proposal
containing `MsgSoftwareUpgrade` and a plan height. It will show proposal/title, upgrade
height, blocks remaining, estimated date/time, countdown, and **Estimated**. This is
not a promise that the upgrade block will be committed at that second: during a
planned halt the latest committed block may remain at plan height minus one until the
new software starts.
