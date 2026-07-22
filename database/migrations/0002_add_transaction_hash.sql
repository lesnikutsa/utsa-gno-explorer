-- Add canonical Tendermint2 transaction hashes. The indexer must be stopped.
-- Backfill and validation are performed transactionally by
-- scripts/migrate_transaction_hashes.py before the unique index is created.
ALTER TABLE transactions ADD COLUMN tx_hash_hex TEXT;

COMMENT ON COLUMN transactions.tx_hash_hex IS
    'SHA-256 of the exact decoded Tendermint2 transaction bytes, in the Explorer canonical uppercase hexadecimal display/search form.';

ALTER TABLE transactions ADD CONSTRAINT transactions_tx_hash_hex_format
    CHECK (tx_hash_hex IS NULL OR tx_hash_hex ~ '^[0-9A-F]{64}$') NOT VALID;
ALTER TABLE transactions ADD CONSTRAINT transactions_tx_hash_consistent
    CHECK (
        (decode_status = 'decoded' AND tx_hash_hex IS NOT NULL)
        OR (decode_status IN ('invalid_base64', 'not_attempted') AND tx_hash_hex IS NULL)
    ) NOT VALID;
