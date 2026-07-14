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
- RPC endpoint health and switching metadata;
- resumable indexing through `indexer_state`.

It does not create a PostgreSQL server, Docker Compose stack, migration framework, backend API, frontend, or continuous indexer.

## Validation

When a PostgreSQL client/server is available, validate the schema in a temporary database:

```bash
createdb utsa_gno_schema_check
psql --dbname=utsa_gno_schema_check --file=database/schema.sql --set=ON_ERROR_STOP=1

dropdb utsa_gno_schema_check
```

If only the client is available, use an external temporary PostgreSQL instance and do not leave persistent data behind.

## Idempotency

Future indexer writes should use PostgreSQL transactions and `INSERT ... ON CONFLICT ... DO UPDATE`. One finalized height is complete only after block, transaction, validator-set, signature, endpoint, and checkpoint writes all commit successfully.

## Secrets

Do not store secrets in this schema or repository. RPC credentials, if ever needed, must come from runtime secret management and must not be written to `rpc_endpoints`.
