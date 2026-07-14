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
