# Database schema

The canonical schema is `database/schema.sql`. It is PostgreSQL-compatible SQL and uses explicit primary keys, foreign keys, uniqueness constraints, and query-driven indexes.

## Tables

### `blocks`

Stores one row per block height. It supports latest block lists, block detail pages, hash search, proposer filtering, and transaction counts.

### `transactions`

Stores transactions ordered within a block. It preserves raw base64, decoded bytes when possible, and decode status. A unique `(block_height, tx_index)` constraint prevents duplicate transaction rows for the same block position.

### `validators`

Stores validator identity by signing address, public key type, public key value, and first/last seen heights. The signing address is used to match validator-set entries and commit precommits.

### `validator_set_members`

Stores the active validator set for each finalized height. Voting power and proposer priority are height-specific because validator sets can change over time.

### `validator_signatures`

Stores one row per `(height, signing_address)` showing whether the validator signed or missed that finalized height. `NULL` precommits are recorded as `signed = false` with `precommit_is_null = true`.

### `rpc_endpoints`

Stores non-secret endpoint URLs, status, latest observed height, lag, selected state, and last error text. It supports endpoint health pages and RPC switching decisions.

### `indexer_state`

Stores a named singleton checkpoint. The first version uses `state_key = 'default'`. The indexer advances `last_finalized_height` only after successfully committing all rows for that finalized height.

## Critical constraints

- `blocks.height` is the primary key and prevents duplicate block ingestion.
- `transactions` has both an internal primary key and a unique `(block_height, tx_index)` constraint.
- `validators.signing_address` is unique and is referenced by validator-set and signature rows.
- `validator_set_members` has primary key `(height, signing_address)`.
- `validator_signatures` has primary key `(height, signing_address)`.
- Foreign keys from transactions, validator-set members, signatures, and indexer state preserve relational consistency.

## Query support

### Latest blocks

Use `blocks` ordered by descending height:

```sql
SELECT height, block_hash_hex, time_utc, proposer_address, tx_count
FROM blocks
ORDER BY height DESC
LIMIT 50;
```

### Block details

Fetch one block and ordered transactions:

```sql
SELECT * FROM blocks WHERE height = $1;
SELECT * FROM transactions WHERE block_height = $1 ORDER BY tx_index;
```

### Active validators by height

```sql
SELECT v.signing_address, v.public_key_type, v.public_key_value,
       m.voting_power, m.proposer_priority
FROM validator_set_members m
JOIN validators v USING (signing_address)
WHERE m.height = $1
ORDER BY m.voting_power DESC, v.signing_address;
```

### Uptime over the latest 1,000 finalized heights

Find the latest finalized height from `indexer_state`, then aggregate signatures in that range:

```sql
WITH bounds AS (
  SELECT last_finalized_height AS end_height,
         GREATEST(last_finalized_height - 999, 0) AS start_height
  FROM indexer_state
  WHERE state_key = 'default'
)
SELECT signing_address,
       count(*) AS observed_heights,
       count(*) FILTER (WHERE signed) AS signed_heights,
       count(*) FILTER (WHERE NOT signed) AS missed_heights,
       count(*) FILTER (WHERE signed)::numeric / NULLIF(count(*), 0) AS uptime_ratio
FROM validator_signatures, bounds
WHERE height BETWEEN bounds.start_height AND bounds.end_height
GROUP BY signing_address
ORDER BY uptime_ratio DESC NULLS LAST, signing_address;
```

### Recent signed/missed squares over the latest 100 finalized heights

```sql
WITH bounds AS (
  SELECT last_finalized_height AS end_height,
         GREATEST(last_finalized_height - 99, 0) AS start_height
  FROM indexer_state
  WHERE state_key = 'default'
)
SELECT height, signing_address, signed, precommit_is_null
FROM validator_signatures, bounds
WHERE height BETWEEN bounds.start_height AND bounds.end_height
ORDER BY height DESC, signing_address;
```

### Recent network-wide misses

```sql
SELECT height,
       count(*) FILTER (WHERE NOT signed) AS missed_validators,
       count(*) AS validators_observed
FROM validator_signatures
WHERE height > $1
GROUP BY height
HAVING count(*) FILTER (WHERE NOT signed) > 0
ORDER BY height DESC;
```

## Idempotent reprocessing

The indexer should use `INSERT ... ON CONFLICT ... DO UPDATE` for rows that may be reprocessed from the same RPC data. The primary keys and unique constraints ensure the second pass updates the same logical records instead of adding duplicates. `indexer_state.last_finalized_height` must be updated only in the same transaction that completed the height.
