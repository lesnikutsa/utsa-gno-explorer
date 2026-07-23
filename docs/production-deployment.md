# Production deployment

## Transaction-hash migration

Stop the production indexer before running `python scripts/migrate_transaction_hashes.py`. The additive, transactional migration backfills historical decoded rows from `transactions.decoded_bytes`, checks format, validates constraints, and creates a non-unique partial lookup index. Repeated hashes are preserved because `(block_height, tx_index)`, not the hash, identifies an occurrence; future hash lookup may return multiple locations. Do not run it concurrently with ingestion. The safe order is: stop indexer, migrate/backfill, update application code, restart API, restart indexer, and verify historical and new hashes. No PostgreSQL extension or destructive table recreation is used, and Base64 decoding does not indicate execution success. Structured Type/message parsing remains deferred.


This guide packages the existing foreground continuous indexer without changing indexing semantics. Production uses PostgreSQL 16 in Docker Compose and runs the Python indexer on the host through systemd. Production deployment is operator-controlled: no container entrypoint or systemd unit runs `git pull`, schema updates, or destructive restore automatically.

## Active Topaz runtime configuration

The single-network runtime targets **Gno.land Topaz Testnet** with chain ID `topaz-1`.
Configure `GNO_RPC_URLS` in this exact order: `https://rpc.topaz.testnets.gno.land`, `https://gnoland-testnet-rpc.itrocket.net`, and `https://topaz.rpc.onbloc.xyz`. Set
`INDEXER_START_HEIGHT=1`. Topaz is a fresh chain, not a continuation or hardfork replay of
Testnet 13: create the Explorer database empty and never reuse Testnet 13 rows or checkpoints.
Database replacement and production deployment remain explicit operator operations outside
this repository change.

## Runtime layout

- Repository: `/opt/utsa-gno-explorer`
- Virtualenv: `/opt/utsa-gno-explorer/.venv`
- PostgreSQL Compose file: `deploy/postgres/compose.yml`
- PostgreSQL environment example: `deploy/postgres/postgres.env.example`
- Indexer systemd unit: `deploy/systemd/utsa-gno-indexer.service`
- API systemd unit: `deploy/systemd/utsa-gno-api.service`
- API environment example: `deploy/systemd/api.env.example`
- Indexer environment example: `deploy/systemd/indexer.env.example`
- External production secrets and environment: `/etc/utsa-gno-explorer/`
- Default PostgreSQL data directory: `/var/lib/utsa-gno-explorer/postgres`
- Default backup directory: `/var/backups/utsa-gno-explorer`
- Frontend source: `/opt/utsa-gno-explorer/frontend`
- Frontend build output: `/opt/utsa-gno-explorer/frontend/dist`
- Nginx frontend webroot: `/var/www/utsa-gno-explorer`

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

`deploy/postgres/compose.yml` sets a stable Compose project name with `name: ${COMPOSE_PROJECT_NAME:-utsa-gno-explorer}` and runs only `postgres:16.14-bookworm`. It binds `127.0.0.1:${POSTGRES_PORT}:5432`, so PostgreSQL is reachable from the host and systemd service but is not exposed on a public host interface. Data is persisted through the host bind mount `${POSTGRES_DATA_DIR:-/var/lib/utsa-gno-explorer/postgres}`; the same safe default is present in Compose, while `/etc/utsa-gno-explorer/postgres.env` remains the operator-controlled production source of truth. The password is provided through Docker Compose secret file `/etc/utsa-gno-explorer/postgres-password`; the real password is not committed. `POSTGRES_PASSWORD_FILE` is used by the official PostgreSQL image only when initializing a new empty data directory; replacing the password file later does not rotate the existing database role password. Password rotation requires an explicit `ALTER ROLE` inside PostgreSQL and a matching `/etc/utsa-gno-explorer/indexer.env` update. Do not type literal passwords directly into shell commands or shell history.

