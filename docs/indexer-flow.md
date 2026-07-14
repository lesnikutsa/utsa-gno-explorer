# Indexer flow

This is a design checkpoint for the future continuous indexer. It is not an implementation plan for running a service in this issue.

## Per-cycle flow

1. Load configured RPC endpoints from runtime configuration, not from committed secrets.
2. Probe each endpoint with `/status`.
3. Reject malformed responses, wrong chain IDs, catching-up nodes, and endpoints outside the maximum height lag.
4. Select the first configured healthy endpoint within the acceptable lag from the highest healthy observed height.
5. Read latest height `H` from the selected endpoint.
6. Fetch `/block?height=H` for latest block metadata and transactions.
7. Set finalized signing height to `H - 1`.
8. Fetch `/commit?height=H-1` and `/validators?height=H-1`.
9. Verify the parsed commit height and validator-set height both equal `H - 1`.
10. Process the finalized height inside one database transaction.

## Single-height transaction

Inside one PostgreSQL transaction, the future indexer must:

1. upsert `blocks` for height `H`;
2. upsert ordered `transactions` for block `H`;
3. upsert `validators` from the validator set at `H - 1`;
4. upsert `validator_set_members` for finalized height `H - 1`;
5. upsert `validator_signatures` for finalized height `H - 1`;
6. update `rpc_endpoints` health and selected endpoint metadata;
7. update `indexer_state.last_finalized_height` to `H - 1` only after all prior writes succeed.

If any statement fails, the transaction rolls back. The checkpoint must not advance after partial processing.

## Signature calculation

- Build the expected validator set from `/validators?height=H-1`.
- Build the signer set from non-null precommits in `/commit?height=H-1`.
- A `null` precommit is a missed signature for the validator at the corresponding commit position.
- A validator in the validator set with no matching non-null precommit signer is stored as `signed = false`.
- A validator with a matching signed precommit is stored as `signed = true`.
- Store raw or parsed precommit details only in limited JSONB for audit and parser debugging.

## RPC switching

Endpoint health is persisted in `rpc_endpoints`. When the selected endpoint changes, the future indexer records:

- the endpoint URL;
- health status;
- latest observed height;
- observed lag from the healthiest endpoint;
- selection timestamp;
- last error message for rejected endpoints.

The database stores endpoint URLs only. It must not store authentication headers, tokens, passwords, or private RPC credentials.

## Restart and resume

On startup, the future indexer reads `indexer_state.last_finalized_height`. The next candidate finalized height is `last_finalized_height + 1`, subject to the current latest available finalized height from RPC. Reprocessing a range is safe because writes are idempotent.

## Reorg and rollback considerations

The first explorer version assumes finalized TM2 heights are stable after `H - 1`. If a mismatch is detected during reprocessing, the indexer should stop, log the conflicting height, and require explicit operator action before rewriting existing finalized data.

## Out of scope

This checkpoint does not add scheduler loops, worker processes, RPC clients beyond the existing prototype, database migrations, Docker Compose, API endpoints, or UI components.
