# Backup and restore

Choose the recovery objective before acting. Exact commands, archive validation, clean-room
restore, and security controls are in [Backup and recovery](backup-and-recovery.md) and the
[production reference](production-deployment.md).

## Scenario A — new server without old history

No PostgreSQL backup is required. Recreate external configuration and secrets, create an
entirely empty database, choose a fixed recent finalized `INDEXER_START_HEIGHT`, initialize
the schema, and start sequential indexing there. Do not restore old rows.

The new Explorer will have no earlier blocks, transactions, account transaction history,
validator sets, signing records, or derived execution history. Those records cannot appear
unless their heights are indexed or a compatible backup is restored. Current Valopers,
Governance, and observed network-distribution snapshots are collected separately after
their services run.

## Scenario B — exact migration or recovery with history

1. Transfer a verified `pg_dump` custom-format archive through a secure channel.
2. Stop all writers, including the indexer and Governance updater.
3. Prepare a clean, compatible PostgreSQL 16 instance and roles; do not restore over an
   unverified live database.
4. Follow the repository-supported validation/restore procedure in the detailed reference,
   including `pg_restore --list` and clean-room validation.
5. Validate the restored schema with the real protected environment:
   `sudo -u utsa-gno sh -c 'set -a; . /etc/utsa-gno-explorer/indexer.env; . /etc/utsa-gno-explorer/rpc.env; set +a; cd /opt/utsa-gno-explorer && exec .venv/bin/python scripts/init_database.py'`.
6. Compare `indexer_state.last_finalized_height` with the highest stored block and matching
   block identity at the RPC. Resolve every discrepancy before writing.
7. Start the API and read-only/one-shot components and verify health.
8. Start the indexer only after validation, confirm checkpoint progress, then verify the
   public frontend.

## Data outside Git

Recreate or transfer securely:

- `/etc/utsa-gno-explorer/*.env`;
- `/etc/utsa-gno-explorer/postgres-password`;
- a PostgreSQL backup when history is required;
- operator-owned Nginx configuration;
- TLS certificates or the ability to issue new certificates;
- DNS records;
- every private credential-bearing RPC URL.

Do not place any of these secrets in the repository, command transcripts, or release notes.
