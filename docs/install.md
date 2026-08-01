# Fresh production installation

This guide installs the Explorer on a clean, supported Ubuntu server. Commands assume an
operator with `sudo`; review every command before running it. For security, migrations,
failover, and recovery detail, see the [production reference](production-deployment.md).

## 1. Install runtimes and tools

Install Git, Python 3 with `venv`, Go, Docker Engine with the Compose plugin, Nginx,
`rsync`, and PostgreSQL client tools from supported Ubuntu/vendor repositories. Install
Node.js **22** and npm. The database image is pinned by the repository to PostgreSQL 16.
Verify with `python3 --version`, `go version`, `node --version`, `docker compose version`,
and `nginx -v`.

## 2. Create the identity and checkout

```bash
sudo groupadd --system utsa-gno
sudo useradd --system --gid utsa-gno --home-dir /nonexistent --shell /usr/sbin/nologin utsa-gno
sudo git clone https://github.com/lesnikutsa/utsa-gno-explorer.git /opt/utsa-gno-explorer
cd /opt/utsa-gno-explorer
sudo git checkout <RELEASE_COMMIT>
sudo chown -R root:root /opt/utsa-gno-explorer
```

The service account must be able to read, but not write, the checkout.

## 3. Build dependencies

```bash
sudo python3 -m venv /opt/utsa-gno-explorer/.venv
sudo /opt/utsa-gno-explorer/.venv/bin/pip install -r requirements.txt
sudo install -d -o root -g root -m 0755 /opt/utsa-gno-explorer/bin
cd tools/gno-tx-decoder
go test ./...
go build -o /tmp/gno-tx-decoder .
sudo install -o root -g root -m 0755 /tmp/gno-tx-decoder /opt/utsa-gno-explorer/bin/gno-tx-decoder
sudo env "PATH=$PATH" npm --prefix /opt/utsa-gno-explorer/frontend ci
sudo env "PATH=$PATH" npm --prefix /opt/utsa-gno-explorer/frontend run build
cd /opt/utsa-gno-explorer
```

The virtual environment, dependency tree, and frontend output are written as root. Passing
the already verified `PATH` explicitly keeps the Node.js 22 toolchain available through
`sudo`; it does not make the checkout writable by the login user or `utsa-gno`.

## 4. Create protected storage and external configuration

```bash
sudo install -d -o root -g utsa-gno -m 0750 /etc/utsa-gno-explorer
sudo install -d -o root -g root -m 0755 /var/lib/utsa-gno-explorer
sudo install -d -o 999 -g 999 -m 0700 /var/lib/utsa-gno-explorer/postgres
sudo install -d -o root -g root -m 0700 /var/backups/utsa-gno-explorer
sudo install -o root -g root -m 0600 deploy/postgres/postgres.env.example /etc/utsa-gno-explorer/postgres.env
sudo install -o root -g root -m 0600 /dev/null /etc/utsa-gno-explorer/postgres-password
sudo install -o root -g utsa-gno -m 0640 deploy/systemd/rpc.env.example /etc/utsa-gno-explorer/rpc.env
sudo install -o root -g utsa-gno -m 0640 deploy/systemd/indexer.env.example /etc/utsa-gno-explorer/indexer.env
sudo install -o root -g utsa-gno -m 0640 deploy/systemd/api.env.example /etc/utsa-gno-explorer/api.env
```

Write a strong placeholder-replacing password, without a trailing newline, to
`postgres-password`. Edit the three `.env` files securely. Keep `GNO_CHAIN_ID=topaz-1` in
`rpc.env` and replace example RPC URLs with approved endpoints. `indexer.env` uses the
writer role `utsa_gno_indexer`; `api.env` uses the separately created read-only
`utsa_gno_api` role. Replace every password placeholder with URL-safe values. Never print
or commit these values and do not add a shared raw `DATABASE_URL` file.

`/etc/utsa-gno-explorer/network-distribution.env` is optional because its unit loads it
with a leading `-`. When overrides are needed, create it as `root:utsa-gno`, mode `0640`;
use only variables documented in the [production reference](production-deployment.md).

## 5. Choose exactly one bootstrap mode

**Mode A — full history:** use an entirely empty database and set
`INDEXER_START_HEIGHT=1`. This is required when complete Topaz history is wanted.

**Mode B — fresh current-state deployment:** use an entirely empty database and do not
restore a backup. Query healthy RPCs, choose a recent finalized height (for example, the
current RPC height minus about 100), and set that fixed value as `INDEXER_START_HEIGHT`
before initialization. Blocks, transactions, account history, validator sets, and signing
history before it will not exist locally. Future ingestion remains sequential from the
chosen height; missing history cannot appear without indexing or restoring it. Current
Valopers, Governance, and observed network-distribution snapshots are populated separately
by their respective services.

