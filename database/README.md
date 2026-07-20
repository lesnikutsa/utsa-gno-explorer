# Database

`schema.sql` contains the PostgreSQL schema for the first UTSA Gno.land explorer design checkpoint.

## Scope

The schema supports:

- latest blocks and block detail pages;
- transactions attached to blocks;
- validator identity and active validator sets by finalized height;
- validator signing and missed-block history;
- uptime over the latest 1,000 finalized heights;
- recent signed/missed squares over the latest 100 finalized heights;
- recent network-wide misses;
- current RPC endpoint health plus append-only check and switching history;
- resumable indexing through `indexer_state`.

It does not create a PostgreSQL server, Docker Compose stack, migration framework, backend API, frontend, or continuous indexer.

## Validation

Validate the schema against a real PostgreSQL parser before merge. A temporary PostgreSQL container is sufficient and should not leave persistent services or data behind. If local PostgreSQL tools are available, use:

```bash
createdb utsa_gno_schema_check
psql --dbname=utsa_gno_schema_check --file=database/schema.sql --set=ON_ERROR_STOP=1

dropdb utsa_gno_schema_check
```

If Docker is available, an equivalent temporary `postgres` container can be used, then removed after `psql --set=ON_ERROR_STOP=1 --file=database/schema.sql` succeeds.

## Idempotency

Future indexer writes should use PostgreSQL transactions and `INSERT ... ON CONFLICT ... DO UPDATE`. One target finalized height `S` is complete only after block, transaction, validator-set, signature, endpoint, endpoint-check history, and checkpoint writes all commit successfully. The future indexer must resume from `last_finalized_height + 1` and never skip intermediate finalized heights.

## Secrets

Do not store secrets in this schema or repository. RPC credentials, if ever needed, must come from runtime secret management and must not be written to `rpc_endpoints`.

## Temporary bounded-indexer validation

For local or exp2 validation, create a temporary PostgreSQL 16 database, apply `database/schema.sql`, and run only a small finalized range. Do not publish the database port unless the operator explicitly needs remote access.

Useful checks after a run:

```sql
SELECT last_finalized_height, finalized_tip_height FROM indexer_state WHERE state_key = 'default';
SELECT height, block_hash_hex, tx_count FROM blocks ORDER BY height;
SELECT height, count(*) FROM validator_signatures GROUP BY height ORDER BY height;
```

Cleanup for a disposable validation database can drop and recreate the database, or truncate explorer tables in dependency order:

```sql
TRUNCATE valoper_profiles, valopers_snapshot_state, rpc_endpoint_checks, indexer_state, validator_signatures, validator_set_members, transactions, blocks, validators, rpc_endpoints RESTART IDENTITY CASCADE;
```

## Continuous indexer advisory lock

`scripts/run_indexer.py` uses a PostgreSQL advisory lock derived from the configured chain ID. The lock is held on a dedicated PostgreSQL session for the lifetime of the foreground process. A normal exit unlocks it, and a lost PostgreSQL connection releases it naturally.

Diagnostic query for active advisory locks:

```sql
SELECT pid, locktype, objid, granted
FROM pg_locks
WHERE locktype = 'advisory'
ORDER BY pid;
```

The lock is only a single-instance guard for the continuous foreground runner. It does not replace PostgreSQL backups, migrations, production deployment, or future process supervision.

## Production initialization

Production schema initialization is operator-controlled and is not run by the PostgreSQL container entrypoint or the systemd indexer service. After PostgreSQL is running and `/etc/utsa-gno-explorer/indexer.env` contains the real `DATABASE_URL`, apply the schema from the repository root:

```bash
set -a
. /etc/utsa-gno-explorer/indexer.env
set +a
python scripts/init_database.py
```

The initialization script applies `database/schema.sql` only to an empty database; when tables already exist, it performs explicit catalog compatibility validation and fails on missing tables, incompatible columns, constraints, foreign keys, or index definitions. The script does not drop tables, drop databases, or delete existing data. For the first empty database, configure `INDEXER_START_HEIGHT` in the external indexer environment before starting the continuous indexer. See [Production deployment](../docs/production-deployment.md) for backup, validation restore, upgrade, and rollback procedures.

## Valopers persistence schema

Fresh empty databases initialized with `python scripts/init_database.py` include
`valoper_profiles`, the current official registry contract, and
`valopers_snapshot_state`, metadata for its one complete snapshot (including an
empty registry). The application does not write a snapshot yet, and the API and
frontend do not use either table.

Existing production databases require the explicit, additive, transactional
operator action below. Back up production and stop the indexer first; restart it
only after this command and `python scripts/init_database.py` both validate the
schema:

```console
python scripts/migrate_valopers_schema.py
python scripts/init_database.py
```

The migration never runs from application startup, services, containers, or
Compose. It preserves all existing indexed rows, rolls back on SQL or exact
catalog-validation failure, and may be rerun safely after success. It creates no
snapshot row or profile data.
