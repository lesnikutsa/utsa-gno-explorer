BEGIN;

CREATE TABLE transaction_execution_results (
    block_height BIGINT NOT NULL,
    tx_index INTEGER NOT NULL,
    execution_status TEXT NOT NULL,
    gas_wanted NUMERIC(78, 0) NOT NULL,
    gas_used NUMERIC(78, 0) NOT NULL,
    error_text TEXT,
    log_text TEXT,
    info_text TEXT,
    data_base64 TEXT,
    events JSONB,
    raw_result JSONB,
    source_rpc_endpoint_id BIGINT REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (block_height, tx_index),
    FOREIGN KEY (block_height, tx_index)
        REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE,
    CONSTRAINT transaction_execution_results_status_check CHECK (execution_status IN ('success', 'failed')),
    CONSTRAINT transaction_execution_results_gas_wanted_check CHECK (gas_wanted >= 0),
    CONSTRAINT transaction_execution_results_gas_used_check CHECK (gas_used >= 0),
    CONSTRAINT transaction_execution_results_error_check CHECK (
        (execution_status = 'success' AND error_text IS NULL) OR
        (execution_status = 'failed' AND error_text IS NOT NULL AND btrim(error_text) <> '')
    )
);

COMMENT ON TABLE transaction_execution_results IS 'Canonical transaction execution results matched to transactions by block position.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
        GRANT SELECT ON transaction_execution_results TO utsa_gno_api;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_indexer') THEN
        GRANT SELECT, INSERT, UPDATE ON transaction_execution_results TO utsa_gno_indexer;
    END IF;
END $$;

COMMIT;
