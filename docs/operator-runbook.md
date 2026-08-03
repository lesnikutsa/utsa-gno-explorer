# Operator runbook

This is the current production operations hub. Start with [installation](install.md), use
[update](update.md) for changes and [restore](restore.md) for recovery. Exhaustive details
remain in the [production reference](production-deployment.md).

## Runtime layout

| Item | Location |
|---|---|
| Root-owned checkout | `/opt/utsa-gno-explorer` |
| Python environment | `/opt/utsa-gno-explorer/.venv` |
| External configuration | `/etc/utsa-gno-explorer` |
| PostgreSQL data | `/var/lib/utsa-gno-explorer/postgres` |
| Backups | `/var/backups/utsa-gno-explorer` |
| Frontend build / Nginx webroot | `frontend/dist` / `/var/www/utsa-gno-explorer` |

## Service and timer inventory

| Unit | Purpose |
|---|---|
| `utsa-gno-api.service` | Localhost read-only HTTP API. |
| `utsa-gno-indexer.service` | Sequential finalized block/transaction ingestion. |
| `utsa-gno-governance-updater.service` | Continuous Governance snapshot updater. |
| `utsa-gno-explorer-backup.service` / `.timer` | Verified PostgreSQL logical backup, daily. |
| `utsa-gno-network-distribution.service` / `.timer` | Observed peer sample, every 15 minutes. |
| `utsa-gno-valopers-refresh.service` / `.timer` | Official Valopers metadata refresh, hourly. |

The frontend has no systemd service; it is static content published by a script.

## Routine status and logs

```bash
sudo systemctl status utsa-gno-api utsa-gno-indexer utsa-gno-governance-updater
sudo systemctl list-timers 'utsa-gno-*'
sudo journalctl -u utsa-gno-indexer.service -n 100 --no-pager
sudo journalctl -u utsa-gno-api.service -u utsa-gno-governance-updater.service -n 100 --no-pager
curl --fail http://127.0.0.1:18180/api/health
```

Inspect the checkpoint without exposing credentials by running the documented PostgreSQL
Compose query for `indexer_state` in the [production reference](production-deployment.md).
Check that `last_finalized_height` advances and does not exceed the RPC finalized tip.
Inspect configured RPCs safely with:

```bash
sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/rpc.env; set +a; cd /opt/utsa-gno-explorer && exec .venv/bin/python scripts/inspect_rpc.py'
```

Do not print `rpc.env` because URLs may contain credentials.

## Frontend publication

```bash
cd /opt/utsa-gno-explorer
sudo env "PATH=$PATH" npm --prefix frontend ci
node --test frontend/test/*.test.js
sudo env "PATH=$PATH" npm --prefix frontend run build
sudo scripts/deploy_frontend.sh
```

The script syncs the build to `/var/www/utsa-gno-explorer`, runs `nginx -t`, and reloads
Nginx. It does not update Git or restart application/database services.

## Backup verification

```bash
sudo systemctl start utsa-gno-explorer-backup.service
sudo systemctl status utsa-gno-explorer-backup.service
sudo journalctl -u utsa-gno-explorer-backup.service -n 100 --no-pager
sudo find /var/backups/utsa-gno-explorer -maxdepth 1 -name '*.dump' -type f -printf '%TY-%Tm-%Td %TT %s %p\n'
```

The job validates archives before atomic publication. Periodically perform the isolated
restore validation from [Backup and recovery](backup-and-recovery.md); file presence alone
is not sufficient.

## Safe reboot checklist

1. Confirm the database is healthy, the checkpoint is current, and no migration/backup is
   active; record service and timer state.
2. Reboot through the operator-approved host procedure.
3. Confirm the PostgreSQL container health and the three long-running services.
4. Confirm timers are active and no oneshot failed during downtime.
5. Verify API health, checkpoint progress, RPC inspection, `nginx -t`, and the public site.
6. Review boot logs before declaring recovery complete.

## Realm catalog rollout and maintenance

Production rollout order is:

1. Back up and verify PostgreSQL.
2. Stop the indexer.
3. Update the repository.
4. Apply and verify migration `0008`.
5. Optionally run `python scripts/rebuild_realm_activity.py --from-height HEIGHT` with an explicit local range.
6. Run `python scripts/refresh_realm_catalog.py`.
7. Restart the indexer.
8. Restart the API.
9. Smoke-test `GET /api/realms`.
10. Leave the frontend unchanged in this release.

The commands are foreground, one-shot operations with dedicated transaction advisory locks; there is no automatic schedule. Decoded-history statistics are limited to available blocks and valid bounded summaries. The qpaths command changes visibility atomically and never deletes historical rows.