Start PostgreSQL explicitly. The default Compose project is `utsa-gno-explorer`; set `COMPOSE_PROJECT_NAME` only for isolated integration or validation environments that intentionally use an alternate project identity:

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

Backups use `pg_dump -Fc` through the PostgreSQL Compose container. Online logical backups are acceptable while the indexer is running for routine daily recovery points because `pg_dump` reads a consistent database snapshot; the daily backup does not stop the indexer. Before destructive upgrades, create a separate checkpoint-aligned backup after stopping the indexer.

Manual backup command:

```bash
python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer --retention 14
```

Install the automated backup timer:

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

Manually test and inspect the timer:

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

The service runs as root so it can access Docker without adding `utsa-gno` to the docker group, logs to journald, uses restrictive `UMask=0077`, and passes only file paths and non-secret options in argv. Backup files and the backup directory remain root-only. The systemd service sets `DOCKER_CONFIG=/run/utsa-gno-explorer-backup`, using its private `RuntimeDirectory=utsa-gno-explorer-backup` as Docker CLI configuration storage so the hardened `ProtectHome=true` sandbox does not depend on `/root/.docker`. The script uses umask `077`, writes a `.part` file first, validates the archive with `pg_restore --list`, atomically renames only after success, and deletes only older files matching `utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump`. Retention keeps 14 successful backups. It never deletes the newest backup it just created and does not stop the indexer.

## Validation restore

Never test restores against production first. Safe validation flow:

1. Stop the indexer when validating a recovery point for production replacement: `sudo systemctl stop utsa-gno-indexer.service`.
2. Create the latest backup: `python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer`.
3. Start a separate empty validation database with an isolated Compose project.
4. Restore the archive there.
5. Verify an exact supported schema: the legacy eight-table catalog for a pre-migration backup, or the current ten-table catalog after migration.
6. Verify `indexer_state`.
7. Verify counts for `blocks`, `transactions`, and `validator_signatures`.
8. Decide whether production restore is necessary only after validation succeeds.

Example isolated validation database:

```bash
set -euo pipefail
VALIDATION_CONTAINER="utsa-gno-restore-validation"
VALIDATION_PASSWORD_FILE="$(mktemp)"
cleanup_restore_validation() {
  docker rm -f "$VALIDATION_CONTAINER" >/dev/null 2>&1 || true
  rm -f "$VALIDATION_PASSWORD_FILE"
}
trap cleanup_restore_validation EXIT
umask 077
python - <<'PY' >"$VALIDATION_PASSWORD_FILE"
import secrets
print(secrets.token_urlsafe(32))
PY
docker run --name "$VALIDATION_CONTAINER" \
  -e POSTGRES_USER=validation \
  -e POSTGRES_DB=validation \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
  -v "$VALIDATION_PASSWORD_FILE:/run/secrets/postgres_password:ro" \
  -d postgres:16.14-bookworm
for attempt in $(seq 1 60); do
  if docker exec "$VALIDATION_CONTAINER" sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    echo "validation PostgreSQL readiness timed out" >&2
    exit 1
  fi
  sleep 1
done
docker exec -i "$VALIDATION_CONTAINER" sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error --single-transaction' \
  < /var/backups/utsa-gno-explorer/utsa-gno-explorer-YYYYMMDDTHHMMSSZ.dump
docker exec -i "$VALIDATION_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
DO $$
DECLARE
  legacy_expected_tables text[] := ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators'];
  current_expected_tables text[] := ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators','valoper_profiles','valopers_snapshot_state'];
  actual_tables text[];
  state_rows integer;
  checkpoint_height bigint;
  tip_height bigint;
BEGIN
  SELECT array_agg(table_name ORDER BY table_name)
    INTO actual_tables
    FROM information_schema.tables
   WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
  IF actual_tables IS DISTINCT FROM legacy_expected_tables
     AND actual_tables IS DISTINCT FROM current_expected_tables THEN
    RAISE EXCEPTION 'validation failed: expected exact legacy % or current %, got %', legacy_expected_tables, current_expected_tables, actual_tables;
  END IF;

  SELECT count(*), max(last_finalized_height), max(finalized_tip_height)
    INTO state_rows, checkpoint_height, tip_height
    FROM indexer_state;
  IF state_rows <> 1 THEN
    RAISE EXCEPTION 'validation failed: indexer_state row count is %', state_rows;
  END IF;
  IF checkpoint_height IS NULL THEN
    RAISE EXCEPTION 'validation failed: indexer_state checkpoint is null';
  END IF;
  IF tip_height IS NOT NULL AND checkpoint_height > tip_height THEN
    RAISE EXCEPTION 'validation failed: checkpoint % is above finalized tip %', checkpoint_height, tip_height;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM blocks WHERE height = checkpoint_height) THEN
    RAISE EXCEPTION 'validation failed: checkpoint block % is missing', checkpoint_height;
  END IF;
  IF EXISTS (SELECT 1 FROM transactions t LEFT JOIN blocks b ON b.height = t.block_height WHERE b.height IS NULL) THEN
    RAISE EXCEPTION 'validation failed: transaction without block';
  END IF;
  IF EXISTS (SELECT 1 FROM validator_signatures s LEFT JOIN validator_set_members m ON m.height = s.height AND m.signing_address = s.signing_address WHERE m.height IS NULL) THEN
    RAISE EXCEPTION 'validation failed: signature without validator-set member';
  END IF;
END
$$;
SELECT
  (SELECT count(*) FROM blocks) AS blocks,
  (SELECT count(*) FROM transactions) AS transactions,
  (SELECT count(*) FROM validator_signatures) AS signatures;
SQL
```

