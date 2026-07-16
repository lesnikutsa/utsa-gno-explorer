# Production deployment

This guide packages the existing foreground continuous indexer without changing indexing semantics. Production uses PostgreSQL 16 in Docker Compose and runs the Python indexer on the host through systemd. Production deployment is operator-controlled: no container entrypoint or systemd unit runs `git pull`, schema updates, or destructive restore automatically.

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
5. Verify all eight tables.
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
  expected_tables text[] := ARRAY['blocks','indexer_state','rpc_endpoint_checks','rpc_endpoints','transactions','validator_set_members','validator_signatures','validators'];
  actual_tables text[];
  state_rows integer;
  checkpoint_height bigint;
  tip_height bigint;
BEGIN
  SELECT array_agg(table_name ORDER BY table_name)
    INTO actual_tables
    FROM information_schema.tables
   WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
  IF actual_tables IS DISTINCT FROM expected_tables THEN
    RAISE EXCEPTION 'validation failed: expected tables %, got %', expected_tables, actual_tables;
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
