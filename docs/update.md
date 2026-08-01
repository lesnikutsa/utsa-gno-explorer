# Production update

Updates are operator-controlled: `git pull`, migrations, deployments, and restarts are
**never automatic**. Read the release notes and the [production reference](production-deployment.md).

## Before every update

```bash
cd /opt/utsa-gno-explorer
sudo git status --short --branch
sudo git fetch --prune origin
sudo git rev-parse HEAD
sudo git show --no-patch --oneline <EXPECTED_COMMIT>
sudo git diff --check
sudo git pull --ff-only origin main
test "$(sudo git rev-parse HEAD)" = "<EXPECTED_COMMIT>"
```

Stop if the worktree is dirty or the commit differs. Back up external configuration through
the approved secret process; never copy secrets into Git.

## A. Frontend-only update

With Node.js 22, run:

```bash
sudo env "PATH=$PATH" npm --prefix frontend ci
node --test frontend/test/*.test.js
sudo env "PATH=$PATH" npm --prefix frontend run build
sudo scripts/deploy_frontend.sh
```

Do not restart the API, indexer, or PostgreSQL.

## B. API and/or gno-tx-decoder update

Run the relevant Python suite and Go tests, then replace the decoder atomically:

```bash
.venv/bin/python -m unittest discover -s tests -v
(cd tools/gno-tx-decoder && go test ./... && go build -o /tmp/gno-tx-decoder .)
sudo install -o root -g root -m 0755 /tmp/gno-tx-decoder /opt/utsa-gno-explorer/bin/gno-tx-decoder
sudo systemctl restart utsa-gno-api.service
curl --fail http://127.0.0.1:18180/api/health
```

For v1.0.0, an existing `/etc/utsa-gno-explorer/api.env` with an explicit version must be
manually changed to `API_VERSION=1.0.0`; restart **only** `utsa-gno-api.service` for that
metadata change. Rebuild/publish the frontend only when it changed. Do not restart the
indexer unless indexer files changed.

## C. Database, indexer, or schema update

1. Read that release's notes and named migration instructions.
2. Stop `utsa-gno-indexer.service` and other writers affected by the release.
3. Create a custom-format backup and verify it with `pg_restore --list`.
4. Run only the explicit migration documented for that release; never infer a migration.
5. Validate the complete schema with the protected production environment:
   `sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/indexer.env; . /etc/utsa-gno-explorer/rpc.env; set +a; cd /opt/utsa-gno-explorer && exec .venv/bin/python scripts/init_database.py'`.
6. Start the API/read-only services first and verify them, then start Governance and the
   indexer in the release-documented order.
7. Verify the `indexer_state` checkpoint and `/api/health`.

## Health and rollback

```bash
sudo systemctl status utsa-gno-api utsa-gno-indexer utsa-gno-governance-updater
sudo journalctl -u utsa-gno-api.service -u utsa-gno-indexer.service -n 100 --no-pager
sudo systemctl list-timers 'utsa-gno-*'
curl --fail http://127.0.0.1:18180/api/health
```

Rollback application files only to a known compatible commit. Never run older code against
an incompatible migrated schema. Preserve the failed state and verified backup; restore
only with the [backup and restore guide](restore.md). Recheck `git diff --check` after edits.
