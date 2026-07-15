# Bounded indexer operator runbook

This runbook is for safe test execution of the bounded prototype only. It is not a production operations guide.

## Prepare

1. Create a temporary PostgreSQL database.
2. Apply `database/schema.sql`.
3. Configure non-secret environment variables from `.env.example`.
4. Choose a small finalized range, usually 3 to 10 heights.

## Dry run

```bash
python scripts/index_range.py --start-height 100 --max-heights 3 --dry-run
```

Dry run fetches and parses RPC data but does not write PostgreSQL rows.

## Write run

```bash
python scripts/index_range.py --start-height 100 --max-heights 3
```

Run the same command a second time to confirm idempotency. The logical row counts should not increase for the same range.

## Failure and resume check

If a run fails while processing height `S`, verify that `indexer_state.last_finalized_height` remains at `S - 1`. The next run should retry `S`; it must not skip to a later finalized height.

## Cleanup

For disposable validation databases, either drop the database or run the cleanup query documented in `database/README.md`.

## Foreground continuous validation

The continuous runner is intended for foreground validation against a temporary database:

```bash
python scripts/run_indexer.py --start-height 100 --once --batch-size 3
python scripts/run_indexer.py --start-height 100 --max-cycles 5 --batch-size 2
python scripts/run_indexer.py --start-height 100 --batch-size 10
```

Use Ctrl+C to request graceful shutdown. The process exits after the current height transaction is complete and before starting the next height. SIGTERM follows the same behavior.

## Advisory-lock diagnostics

Only one continuous indexer per `GNO_CHAIN_ID` can run. If a second process starts while the first holds the lock, it exits with an advisory-lock error. Inspect advisory locks from PostgreSQL with the query in `database/README.md`. Do not use PID files as supervision or locking.

## Recovery after transient failure

For all-RPC-unavailable, timeout, or temporary PostgreSQL connection failures, the runner logs the retry height and bounded backoff. The checkpoint is unchanged, so the next cycle repeats the same missing height after probing all RPC endpoints again.

## Remaining follow-up milestones

Production PostgreSQL setup, systemd supervision, backend API, and frontend remain separate work and are intentionally not part of this validation runbook.
