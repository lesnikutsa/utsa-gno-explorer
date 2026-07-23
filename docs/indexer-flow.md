# Indexer flow

## Transaction hashes

Successfully decoded transaction bytes are preserved exactly and hashed with SHA-256. The canonical Tendermint2 hash is uppercase 64-character hexadecimal without `0x`. Invalid Base64 is not hashed and remains nullable; decoding does not indicate execution success. `(block_height, tx_index)` identifies an indexed occurrence. Repeated hashes remain separate rows and the non-unique partial lookup index permits a future hash query to return multiple locations; Type and structured message parsing remain deferred.


This is a design checkpoint for the future continuous indexer. It is not an implementation plan for running a service in this issue.

## Per-cycle flow

1. Load configured RPC endpoints from runtime configuration, not from committed secrets.
2. Probe each endpoint with `/status` and append one `rpc_endpoint_checks` row per probe.
3. Reject malformed responses, wrong chain IDs, catching-up nodes, and endpoints outside the maximum height lag.
4. Select the first configured healthy endpoint within the acceptable lag from the highest healthy observed height.
5. Read latest RPC height `H` from the selected endpoint only to establish `finalized_tip = H - 1`.
6. Read `indexer_state.last_finalized_height`; set the next target finalized height to `S = last_finalized_height + 1`.
7. Process every `S` sequentially while `S <= finalized_tip`; never jump directly to `finalized_tip` after downtime.
8. For each `S`, fetch `/block?height=S`, `/commit?height=S`, and `/validators?height=S`.
9. Verify the parsed block height, commit header height, and validator-set height all equal `S`.
10. Commit exactly one complete height atomically, then advance the checkpoint only to `S` after success.

## Single-height transaction

Inside one PostgreSQL transaction for target finalized height `S`, the future indexer must:

1. upsert `blocks` for height `S`;
2. upsert ordered `transactions` for block `S`;
3. upsert `validators` from the validator set at `S`;
4. upsert `validator_set_members` for height `S`;
5. upsert `validator_signatures` for height `S`;
6. update current `rpc_endpoints` health and selected endpoint metadata;
7. append any endpoint check or selection rows that belong to the cycle;
8. update `indexer_state.last_finalized_height` to `S` only after all prior writes succeed.

If any statement fails, the transaction rolls back. The checkpoint must not advance after partial processing, and the next run must retry the same `S`.

## Signature calculation

- Build the expected validator set from `/validators?height=S`.
- Build parsed vote records from non-null precommits in `/commit?height=S`, keyed by validator signing address. Address matching is required for non-null votes; array position must not be the sole evidence of signing.
- Do not associate a null precommit with a validator by array position unless that relationship is explicitly verified in a future discovery task.
- Validate each non-zero `Vote.BlockID` and enclosing `Commit.BlockID` as complete BlockIDs: valid non-empty base64 hash, non-null non-negative part-set total, and valid non-empty base64 part-set hash. Compare hash, part-set total, and part-set hash. A non-null signature alone is not sufficient for signing.
- Store `vote_status = 'commit'` and `signed = true` only when the validator has a non-null precommit whose `Vote.BlockID` matches the enclosing `Commit.BlockID` and has a structurally usable base64 Ed25519 or Secp256k1 consensus signature that decodes to exactly 64 bytes.
- Store `vote_status = 'nil'` when the validator has a non-null vote with zero `Vote.BlockID`; nil votes are not signed for uptime.
- Store `vote_status = 'absent'` when the validator signing address is absent from the non-null precommit signer-address set.
- Store `vote_status = 'invalid'` when a non-null vote is malformed, has an unmatched address, or has a non-zero `Vote.BlockID` that does not match the enclosing commit and needs investigation.
- Nil and invalid votes may retain `raw_precommit` JSONB for audit; absent votes must not invent per-validator raw precommit data.

## RPC switching

Endpoint health is persisted in `rpc_endpoints` as current state and in `rpc_endpoint_checks` as append-only history. When endpoint health is checked or selected, the future indexer records:

- the endpoint URL via `rpc_endpoint_id`;
- health status;
- latest observed height;
- observed lag from the healthiest endpoint;
- whether the endpoint was selected for this cycle;
- switch reason when the selected endpoint changes;
- last error message for rejected endpoints.

The database stores endpoint URLs only. It must not store authentication headers, tokens, passwords, or private RPC credentials.

## Restart and resume

