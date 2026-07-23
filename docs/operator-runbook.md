# Bounded indexer operator runbook

This runbook is for safe test execution of the bounded prototype only. It is not a production operations guide.

## Active Topaz configuration

The current single-network runtime is **Gno.land Topaz Testnet** (`topaz-1`). Use RPCs in
this order: `https://rpc.topaz.testnets.gno.land`, `https://gnoland-testnet-rpc.itrocket.net`, and `https://topaz.rpc.onbloc.xyz`. A new Topaz database must be empty, must start at block `1`, and must not
contain Testnet 13 rows or checkpoints. Database recreation and deployment are separate,
manual operator actions.

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
python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer --retention 3
```

Automated PostgreSQL backups are installed as a root-owned systemd timer. The Compose file has a stable default project name, so normal Compose and backup commands work without exporting `COMPOSE_PROJECT_NAME`; set that variable only for isolated integration or validation environments. Enable the timer only after the updated service and timer units are installed and `systemctl daemon-reload` has completed; installing these files does not itself enable the production timer:

```bash
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-explorer-backup.service \
  /etc/systemd/system/utsa-gno-explorer-backup.service
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-explorer-backup.timer \
  /etc/systemd/system/utsa-gno-explorer-backup.timer
systemctl daemon-reload
install -d -o root -g root -m 0700 \
  /var/backups/utsa-gno-explorer
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

Backups use `pg_dump -Fc`, write archives as `.part` first, validate each archive with `pg_restore --list`, then atomically rename successful backups. Only after that validation and finalization does rotation retain the 3 newest successful files matching `utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump`. Manually named recovery dumps, validation restore files, checksum files, and unrelated files are outside automatic rotation. Backup files and the backup directory remain root-only. The systemd service sets `DOCKER_CONFIG=/run/utsa-gno-explorer-backup`, using its private `RuntimeDirectory=utsa-gno-explorer-backup` as Docker CLI configuration storage so the hardened `ProtectHome=true` sandbox does not depend on `/root/.docker`. The daily backup is online and does not stop the indexer. Before destructive upgrades, stop the indexer and create a separate checkpoint-aligned backup.

## Apply the Valopers schema migration

After merge and operator review, `python scripts/persist_valopers_snapshot.py`
collects the complete registry from one healthy RPC at one pinned height. In one PostgreSQL
transaction it takes a dedicated transaction advisory lock, validates current state,
deletes profiles, inserts the ordered replacement, writes singleton state, verifies it,
and commits. Failures roll back. Stale and divergent same-height snapshots are rejected;
identical snapshots are unchanged. Empty registries are zero profiles plus one state row.
The API and frontend read the persisted profiles after each successful refresh.

Fresh empty databases use `python scripts/init_database.py`. For an existing
production database, first create and verify a backup, then stop the indexer and
run:

```console
python scripts/migrate_valopers_schema.py
python scripts/init_database.py
```

The explicit migration accepts only the exact legacy eight-table catalog or the
already-compatible ten-table catalog. It adds `valoper_profiles` and
`valopers_snapshot_state` transactionally, validates the exact complete catalog
before commit, and leaves existing indexed rows untouched. Any error rolls back.
A successful migration can be rerun safely. It is never applied automatically;
restart the indexer only after validation.

The read-only validator API (version 0.8.0) enriches validator identities from the
persisted official Valopers snapshot using exact, case-sensitive `signing_address` equality.
The API reads PostgreSQL only and never reads Telegram bot storage or Telegram user data.
Valopers metadata is separate from consensus indexing: TM2 RPC provides consensus identity
and activity but cannot provide official monikers. Install the hourly refresh only after
the schema migration is complete. The timer reuses the existing atomic persistence script;
it does not add Valopers collection to the block-indexing loop.

```bash
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-valopers-refresh.service \
  /etc/systemd/system/utsa-gno-valopers-refresh.service
install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-valopers-refresh.timer \
  /etc/systemd/system/utsa-gno-valopers-refresh.timer
systemctl daemon-reload
systemctl start utsa-gno-valopers-refresh.service
journalctl \
  -u utsa-gno-valopers-refresh.service \
  -n 100 \
  --no-pager
systemctl enable --now utsa-gno-valopers-refresh.timer
systemctl status utsa-gno-valopers-refresh.timer
systemctl list-timers \
  utsa-gno-valopers-refresh.timer \
  --all \
  --no-pager
```

The repository change itself does not install or enable these production units. After the
manual pre-enable service test succeeds, `utsa-gno-valopers-refresh.timer` runs
`utsa-gno-valopers-refresh.service` hourly at the beginning of the hour, delayed randomly
by up to five minutes. `Persistent=true` catches up a missed occurrence after the server
returns. Inspect failures in the service journal. To disable future runs:

```bash
systemctl disable --now utsa-gno-valopers-refresh.timer
```

Successful runs update moniker, operator address, signing gpub, description, and server
type. Validators not registered in the Valopers realm continue to display their signing
address. An RPC, chain-ID, pagination, identity-validation, or PostgreSQL failure returns
non-zero and preserves the last successful snapshot through the existing validation,
transaction rollback, and advisory-lock behavior. The API and frontend keep using that
snapshot; the next timer occurrence retries without stopping the indexer.

The full Validators table and Overview validator identities link to validator detail pages.
The full table locally filters its loaded active set by official moniker or consensus signing
address. Detail pages refresh every 2 seconds and present Current Status, 100 actual indexed
signing blocks with all supported signing states, and official profile and public-key fields.
Peers & Decentralization Map remains a coming-soon presentation area.

Production already running the compatible pre-release state, including commit
`818cee6a5d0dc8c8817e8ef3fc03af97d35aeeab`, needs only the metadata update: edit
`/etc/utsa-gno-explorer/api.env` through the approved operator process, set
`API_VERSION=0.8.0`, and restart only `utsa-gno-api.service`. After schema compatibility is
established, this metadata-only step requires no database migration or indexer restart.
Frontend deployment remains operator-controlled.

A deployment upgrading from `v0.5.0-production-runtime`, or any deployment without the
compatible Valopers tables and API-role privilege, must first follow the existing
operator-controlled Valopers schema migration and API-role grant procedure in the production
deployment guide. No migration is automatic.
