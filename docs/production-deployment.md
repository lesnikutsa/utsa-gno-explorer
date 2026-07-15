# Production deployment

This guide packages the existing foreground continuous indexer without changing indexing semantics. Production uses PostgreSQL 16 in Docker Compose and runs the Python indexer on the host through systemd. Production deployment is operator-controlled: no container entrypoint or systemd unit runs `git pull`, schema updates, or destructive restore automatically.

## Runtime layout

- Repository: `/opt/utsa-gno-explorer`
- Virtualenv: `/opt/utsa-gno-explorer/.venv`
- PostgreSQL Compose file: `deploy/postgres/compose.yml`
- PostgreSQL environment example: `deploy/postgres/postgres.env.example`
- systemd unit: `deploy/systemd/utsa-gno-indexer.service`
- Indexer environment example: `deploy/systemd/indexer.env.example`
- External production secrets and environment: `/etc/utsa-gno-explorer/`
- Default PostgreSQL data directory: `/var/lib/utsa-gno-explorer/postgres`
- Default backup directory: `/var/backups/utsa-gno-explorer`

## Production secrets

Create only real production files outside the repository:

```bash
getent group utsa-gno >/dev/null || sudo groupadd --system utsa-gno
id -u utsa-gno >/dev/null 2>&1 || sudo useradd --system --gid utsa-gno --home-dir /nonexistent --shell /usr/sbin/nologin utsa-gno
sudo install -d -o root -g utsa-gno -m 750 /etc/utsa-gno-explorer
sudo install -d -o root -g root -m 755 /var/lib/utsa-gno-explorer
sudo install -d -o 999 -g 999 -m 700 /var/lib/utsa-gno-explorer/postgres
sudo install -o root -g root -m 600 deploy/postgres/postgres.env.example /etc/utsa-gno-explorer/postgres.env
sudo install -o root -g utsa-gno -m 640 deploy/systemd/indexer.env.example /etc/utsa-gno-explorer/indexer.env
sudo install -o root -g root -m 600 /dev/null /etc/utsa-gno-explorer/postgres-password
sudo editor /etc/utsa-gno-explorer/postgres.env
sudo editor /etc/utsa-gno-explorer/indexer.env
sudo sh -c 'umask 077; stty -echo; printf "PostgreSQL password: " >&2; read password; stty echo; printf "\n" >&2; printf "%s" "$password" > /etc/utsa-gno-explorer/postgres-password'
```

Do not print or paste `DATABASE_URL`, database passwords, or credential-bearing RPC URLs in logs, tickets, or terminal transcripts. The PostgreSQL data directory must be writable only by the PostgreSQL container runtime identity. The repository and `.venv` under `/opt/utsa-gno-explorer` must be readable/executable by `utsa-gno` but must not be writable by the service user; use root-owned files with group/other read and execute bits as appropriate for the host policy.

## PostgreSQL Compose architecture

`deploy/postgres/compose.yml` runs only `postgres:16.14-bookworm`. It binds `127.0.0.1:${POSTGRES_PORT}:5432`, so PostgreSQL is reachable from the host and systemd service but is not exposed on a public host interface. Data is persisted through the host bind mount `${POSTGRES_DATA_DIR:-/var/lib/utsa-gno-explorer/postgres}`; the same safe default is present in Compose, while `/etc/utsa-gno-explorer/postgres.env` remains the operator-controlled production source of truth. The password is provided through Docker Compose secret file `/etc/utsa-gno-explorer/postgres-password`; the real password is not committed. `POSTGRES_PASSWORD_FILE` is used by the official PostgreSQL image only when initializing a new empty data directory; replacing the password file later does not rotate the existing database role password. Password rotation requires an explicit `ALTER ROLE` inside PostgreSQL and a matching `/etc/utsa-gno-explorer/indexer.env` update. Do not type literal passwords directly into shell commands or shell history.

Start PostgreSQL explicitly:

```bash
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env up -d postgres
```

Validate the Compose model before starting it:

```bash
docker compose -f deploy/postgres/compose.yml --env-file deploy/postgres/postgres.env.example config
```

## Database initialization

Apply schema only by an explicit operator command. The initialization script creates the schema transactionally only when the public schema is empty; otherwise it performs explicit catalog compatibility validation and fails on incompatible or partial schemas. It stops on SQL errors and does not drop tables or databases.

```bash
set -a
. /etc/utsa-gno-explorer/indexer.env
set +a
python scripts/init_database.py
```

For the first empty database, `INDEXER_START_HEIGHT` is mandatory in `/etc/utsa-gno-explorer/indexer.env` or as a one-time CLI argument. After the first checkpoint exists, normal restarts resume from `indexer_state`.

## systemd lifecycle

Install the unit and run it in the foreground under journald supervision:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/utsa-gno-indexer.service /etc/systemd/system/utsa-gno-indexer.service
sudo systemctl daemon-reload
sudo systemctl enable --now utsa-gno-indexer.service
```

The service uses user and group `utsa-gno`, `WorkingDirectory=/opt/utsa-gno-explorer`, `EnvironmentFile=/etc/utsa-gno-explorer/indexer.env`, and `ExecStart=/opt/utsa-gno-explorer/.venv/bin/python scripts/run_indexer.py`. It does not pass `--start-height`; bootstrap height belongs in the external environment only for first initialization. `ExecStartPre` runs `scripts/wait_for_postgres.py`, `Restart=on-failure` handles process failures, `KillSignal=SIGTERM` requests graceful shutdown, and `TimeoutStopSec=180` allows the current atomic height transaction to finish. The existing PostgreSQL advisory lock remains the primary duplicate-indexer protection.

## Operational checks

```bash
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env config
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env ps
docker inspect --format '{{json .State.Health}}' utsa-gno-postgres
ss -ltnp | grep ':5432' | grep '127.0.0.1'
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select table_name from information_schema.tables where table_schema = current_schema() order by table_name;"'
systemctl status utsa-gno-indexer.service
journalctl -u utsa-gno-indexer.service -n 100 --no-pager
systemd-analyze verify /etc/systemd/system/utsa-gno-indexer.service
systemd-analyze security utsa-gno-indexer.service
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select locktype, granted from pg_locks where locktype = chr(97)||chr(100)||chr(118)||chr(105)||chr(115)||chr(111)||chr(114)||chr(121);"'
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select chain_id,last_finalized_height,finalized_tip_height,updated_at from indexer_state;"'
python scripts/inspect_rpc.py
sudo systemctl restart utsa-gno-indexer.service
docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env restart postgres
sudo reboot
sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/indexer.env; set +a; cd /opt/utsa-gno-explorer && .venv/bin/python scripts/run_indexer.py --once'
python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer
pg_restore --list /var/backups/utsa-gno-explorer/utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump >/dev/null
```

The second indexer command is expected to fail while the service owns the advisory lock.

## Backup

Backups use `pg_dump -Fc` through the PostgreSQL Compose container. Online logical backups are acceptable while the indexer is running for routine recovery points because `pg_dump` reads a consistent database snapshot; stop the indexer first when you need a backup tied to a known final checkpoint before an upgrade or destructive restore.

```bash
python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer --retention 14
```

The script uses umask `077`, writes a `.part` file first, validates the archive with `pg_restore --list`, atomically renames only after success, and deletes only older files matching `utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump`. It never deletes the newest backup it just created and does not stop the indexer.

## Validation restore

Never test restores against production first. Safe validation flow:

1. Stop the indexer when validating a recovery point for production replacement: `sudo systemctl stop utsa-gno-indexer.service`.
2. Create the latest backup: `python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer`.
3. Start a separate empty validation database with an isolated Compose project.
4. Restore the archive there.
5. Verify all eight tables.
6. Verify `indexer_state`.
7. Verify counts for `blocks`, `transactions`, and `validator_signatures`.
8. Decide whether production restore is necessary only after validation succeeds.

Example isolated validation database:

```bash
docker run --rm --name utsa-gno-restore-validation -e POSTGRES_USER=validation -e POSTGRES_DB=validation -e POSTGRES_PASSWORD=validation -p 127.0.0.1:55432:5432 -d postgres:16.14-bookworm
PGPASSWORD=validation pg_isready -h 127.0.0.1 -p 55432 -U validation -d validation
until PGPASSWORD=validation pg_isready -h 127.0.0.1 -p 55432 -U validation -d validation; do sleep 1; done
PGPASSWORD=validation pg_restore -h 127.0.0.1 -p 55432 -U validation -d validation --no-owner --no-privileges --exit-on-error --single-transaction /var/backups/utsa-gno-explorer/utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump
PGPASSWORD=validation psql -h 127.0.0.1 -p 55432 -U validation -d validation -v ON_ERROR_STOP=1 -c "select array_agg(table_name order by table_name) from information_schema.tables where table_schema = current_schema() having array_agg(table_name order by table_name) = ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators'];"
PGPASSWORD=validation psql -h 127.0.0.1 -p 55432 -U validation -d validation -v ON_ERROR_STOP=1 -c "select * from indexer_state;"
PGPASSWORD=validation psql -h 127.0.0.1 -p 55432 -U validation -d validation -v ON_ERROR_STOP=1 -c "select (select count(*) from blocks) blocks, (select count(*) from transactions) transactions, (select count(*) from validator_signatures) signatures;"
PGPASSWORD=validation psql -h 127.0.0.1 -p 55432 -U validation -d validation -v ON_ERROR_STOP=1 -c "select last_finalized_height <= finalized_tip_height as checkpoint_consistent from indexer_state;"
docker stop utsa-gno-restore-validation
```

## Destructive production restore

Destructive commands can remove production data. They must be run manually only after validation restore succeeds and a recovery decision is recorded.

```bash
# DESTRUCTIVE: stop writers first.
sudo systemctl stop utsa-gno-indexer.service
# DESTRUCTIVE: replace production database contents only with an operator-approved backup.
# Example command intentionally not automated:
# docker compose ... exec -T postgres pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" < approved-backup.dump
sudo systemctl start utsa-gno-indexer.service
```

## Upgrade procedure

1. `sudo systemctl stop utsa-gno-indexer.service`.
2. `systemctl is-active utsa-gno-indexer.service` and confirm it is inactive.
3. `python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer`.
4. Save the current commit or tag: `git rev-parse HEAD`.
5. Update the repository manually; systemd never runs `git pull`.
6. Rebuild the virtualenv: `.venv/bin/python -m pip install -r requirements.txt`.
7. Run automated tests: `python -m unittest discover -s tests -v`.
8. Check schema compatibility with `python scripts/init_database.py` against the target database.
9. `sudo systemctl start utsa-gno-indexer.service`.
10. Check journal output and checkpoint progression.

## PostgreSQL minor-version upgrade

1. Create and validate a backup.
2. Stop the indexer: `sudo systemctl stop utsa-gno-indexer.service`.
3. Pull the pinned PostgreSQL 16 minor image manually: `docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env pull postgres`.
4. Recreate only the PostgreSQL container: `docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env up -d --no-deps postgres`.
5. Confirm the server major version remains 16 and healthcheck is healthy.
6. Start the indexer and verify checkpoint progression. Systemd never pulls images automatically.

## Rollback procedure

Stop the service, return the repository to the previous verified Git tag or commit, restore the matching requirements and virtualenv, and start the service. Restore the database only if schema or data changes require it. Any database rollback must first pass the validation restore process above, then use a clearly marked destructive production restore. After startup, verify the checkpoint and finalized tip continue progressing.

## Development and test deployment

For development, use `.env`, temporary PostgreSQL databases, `scripts/index_range.py`, and `scripts/run_indexer.py` directly as described in `README.md`. Do not copy production secrets into the repository.