On startup, the future indexer reads `indexer_state.last_finalized_height`. The next candidate finalized height is always `last_finalized_height + 1`, subject to the current `finalized_tip = latest_rpc_height - 1`. Reprocessing a range is safe because writes are idempotent. Downtime must not create gaps: all intermediate heights from the checkpoint to the finalized tip are processed in order.

## Reorg and rollback considerations

The first explorer version assumes finalized TM2 heights are stable once they are at or below `finalized_tip`. If a mismatch is detected during reprocessing, the indexer should stop, log the conflicting height, and require explicit operator action before rewriting existing finalized data. Because block, transaction, validator-set, and signature rows all use the same target height `S`, rollback boundaries are consistent by height.

## Out of scope

This checkpoint does not add scheduler loops, worker processes, RPC clients beyond the existing prototype, database migrations, Docker Compose, API endpoints, or UI components. Follow-up verification must confirm exact live Gno TM2 precommit field paths for `Vote.BlockID`, enclosing `Commit.BlockID`, nil votes, and validator signing addresses before implementing the continuous indexer.

## Implemented bounded prototype

The current implementation is the bounded one-shot prototype in `scripts/index_range.py` and the `indexer/` package. It performs the same single-height transaction shape described above, but only for an explicit finite range chosen by the operator.

It is not a continuous production indexer. It has no infinite loop, no scheduler, no systemd unit, and no background worker. The future continuous service may reuse the parsing and database boundaries, but it must add operational supervision separately.

## Implemented foreground continuous runner

`scripts/run_indexer.py` adds a foreground continuous runner on top of the existing parsing and single-height transaction boundary. It is not a daemon and does not add systemd, cron, Docker Compose, production PostgreSQL deployment, backend API, frontend, metrics, or alerts.

### Continuous per-cycle flow

1. Verify that the dedicated PostgreSQL advisory-lock session is still live before attempting the cycle.
2. Read `indexer_state.last_finalized_height` first so a configured chain mismatch fails before writing RPC probe rows.
3. Probe every configured RPC endpoint once with `/status`.
4. Persist one `rpc_endpoint_checks` row per configured endpoint, even when no endpoint is selectable.
5. Select one healthy endpoint for the whole batch or raise a transient no-healthy-RPC error after probe persistence.
6. Compute `finalized_tip = latest_rpc_height - 1` from the selected endpoint.
7. If the database is empty, require `--start-height` or `INDEXER_START_HEIGHT`.
8. Plan the next range from `checkpoint + 1` or the bootstrap start height.
9. Process at most `batch_size` finalized heights, strictly sequentially.
10. Commit each height through the existing atomic PostgreSQL transaction.
11. Stop the batch on any failed height; the next attempted cycle re-probes RPC and retries the same height.
12. If caught up, write no heights and wait with a stop-aware poll interval.

### Continuous catch-up and steady state

For checkpoint `C` and finalized tip `T`, the next height is always `C + 1`. One cycle processes no more than `min(T - C, batch_size)` heights, and `batch_size` must not exceed `INDEXER_HARD_MAX_HEIGHTS`. The runner never skips intermediate heights and never jumps directly to the tip after downtime. When `C >= T`, the runner is in steady state: it records the probe cycle, writes no block data, and waits for the next poll.

For each individual height, the independent `block`, `commit`, and `validators` RPC requests run concurrently in at most three worker threads. Parsing begins only after all three payloads have completed successfully, so a request failure cannot produce a partial height. Different heights remain strictly sequential: the current height is fetched, parsed, written to PostgreSQL, and checkpointed before the next height starts. `INDEXER_BATCH_SIZE` is the number of heights planned per cycle, not the number of concurrently processed or written heights. The fetch improvement is bounded by the slowest of the three RPC methods rather than their combined latency. RPC failover retries another safe endpoint at the same height without changing these concurrency boundaries.

### Continuous exit codes and waits

`--once` performs exactly one attempted probe/catch-up cycle. It exits `0` after a successful or caught-up cycle and exits non-zero when that single attempt ends in a transient or fatal error.

`--max-cycles` counts every attempted cycle, including transient failures. The runner does not sleep after the final permitted cycle. It exits non-zero if every permitted cycle failed and no successful cycle completed; otherwise it exits `0` when the limit is reached.

Poll waits and transient backoff waits are stop-aware. SIGINT or SIGTERM during a wait requests shutdown promptly instead of waiting for the full interval.

### Advisory-lock behavior

