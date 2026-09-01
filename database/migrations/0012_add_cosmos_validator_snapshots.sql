CREATE TABLE IF NOT EXISTS cosmos_validator_power_snapshots (
    network_id TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    operator_address TEXT NOT NULL,
    tokens NUMERIC(78, 0) NOT NULL CHECK (tokens >= 0),
    PRIMARY KEY (network_id, captured_at, operator_address)
);

CREATE INDEX IF NOT EXISTS cosmos_validator_power_snapshots_lookup
    ON cosmos_validator_power_snapshots (network_id, captured_at DESC);

