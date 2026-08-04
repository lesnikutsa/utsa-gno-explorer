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
5. Run `python scripts/refresh_realm_catalog.py` to create the initial fixed-height catalog state.
6. Optionally run `python scripts/rebuild_realm_activity.py --from-height HEIGHT` with an explicit verified local range.
7. Restart the indexer.
8. Restart the API.
9. Smoke-test `GET /api/realms`.
10. Leave the frontend unchanged in this release.

The initial commands are foreground, one-shot operations with dedicated transaction
advisory locks. After rollout, `utsa-gno-realm-catalog-refresh.timer` invokes the same
entry point every three hours at 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00,
and 21:00 UTC. The refresh must run before the first rebuild because the rebuild
requires an existing catalog state. Decoded-history statistics are limited to a
verified complete local block range and valid bounded summaries. The qpaths command
changes visibility atomically and never deletes historical rows.

Use `sudo systemctl start utsa-gno-realm-catalog-refresh.service` for an operator
refresh. Inspect it with
`journalctl -u utsa-gno-realm-catalog-refresh.service -n 50 --no-pager`, then verify
the API's `catalog_observed_height`, Realm/package counts, and `rpc_visible` count.
Equal-height runs report `status=unchanged`; older snapshots report
`status=stale_ignored`. Invalid qpaths data rolls back without publishing a partial
catalog. Catalog refreshes leave Realm activity counters and coverage unchanged,
do not stop the indexer, restart the API, or modify the application registry.

### One-time Realm activity coverage alignment

An installation that indexed live blocks with the legacy indexer can have a
multi-height lag. Metadata-only repair is unsafe because a previous bounded rebuild
may have intentionally excluded otherwise present blocks. Use this sequence:

1. Stop `utsa-gno-indexer.service` before deploying the new code.
2. Deploy the new code and run `python scripts/check_realm_activity_coverage.py`.
3. If it reports `status=rebuild_required`, record the checkpoint and run
   `python scripts/rebuild_realm_activity.py --from-height <activity_from_height> --through-height <indexer_checkpoint>`.
4. Repeat the check and require `status=aligned`.
5. Start `utsa-gno-indexer.service`.
6. Confirm each subsequent block advances `activity_through_height` by exactly one.

The check command is read-only. Do not start the new indexer with a multi-height
lag: exact-next advancement deliberately fails closed until the full rebuild has
atomically recalculated counters and range metadata. The API may remain available
during the rebuild because readers continue to see the previously committed state
until the rebuild transaction commits. Block continuity is a rebuild precondition,
not evidence that counters for those blocks already exist.
