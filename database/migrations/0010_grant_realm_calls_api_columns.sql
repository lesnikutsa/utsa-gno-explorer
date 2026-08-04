BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
        GRANT SELECT (height, time_utc)
        ON TABLE blocks
        TO utsa_gno_api;

        GRANT SELECT (block_height, tx_index, tx_hash_hex)
        ON TABLE transactions
        TO utsa_gno_api;

        GRANT SELECT (state_key, chain_id, last_finalized_height)
        ON TABLE indexer_state
        TO utsa_gno_api;
    END IF;
END
$$;

COMMIT;
