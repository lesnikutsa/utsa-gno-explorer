# Indexer flow

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
- Build the signer-address set from non-null precommits in `/commit?height=S`.
- Do not associate a null precommit with a validator by array position unless that relationship is explicitly verified in a future discovery task.
- A validator is marked missed when its signing address is absent from the non-null signer-address set.
- A validator with a matching signed precommit is stored as `signed = true`.
- Store raw or parsed precommit details only for matched signer addresses and only in limited JSONB for audit and parser debugging.

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

This checkpoint does not add scheduler loops, worker processes, RPC clients beyond the existing prototype, database migrations, Docker Compose, API endpoints, or UI components.