An exact eight-table restore is a valid rollback point captured before the
Valopers migration. An exact ten-table restore is a valid backup captured after
the migration. A partial catalog, including either possible nine-table state,
is invalid, as is a catalog with missing legacy tables or unexpected tables.
The structural data checks following catalog validation run for both supported
schema versions.



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

## Read-only API deployment

The API is a host Python process supervised by systemd and logged by journald. It reads PostgreSQL only; it does not call Gno RPC. Its credentials must be separate from the PostgreSQL owner/admin and indexer roles: never reuse the indexer role or its `DATABASE_URL`. This procedure makes no schema changes.

### Create and verify the API database role

Open an interactive administrator session without putting a password in shell history (the exact container-side administrator role comes from the production PostgreSQL configuration):

```bash
docker compose -f deploy/postgres/compose.yml \
  --env-file /etc/utsa-gno-explorer/postgres.env \
  exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

At the `psql` prompt, run:

```sql
CREATE ROLE utsa_gno_api LOGIN;
\password utsa_gno_api

ALTER ROLE utsa_gno_api
  SET default_transaction_read_only = on;
ALTER ROLE utsa_gno_api
  SET statement_timeout = '5s';
ALTER ROLE utsa_gno_api
  SET idle_in_transaction_session_timeout = '10s';

GRANT CONNECT
  ON DATABASE utsa_gno_explorer
  TO utsa_gno_api;
GRANT USAGE
  ON SCHEMA public
  TO utsa_gno_api;
GRANT SELECT
  ON ALL TABLES IN SCHEMA public
  TO utsa_gno_api;
```

Do not grant this role `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, ownership, superuser, createdb, createrole, replication, or bypassrls. `default_transaction_read_only` adds a database-level safety layer, but application SQL must still remain read-only. Future tables need an explicit `SELECT` grant unless deliberate, owner-specific default privileges are configured. No default privileges or other schema changes are part of this procedure.

After installing the real API environment file below, connect interactively as `utsa_gno_api` (allow `psql` to prompt for its password; do not put a password or URL in the command) and run:

```bash
psql -h 127.0.0.1 -U utsa_gno_api -d utsa_gno_explorer
```

```sql
SHOW default_transaction_read_only;
SHOW statement_timeout;
SELECT has_table_privilege(
  current_user,
  'public.blocks',
  'SELECT'
);
SELECT has_table_privilege(
  current_user,
  'public.blocks',
  'UPDATE'
);
```