The continuous runner uses a PostgreSQL advisory lock derived from the configured chain ID and held on a dedicated PostgreSQL session. The runner verifies that session before every cycle and exits non-zero if the session is lost, so it never indexes without a proven lock. Advisory lock close is best-effort; unlock or close failures are logged and do not mask the original exit reason.

### Continuous failure handling

Fatal failures exit non-zero immediately: invalid configuration, chain identity mismatch, `FinalizedDataConflict`, advisory-lock contention or loss, invalid checkpoint sequence, and unsupported database/schema state. Transient failures such as all RPC endpoints unavailable, RPC timeout, or psycopg `OperationalError`/`InterfaceError` sleep with bounded exponential backoff and retry without advancing the checkpoint. Successful progress resets the backoff to the configured base.

### Lock acquisition startup behavior

Advisory-lock acquisition uses the same bounded, stop-aware backoff as transient cycle failures. A transient psycopg `OperationalError` or `InterfaceError` while opening or acquiring the lock is retried before any indexing cycle starts. With `--once`, one failed lock-acquisition attempt exits non-zero. With `--max-cycles`, the runner uses that value as the startup lock-acquisition retry limit before any cycle is attempted. Without either option, startup acquisition continues with bounded backoff until the lock is acquired, a fatal error occurs, or SIGINT/SIGTERM requests shutdown.

The advisory-lock connection is configured for autocommit before `pg_try_advisory_lock` is executed. Liveness checks also run in autocommit mode, so the session-level lock remains held without leaving the connection idle in a transaction.

Empty RPC configuration is a fatal startup configuration error. The runner validates that the RPC URL list is non-empty before advisory-lock acquisition, before any backoff, and before any database write for heights or RPC checks. A configured but unavailable non-empty RPC list remains a transient RPC outage.

Advisory-lock acquisition is exception-safe: if the PostgreSQL connection is created but autocommit setup, cursor creation, `pg_try_advisory_lock`, or `fetchone` fails, the runner closes that exact connection best-effort, resets the stored connection reference, and retries later with a fresh connection when the failure is transient.

## RPC failover and chain continuity

`GNO_RPC_URLS` is an ordered priority list. Every full cycle probes every configured URL with `/status`; malformed, unreachable, wrong-chain, catching-up, excessively lagging, or checkpoint-inadequate endpoints are rejected. Selection always prefers the first safe configured endpoint rather than the fastest or highest endpoint. The persistence cycle enables configured URLs, disables same-chain URLs removed from configuration, clears selection from removed URLs, and leaves other chains untouched.

A non-empty database supplies a trusted checkpoint anchor consisting of `indexer_state.last_finalized_height` and the corresponding uppercase `blocks.block_hash_hex`. Before an endpoint is used, the indexer requests that checkpoint through `/block`, safely decodes the canonical BlockID hash, and requires an exact match. A matching `chain_id` alone cannot distinguish a fork, a reused network identifier, or an endpoint that moved to different history. A pruned endpoint that cannot return the anchor is therefore unsafe. An empty database has no anchor and retains the configured bootstrap-height behavior.

For every subsequent height `N`, `header.last_block_id.hash` must decode to the canonical hash of persisted height `N-1`. This check occurs before parsing and before the atomic database write. After a successful write, the newly decoded canonical hash becomes the expected parent for `N+1`.

Block, commit, and validators requests for one endpoint and one height remain concurrent. Heights and PostgreSQL writes remain sequential. An endpoint-specific RPC, transport, malformed-payload, anchor, or parent-continuity failure removes that candidate for the current height and immediately tries the next safe URL at the same height. The replacement proves the current checkpoint before fetching the height. Database errors, chain identity errors, finalized-data conflicts, checkpoint sequence violations, advisory-lock loss, and unclassified programming errors remain fatal and are never converted into failover.

The actual successful endpoint is persisted as selected and is linked from the next `indexer_state` write; switch checks include a short non-secret reason. Global bounded backoff starts only after every candidate fails. With one URL, the same rule means no write and an unchanged checkpoint until that endpoint recovers. Existing API pages continue serving persisted data, while health becomes degraded once all enabled endpoints are unhealthy, checks are stale, or indexer lag is excessive. A failed backup alone does not degrade health when another enabled endpoint is healthy and lag is acceptable; disabled historical endpoints cannot mask an outage.

Different networks must use separate PostgreSQL databases and runtime instances. This failover mechanism is intentionally not a multi-chain selector.
