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

## Continuous exit-code behavior

`--once` attempts exactly one cycle. It exits `0` for a successful or caught-up cycle and exits non-zero when that only attempt ends in a transient or fatal error.

`--max-cycles` counts every attempted cycle, including transient failures. The runner does not sleep after the final permitted cycle. It exits non-zero if every permitted cycle failed and no successful cycle completed; otherwise it exits `0` when the limit is reached.

## Lock-acquisition startup behavior

The advisory-lock session uses autocommit. Transient PostgreSQL `OperationalError` or `InterfaceError` failures while connecting or acquiring the lock are retried with bounded stop-aware backoff before any indexing cycle starts. `--once` exits non-zero after one failed lock-acquisition attempt. `--max-cycles` also bounds startup lock-acquisition attempts before the first cycle. SIGINT or SIGTERM during lock-acquisition backoff exits promptly.

An empty `GNO_RPC_URLS` configuration is fatal and exits with code `1` before advisory-lock acquisition. Configure at least one endpoint to distinguish operator misconfiguration from a transient outage of a non-empty endpoint list.

If advisory-lock acquisition fails after opening a PostgreSQL connection, the runner closes that failed connection best-effort before retrying. A later retry uses a fresh connection, so any session-level lock that may have been acquired is naturally released with the failed session.

## Production runtime

Use [Production deployment](production-deployment.md) for the production-oriented runtime introduced for PostgreSQL 16 Compose plus host systemd. The production flow is separate from local development:

- development and tests may use `.env` and temporary databases;
- production secrets live outside Git under `/etc/utsa-gno-explorer`;
- PostgreSQL is started explicitly with Docker Compose and binds only to `127.0.0.1`;
- the continuous indexer runs in the foreground under systemd and logs to journald;
- schema initialization, backup, validation restore, destructive restore, upgrade, and rollback are manual operator actions.

Quick production checks:

```bash
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env ps
systemctl status utsa-gno-indexer.service
journalctl -u utsa-gno-indexer.service -n 100 --no-pager
python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer --retention 14
```

Automated PostgreSQL backups are installed as a root-owned systemd timer. The Compose file has a stable default project name, so normal Compose and backup commands work without exporting `COMPOSE_PROJECT_NAME`; set that variable only for isolated integration or validation environments. Install and enable the timer:

```bash
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-explorer-backup.service \
  /etc/systemd/system/utsa-gno-explorer-backup.service
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-explorer-backup.timer \
  /etc/systemd/system/utsa-gno-explorer-backup.timer
systemctl daemon-reload
systemctl enable --now utsa-gno-explorer-backup.timer
```

Manual test and status commands:

```bash
systemctl start utsa-gno-explorer-backup.service
systemctl status utsa-gno-explorer-backup.service
systemctl status utsa-gno-explorer-backup.timer
systemctl list-timers utsa-gno-explorer-backup.timer
journalctl -u utsa-gno-explorer-backup.service
```

Verify backup archives:

```bash
find /var/backups/utsa-gno-explorer \
  -maxdepth 1 \
  -type f \
  -name 'utsa-gno-explorer-*.dump'
```

Backups use `pg_dump -Fc`, write archives as `.part` first, validate each archive with `pg_restore --list`, then atomically rename successful backups. Retention keeps 14 successful backups. Backup files and the backup directory remain root-only. The daily backup is online and does not stop the indexer. Before destructive upgrades, stop the indexer and create a separate checkpoint-aligned backup.