Expect `default_transaction_read_only` to be `on`, `statement_timeout` to be `5s`, the `SELECT` check to be `true`, and the `UPDATE` check to be `false`.

### Install and operate the API service

First confirm the default port is free. No output means no listener was found:

```bash
ss -ltnp | grep ':18180'
```

Install the external environment and unit. Edit the real `DATABASE_URL` securely without printing it; keep the default bind on localhost. The environment file is readable by root and the service group only.

```bash
sudo chown -R root:utsa-gno \
  /opt/utsa-gno-explorer/.venv \
  /opt/utsa-gno-explorer/api \
  /opt/utsa-gno-explorer/scripts
sudo chmod -R u=rwX,g=rX,o= \
  /opt/utsa-gno-explorer/.venv \
  /opt/utsa-gno-explorer/api \
  /opt/utsa-gno-explorer/scripts
sudo install -o root -g utsa-gno -m 0640 \
  deploy/systemd/api.env.example /etc/utsa-gno-explorer/api.env
sudo editor /etc/utsa-gno-explorer/api.env
sudo install -o root -g root -m 0644 \
  deploy/systemd/utsa-gno-api.service /etc/systemd/system/utsa-gno-api.service
sudo systemd-analyze verify /etc/systemd/system/utsa-gno-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now utsa-gno-api.service
```

These ownership and mode commands keep `root` as the owner while giving the
`utsa-gno` group read and directory traversal access, including executable bits
already present. They grant `utsa-gno` no write access. A symbolic link mode such
as `lrwxrwxrwx` describes the link, not its target, and does not mean that the
target is group-writable.

Verify runtime access and confirm that no regular file or directory is
group-writable. The `find` checks do not follow symbolic links:

```bash
sudo -u utsa-gno test -r /opt/utsa-gno-explorer/api/app.py
sudo -u utsa-gno test -r /opt/utsa-gno-explorer/scripts/wait_for_postgres.py
sudo -u utsa-gno sh -c 'cd /opt/utsa-gno-explorer && .venv/bin/python -c "import api.app"'
sudo -u utsa-gno /opt/utsa-gno-explorer/.venv/bin/uvicorn --version
find -P /opt/utsa-gno-explorer/.venv /opt/utsa-gno-explorer/api /opt/utsa-gno-explorer/scripts \
  -type f -perm /g=w -print
find -P /opt/utsa-gno-explorer/.venv /opt/utsa-gno-explorer/api /opt/utsa-gno-explorer/scripts \
  -type d -perm /g=w -print
```

Both `find` commands must produce no output.

The default internal address is `127.0.0.1:18180`, sourced from `/etc/utsa-gno-explorer/api.env`. Keep `API_BIND_HOST=127.0.0.1`; a localhost-only listener needs no firewall opening. If the port changes, update the future reverse-proxy target at the same time. The unit grants no writable paths.

Inspect the process, journal, and listener:

```bash
systemctl status utsa-gno-api.service
journalctl -u utsa-gno-api.service -n 100 --no-pager
ss -ltnp | grep ':18180' | grep '127.0.0.1'
```

Run local smoke tests for every endpoint (replace example path values with known records where applicable):

```bash
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/health
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/network
curl --fail --silent --show-error \
  'http://127.0.0.1:18180/api/blocks?limit=2'
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/blocks/REPLACE_WITH_HEIGHT
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/validators
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/validators/REPLACE_WITH_ADDRESS
```

Lifecycle commands remain operator-controlled:

```bash
sudo systemctl stop utsa-gno-api.service
sudo systemctl start utsa-gno-api.service
sudo systemctl restart utsa-gno-api.service
sudo systemctl disable --now utsa-gno-api.service
```

### API-only update and rollback

For API-only changes, do not stop PostgreSQL or the indexer. Create an isolated Git worktree for PR validation, validate there, and merge only after validation. Then explicitly fast-forward the production checkout and restart only the API:

```bash
git worktree add /tmp/utsa-gno-api-validation origin/PR_BRANCH
# Validate the PR in the isolated worktree, then remove it according to operator policy.
sudo git -C /opt/utsa-gno-explorer fetch origin
sudo git -C /opt/utsa-gno-explorer switch main
sudo git -C /opt/utsa-gno-explorer merge --ff-only origin/main
# Run only when requirements.txt changed:
sudo /opt/utsa-gno-explorer/.venv/bin/python \
  -m pip install \
  -r /opt/utsa-gno-explorer/requirements.txt
# Normalize runtime permissions after Git and pip operations.
sudo chown -R root:utsa-gno \
  /opt/utsa-gno-explorer/.venv \
  /opt/utsa-gno-explorer/api \
  /opt/utsa-gno-explorer/scripts
sudo chmod -R u=rwX,g=rX,o= \
  /opt/utsa-gno-explorer/.venv \
  /opt/utsa-gno-explorer/api \
  /opt/utsa-gno-explorer/scripts
sudo systemctl restart utsa-gno-api.service
```

Repeat the local curl smoke tests after restart. Neither systemd nor the application performs Git operations, dependency installation, database initialization, migrations, restore, or deployment automatically.

#### Valopers schema and API access prerequisite

Use this ordered, fail-closed prerequisite when upgrading from
`v0.5.0-production-runtime`, or when any deployment does not already have the compatible
Valopers tables and API-role privilege. It detects and migrates the legacy eight-table schema
when required, while safely revalidating an already-compatible ten-table schema. No migration
is automatic.

The earlier
`GRANT SELECT ON ALL TABLES IN SCHEMA public` covered only tables that existed
when that statement ran. The explicit Valopers migration created
`valoper_profiles` later, so the API role does not inherit access to it. Future
tables likewise require operator review and explicit grants; do not configure an
automatic grant path.

1. Fetch and fast-forward the production checkout to the reviewed revision:

   ```bash
   sudo git -C /opt/utsa-gno-explorer fetch origin
   sudo git -C /opt/utsa-gno-explorer switch main
   sudo git -C /opt/utsa-gno-explorer merge --ff-only origin/main
   ```

2. Load the protected indexer environment, apply the existing migration when the exact
   legacy eight-table schema is detected, and validate the resulting ten-table schema before
   changing privileges. The migration command safely revalidates an already-compatible
   ten-table schema without applying DDL:

   ```bash
   sudo -u utsa-gno sh -c '
     set -a
     . /etc/utsa-gno-explorer/indexer.env
     set +a
     cd /opt/utsa-gno-explorer
     .venv/bin/python scripts/migrate_valopers_schema.py
     exec .venv/bin/python scripts/init_database.py
   '
   ```

