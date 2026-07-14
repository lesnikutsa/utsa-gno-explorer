# Backup and recovery

This document describes operational expectations for the future PostgreSQL database. It does not add infrastructure in this checkpoint.

## Backup strategy

- Use regular logical backups with `pg_dump` for small deployments.
- Use physical backups or managed PostgreSQL point-in-time recovery for production-size deployments.
- Store backups outside the application host.
- Encrypt backups at rest when they leave the trusted database environment.
- Do not include private RPC credentials in database backups because the schema does not store secrets.

## Suggested logical backup command

```bash
pg_dump --format=custom --file=utsa-gno-explorer.dump "$DATABASE_URL"
```

## Suggested restore command

```bash
createdb utsa_gno_explorer_restore
pg_restore --dbname=utsa_gno_explorer_restore --clean --if-exists utsa-gno-explorer.dump
```

## Recovery validation

After restore, validate at least:

```sql
SELECT max(height) FROM blocks;
SELECT last_finalized_height FROM indexer_state WHERE state_key = 'default';
SELECT count(*) FROM validator_signatures;
```

The restored `last_finalized_height` should be less than or equal to the highest signature height and should match the most recent fully processed finalized height.

## Rollback procedure

If a bad parser version writes incorrect data:

1. Stop the indexer.
2. Identify the first affected finalized height.
3. Restore from backup if broad corruption is suspected.
4. For narrow corruption, delete rows at and after the affected height in dependency order inside a transaction.
5. Reset `indexer_state.last_finalized_height` to the last verified good finalized height.
6. Restart indexing from the next height.

Example narrow rollback shape:

```sql
BEGIN;
DELETE FROM validator_signatures WHERE height >= $1;
DELETE FROM validator_set_members WHERE height >= $1;
DELETE FROM transactions WHERE block_height >= $2;
DELETE FROM blocks WHERE height >= $2;
UPDATE indexer_state
SET last_finalized_height = $1 - 1,
    updated_at = now()
WHERE state_key = 'default';
COMMIT;
```

Block, transaction, validator-set, and signature rows use the same target finalized height `S`, so rollback boundaries are consistent by height. Use `$1` as the first affected target height and reset the checkpoint to `$1 - 1`.

## Raw RPC response retention

Raw JSONB responses are retained only for short-term debugging. Operators should prune them after the configured retention window while keeping normalized rows.
