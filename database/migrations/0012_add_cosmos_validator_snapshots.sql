BEGIN;

CREATE TABLE IF NOT EXISTS cosmos_validator_power_snapshots (
    network_id TEXT NOT NULL CONSTRAINT cosmos_validator_power_snapshots_network_check
        CHECK (network_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(network_id) <= 64),
    captured_at TIMESTAMPTZ NOT NULL,
    operator_address TEXT NOT NULL CONSTRAINT cosmos_validator_power_snapshots_operator_check
        CHECK (char_length(operator_address) BETWEEN 3 AND 90),
    tokens NUMERIC(78, 0) NOT NULL CONSTRAINT cosmos_validator_power_snapshots_tokens_check
        CHECK (tokens >= 0),
    PRIMARY KEY (network_id, captured_at, operator_address)
);

CREATE INDEX IF NOT EXISTS cosmos_validator_power_snapshots_lookup
    ON cosmos_validator_power_snapshots (network_id, captured_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
        GRANT SELECT, INSERT, DELETE ON cosmos_validator_power_snapshots TO utsa_gno_api;
    END IF;
END
$$;

COMMIT;