3. Open the existing interactive PostgreSQL administrator session. No password or
   `DATABASE_URL` is placed on the command line:

   ```bash
   docker compose -f deploy/postgres/compose.yml \
     --env-file /etc/utsa-gno-explorer/postgres.env \
     exec postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

   Apply only the required read privilege:

   ```sql
   GRANT SELECT ON TABLE public.valoper_profiles TO utsa_gno_api;
   ```

4. In the same administrator session, verify the grant and absence of write
   privileges:

   ```sql
   DO $$
   BEGIN
     IF NOT has_table_privilege(
       'utsa_gno_api', 'public.valoper_profiles', 'SELECT'
     ) THEN
       RAISE EXCEPTION 'API role is missing SELECT on valoper_profiles';
     END IF;

     IF has_table_privilege(
       'utsa_gno_api', 'public.valoper_profiles', 'INSERT'
     ) OR has_table_privilege(
       'utsa_gno_api', 'public.valoper_profiles', 'UPDATE'
     ) OR has_table_privilege(
       'utsa_gno_api', 'public.valoper_profiles', 'DELETE'
     ) OR has_table_privilege(
       'utsa_gno_api', 'public.valoper_profiles', 'TRUNCATE'
     ) THEN
       RAISE EXCEPTION 'API role has unexpected write privileges';
     END IF;

     IF has_table_privilege(
       'utsa_gno_api', 'public.valopers_snapshot_state', 'SELECT'
     ) THEN
       RAISE EXCEPTION 'API role has unexpected snapshot-state access';
     END IF;
   END
   $$;
   ```

   A successful block returns `DO`; any failed condition raises an exception and
   `ON_ERROR_STOP` terminates the administrator session. Stop the deployment before
   restart if the block does not succeed. Do not grant access to
   `valopers_snapshot_state`, use `GRANT
   ALL`, change ownership, or add superuser or data-changing privileges. The API
   role remains read-only.

5. Restart only `utsa-gno-api.service` after the schema and privileges have been verified:

   ```bash
   sudo systemctl restart utsa-gno-api.service
   ```

6. Verify health:

   ```bash
   curl --fail --silent --show-error http://127.0.0.1:18180/api/health
   ```

7. Verify the active validator list:

   ```bash
   curl --fail --silent --show-error http://127.0.0.1:18180/api/validators
   ```

8. When at least one matched profile exists, request one known matched consensus
   signing address and verify its official profile fields and
   `valoper_source_height` are non-null:

   ```bash
   curl --fail --silent --show-error \
     http://127.0.0.1:18180/api/validators/MATCHED_SIGNING_ADDRESS
   ```

9. Inspect the list for an unmatched validator. If one currently exists, confirm
    it remains present, then request its detail and verify `moniker`,
    `operator_address`, `description`, `server_type`, and
    `valoper_source_height` are null:

    ```bash
    curl --fail --silent --show-error \
      http://127.0.0.1:18180/api/validators/UNMATCHED_SIGNING_ADDRESS
    ```

    If every active validator currently has a profile, report that fact and rely
    on the mandatory real PostgreSQL integration test for unmatched `LEFT JOIN`
    semantics. Never create or modify production rows to manufacture an unmatched
    smoke-test case.

#### API 0.8.0 metadata update

For an already-compatible deployment, including production at commit
`818cee6a5d0dc8c8817e8ef3fc03af97d35aeeab`, perform only this metadata update:

1. Edit the protected `/etc/utsa-gno-explorer/api.env` through the approved operator process.
2. Set `API_VERSION=0.8.0`.
3. Restart only `utsa-gno-api.service`:

   ```bash
   sudo systemctl restart utsa-gno-api.service
   ```

4. Verify that `/api/health` reports `api_version` as `0.8.0`:

   ```bash
   curl --fail --silent --show-error http://127.0.0.1:18180/api/health
   ```

This already-compatible path requires no database migration, indexer restart, or PostgreSQL
restart. Frontend deployment remains operator-controlled. Migration and API-role grant
commands belong only to the prerequisite procedure above.

For rollback, stop the API, check out or reset only to a previously verified commit according to the repository's existing operator policy, reinstall dependencies only if required, start only the API, and verify `/api/health` locally:

```bash
sudo systemctl stop utsa-gno-api.service
# Apply the operator-approved checkout/reset to a previously verified commit here.
# Reinstall requirements only when that verified commit requires it.
sudo systemctl start utsa-gno-api.service
curl --fail --silent --show-error \
  http://127.0.0.1:18180/api/health
