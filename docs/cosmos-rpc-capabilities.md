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

Future block views will maintain an initial 10-block rolling window, prepend new
blocks, and replace the window after large height jumps rather than fetching every
intermediate block. Old heights use direct lookup. Future transaction views will seek
up to 20 recent transactions through a bounded scan and perform exact hash lookup
directly. They will not imply nonexistence when the connected RPC index cannot find a
transaction. Account current state and balances remain independent of transaction
history, and no blocks or transactions view requires Next/Previous pagination.