## 6. Start PostgreSQL and create the required roles

```bash
sudo docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env up -d postgres
sudo docker compose -f deploy/postgres/compose.yml --env-file /etc/utsa-gno-explorer/postgres.env ps
```

On the first container initialization, Compose creates the `POSTGRES_USER` from
`postgres.env` as the database owner/login and reads its password from
`/etc/utsa-gno-explorer/postgres-password`. Keep this value as `utsa_gno_indexer`; it is the
writer role named by `indexer.env`, owns `utsa_gno_explorer`, and therefore owns its schema,
tables, and sequences. Do not create a second writer model.

The separate API login is required on every fresh installation. Open the administrator
session without placing either password in shell history:

```bash
sudo docker compose -f deploy/postgres/compose.yml \
  --env-file /etc/utsa-gno-explorer/postgres.env \
  exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

At the `psql` prompt, create the login and enter the API password interactively:

```sql
CREATE ROLE utsa_gno_api LOGIN;
\password utsa_gno_api
ALTER ROLE utsa_gno_api SET default_transaction_read_only = on;
ALTER ROLE utsa_gno_api SET statement_timeout = '5s';
ALTER ROLE utsa_gno_api SET idle_in_transaction_session_timeout = '10s';
GRANT CONNECT ON DATABASE utsa_gno_explorer TO utsa_gno_api;
GRANT USAGE ON SCHEMA public TO utsa_gno_api;
```

Create the API role **before** schema initialization: `database/schema.sql` conditionally
grants access to late tables when `utsa_gno_api` already exists. Then initialize with the
real writer and RPC environments, without printing them:

```bash
sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/indexer.env; . /etc/utsa-gno-explorer/rpc.env; set +a; cd /opt/utsa-gno-explorer && exec .venv/bin/python scripts/init_database.py'
```

Return to the same administrator `psql` session after initialization and complete the
required read-only grants:

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA public TO utsa_gno_api;
```

The API does not read sequences, so no sequence privilege is required or granted. The
writer owns and may use the sequences; the API receives only database `CONNECT`, schema
`USAGE`, and table `SELECT`. Do not grant API ownership, `CREATE`, write privileges,
superuser, createdb, createrole, replication, or bypassrls. Ensure `api.env` uses the API
password entered with `\password`, and `indexer.env` uses the password file's writer value.

## 7. Install all systemd units

```bash
sudo install -o root -g root -m 0644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now utsa-gno-api.service utsa-gno-indexer.service utsa-gno-governance-updater.service
sudo systemctl enable --now utsa-gno-explorer-backup.timer utsa-gno-network-distribution.timer utsa-gno-valopers-refresh.timer
```

The inventory is: API, continuous indexer, continuous Governance updater; one-shot backup,
network-distribution, and Valopers refresh services; and a timer for each one-shot service.
There is no frontend service.

## 8. Publish the frontend and configure Nginx

```bash
sudo install -d -o root -g root -m 0755 /var/www/utsa-gno-explorer
sudo /opt/utsa-gno-explorer/scripts/deploy_frontend.sh
```

The script publishes `frontend/dist` to `/var/www/utsa-gno-explorer`, validates Nginx, and
reloads it. Review repository examples under `deploy/nginx/`; site activation, DNS, and TLS
certificate issuance remain operator-owned external configuration. Never commit private
keys. Confirm `sudo nginx -t` before exposing the site.

## 9. Verify services and reboot behavior

```bash
curl --fail http://127.0.0.1:18180/api/health
sudo systemctl status utsa-gno-api utsa-gno-indexer utsa-gno-governance-updater
sudo systemctl list-timers 'utsa-gno-*'
sudo journalctl -u utsa-gno-indexer.service -n 100 --no-pager
sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/rpc.env; set +a; cd /opt/utsa-gno-explorer && exec .venv/bin/python scripts/inspect_rpc.py'
sudo reboot
```

After reconnecting, repeat health, service, timer, Nginx, and public URL checks.

## Final checklist

- [ ] PostgreSQL healthy; schema initialized.
- [ ] Decoder executable exists at `/opt/utsa-gno-explorer/bin/gno-tx-decoder`.
- [ ] API healthy; indexer checkpoint progressing; Governance updater active.
- [ ] Backup, network-distribution, and Valopers timers active.
- [ ] Frontend published; Nginx configuration valid; public Explorer opens.