```

There is no database rollback step for an API-only release because this deployment adds no schema changes.

## Nginx HTTPS reverse proxy

The Explorer uses an independent `exp.gno.utsa.tech` server block. The API continues to listen only on `127.0.0.1:18180`; Nginx exposes the read-only `/api/` prefix and serves the production React/Vite frontend from `/var/www/utsa-gno-explorer`. The Vite dev server is not used in production, port `4174` is only for temporary PR previews, and port `18180` remains the localhost-only API upstream. This procedure does not require stopping PostgreSQL, the indexer, the API service, or unrelated Nginx sites. Reload Nginx rather than restarting it so existing sites remain available.

### Certificate bootstrap

1. Confirm that every configured A and AAAA record for `exp.gno.utsa.tech` resolves to the production server. An AAAA record is optional and must only be configured if `exp2` is publicly reachable over IPv6:

   ```bash
   getent ahosts exp.gno.utsa.tech
   ```

2. Create the dedicated ACME webroot with root-owned permissions:

   ```bash
   sudo install -d -o root -g root -m 0755 /var/www/letsencrypt/.well-known/acme-challenge
   ```

3. Install the HTTP-only bootstrap configuration and enable it:

   ```bash
   sudo install -o root -g root -m 0644 deploy/nginx/exp.gno.utsa.tech.bootstrap.conf /etc/nginx/sites-available/exp.gno.utsa.tech.conf
   sudo ln -s /etc/nginx/sites-available/exp.gno.utsa.tech.conf /etc/nginx/sites-enabled/exp.gno.utsa.tech.conf
   ```

4. Validate the complete Nginx configuration before reloading it:

   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

5. Obtain the first certificate through the dedicated webroot. Certbot writes certificate material under `/etc/letsencrypt`; do not display or copy private-key contents. The deploy hook runs after successful certificate issuance and after each future successful renewal, validating the complete Nginx configuration before reloading it:

   ```bash
   sudo certbot certonly --webroot \
     -w /var/www/letsencrypt \
     -d exp.gno.utsa.tech \
     --deploy-hook 'nginx -t && systemctl reload nginx'
   ```

### Frontend release flow

Build the frontend in the repository, then publish only the static build output into the dedicated Nginx webroot. Do not serve production files directly from `/opt/utsa-gno-explorer`, do not proxy frontend requests to Vite, and do not expose the Vite preview port. The existing TLS certificate is reused; Certbot does not need to be run again for a normal frontend deployment.

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm use 20

cd /opt/utsa-gno-explorer/frontend
npm run build

cd /opt/utsa-gno-explorer
sudo ./scripts/deploy_frontend.sh
```

`scripts/deploy_frontend.sh` verifies that `frontend/dist/index.html` exists before changing `/var/www/utsa-gno-explorer`, synchronizes the built files with stale-file removal, normalizes root-owned static file permissions, validates Nginx with `nginx -t`, and reloads Nginx only after validation succeeds. It does not run `git pull`, `npm install`, Certbot, or any PostgreSQL, API, or indexer service command.

### Final HTTPS installation

1. Build and deploy the frontend static files with the release flow above.

2. Replace the bootstrap configuration with the tracked HTTPS configuration:

   ```bash
   sudo install -o root -g root -m 0644 deploy/nginx/exp.gno.utsa.tech.conf /etc/nginx/sites-available/exp.gno.utsa.tech.conf
   ```

