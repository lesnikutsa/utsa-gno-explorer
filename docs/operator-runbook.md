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
