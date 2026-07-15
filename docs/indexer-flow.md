# Indexer flow

The repository now contains two indexer entry points: the bounded one-shot `scripts/index_range.py` and the foreground continuous `scripts/run_indexer.py`. Both reuse the same parsing and single-height PostgreSQL write path. The continuous runner is not a daemon and is not a production deployment.

## Continuous per-cycle flow

1. Hold the chain-scoped PostgreSQL advisory lock in a dedicated session.
2. Start a numbered cycle.
3. Probe every configured RPC endpoint once with `/status`.
4. Persist one `rpc_endpoint_checks` row per endpoint and update current endpoint state.
5. Reject malformed, unavailable, wrong-chain, catching-up, and stale endpoints.
6. Select one healthy endpoint for the whole cycle.
7. Compute `finalized_tip = latest_rpc_height - 1`.
8. Read `indexer_state.last_finalized_height`.
9. If the database is empty, require `--start-height` or `INDEXER_START_HEIGHT`.
10. Plan the next range from `checkpoint + 1` or the bootstrap start height.
11. Process at most `batch_size` finalized heights, strictly sequentially.
12. Commit each height through the existing atomic PostgreSQL transaction.
13. Stop the batch on any failed height; the next cycle re-probes RPC and retries the same height.
14. If caught up, write no heights and sleep for `poll_interval_seconds`.

## Catch-up and steady state

For checkpoint `C` and finalized tip `T`, the next height is always `C + 1`. One cycle processes no more than `min(T - C, batch_size)` heights. The runner never skips intermediate heights and never jumps directly to the tip after downtime. When `C >= T`, the runner is in steady state: it records the probe cycle, writes no block data, and waits for the next poll.

## Failure handling

Fatal failures exit non-zero immediately: invalid configuration, chain identity mismatch, `FinalizedDataConflict`, advisory-lock contention, and unsupported database/schema state. Transient failures such as all RPC endpoints unavailable, RPC timeout, or temporary PostgreSQL connection failure sleep with bounded exponential backoff and retry without advancing the checkpoint. Successful progress resets the backoff to the configured base.

## Graceful shutdown

SIGINT and SIGTERM set a stop request. The runner checks the request before starting each height, so it does not begin another height after a stop. If the signal arrives while one height is being processed, the current single-height database transaction completes atomically or rolls back; then the runner exits before the next height. The foreground process logs the final checkpoint and shutdown reason.

## Out of scope

Systemd units, cron, Docker Compose, production PostgreSQL deployment, daemonization, PID-file supervision, backend API, FastAPI, frontend, Next.js, Prometheus, Telegram alerts, full genesis sync, and full transaction decoding remain separate future milestones.