3. Validate the complete Nginx configuration before reloading it:

   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```

4. Confirm that Uvicorn remains localhost-only and that UFW has no rule exposing its internal port:

   ```bash
   sudo ss -ltnp '( sport = :18180 )'
   sudo ufw status numbered
   ```

   The socket output must show `127.0.0.1:18180`, never a wildcard or public address. The UFW output must contain no rule allowing port `18180`; do not add one.

5. Run public HTTPS smoke tests. Replace the height and validator address placeholders with known public values:

   ```bash
   curl --fail --show-error https://exp.gno.utsa.tech/
   curl --fail --show-error https://exp.gno.utsa.tech/api/health
   curl --fail --show-error https://exp.gno.utsa.tech/api/network
   curl --fail --show-error 'https://exp.gno.utsa.tech/api/blocks?limit=2'
   curl --fail --show-error https://exp.gno.utsa.tech/api/blocks/REPLACE_WITH_HEIGHT
   curl --fail --show-error https://exp.gno.utsa.tech/api/validators
   curl --fail --show-error https://exp.gno.utsa.tech/api/validators/REPLACE_WITH_ADDRESS
   ```

6. Verify the public boundary, read-only policy, and SPA fallback:

   ```bash
   curl --output /dev/null --write-out '%{http_code}\n' --request POST https://exp.gno.utsa.tech/api/health
   curl --connect-timeout 5 --output /dev/null --show-error http://exp.gno.utsa.tech:18180/api/health
   curl --output /dev/null --write-out '%{http_code}\n' https://exp.gno.utsa.tech/__client_side_route_smoke_test__
   ```

   The POST must be rejected, direct public access to port `18180` must be unavailable, and the client-side route request must return the SPA HTML rather than an Nginx `404`. `OPTIONS` requests are forwarded to FastAPI; Nginx does not synthesize CORS responses.

## Upgrade procedure

1. `sudo systemctl stop utsa-gno-indexer.service`.
2. `systemctl is-active utsa-gno-indexer.service` and confirm it is inactive.
3. Create a backup with `python scripts/backup_database.py --backup-dir /var/backups/utsa-gno-explorer` and validate it with the isolated validation-restore procedure above.
4. Save the current commit or tag with `git rev-parse HEAD`, then manually update or check out the new verified repository revision; systemd never runs `git pull`.
5. Rebuild the virtualenv: `.venv/bin/python -m pip install -r requirements.txt`.
6. Run automated tests: `python -m unittest discover -s tests -v`.
7. Load `DATABASE_URL` only from the protected external environment:

   ```bash
   set -a
   . /etc/utsa-gno-explorer/indexer.env
   set +a
   ```

8. For an existing database, explicitly apply or revalidate the additive migration: `python scripts/migrate_valopers_schema.py`. An exact legacy database is migrated; an already-migrated database is safely revalidated without DDL.
9. Only after migration succeeds, validate the complete current schema with `python scripts/init_database.py`.
10. Only after both commands succeed, run `sudo systemctl start utsa-gno-indexer.service`.
11. Check service status, journal output, PostgreSQL health, and checkpoint progression.

Fresh empty databases use only `python scripts/init_database.py`;
`scripts/migrate_valopers_schema.py` rejects an empty public schema. Existing
legacy production databases require migration followed by final-schema
validation. No migration is run automatically by systemd, Docker Compose,
container startup, the indexer, the API, or imports.

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

## Existing-database Valopers schema migration

This migration is a separate operator action from future snapshot persistence.
Fresh empty databases continue to use `python scripts/init_database.py`. Before
changing an existing production database, verify a backup, stop the indexer, and
run from the checked-out repository with `DATABASE_URL` supplied only by the
protected environment:

```console
python scripts/migrate_valopers_schema.py
python scripts/init_database.py
```

The first command accepts only the exact legacy eight-table schema or the exact
already-compatible ten-table schema. It transactionally adds
`valoper_profiles` and `valopers_snapshot_state`, performs complete catalog
validation before commit, and rolls back on any failure. It never alters or
deletes existing indexed rows and is safe to rerun after success. No container,
Compose entrypoint, systemd unit, indexer, API, or import applies it
automatically. Restart the indexer only after validation. Snapshot persistence remains a manual operator action. The API and frontend read the
persisted profiles; no automatic refresh is performed.

### Ordered RPC failover safety

Configure `GNO_RPC_URLS` in preference order. Each complete probe cycle synchronizes enabled endpoints for the configured chain, and the indexer uses the first endpoint that passes status, lag, trusted checkpoint-anchor, and parent-continuity checks. Removed same-chain URLs are disabled and deselected. The active endpoint proves its checkpoint only once per activation. If a request fails mid-batch, it is persisted unhealthy and excluded for the rest of the cycle; the next candidate proves the latest checkpoint once and retries the same height without global backoff. Endpoint selection is persisted only on initial activation or a real switch; backoff begins only when every candidate is exhausted. A single configured RPC follows the same retry behavior and never advances the checkpoint while unavailable or unable to prove continuity. Keep separate networks in separate database/runtime instances: `chain_id` equality alone is not cryptographic fork protection.
