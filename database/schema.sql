-- PostgreSQL schema for the UTSA Gno.land explorer design checkpoint.
-- This file is intentionally limited to tables required by the first explorer version.

CREATE TABLE blocks (
    height BIGINT PRIMARY KEY,
    block_hash_base64 TEXT NOT NULL,
    block_hash_hex TEXT NOT NULL,
    time_utc TIMESTAMPTZ NOT NULL,
    proposer_address TEXT,
    tx_count INTEGER NOT NULL CHECK (tx_count >= 0),
    raw_block_response JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT blocks_block_hash_base64_unique UNIQUE (block_hash_base64),
    CONSTRAINT blocks_block_hash_hex_unique UNIQUE (block_hash_hex),
    CONSTRAINT blocks_block_hash_hex_uppercase CHECK (block_hash_hex = upper(block_hash_hex))
);

COMMENT ON TABLE blocks IS 'One row per block height. Height is the natural key and prevents duplicate block ingestion.';
COMMENT ON COLUMN blocks.block_hash_base64 IS 'Original TM2 RPC block hash encoding retained for source fidelity.';
COMMENT ON COLUMN blocks.block_hash_hex IS 'Uppercase hex hash normalized from decoded block_hash_base64 for explorer search and display.';
COMMENT ON COLUMN blocks.time_utc IS 'Network block timestamp stored as TIMESTAMPTZ and displayed in UTC.';
COMMENT ON COLUMN blocks.raw_block_response IS 'Optional short-retention RPC JSON for parser auditing; not used for primary explorer queries.';

-- Latest block pages scan by descending height; PostgreSQL can scan this index backward/forward as needed.
CREATE INDEX blocks_height_desc_idx ON blocks (height DESC);
-- Block time can power future recent-block and time-range filters.
CREATE INDEX blocks_time_utc_idx ON blocks (time_utc DESC);

CREATE TABLE transactions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    block_height BIGINT NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
    tx_index INTEGER NOT NULL CHECK (tx_index >= 0),
    raw_base64 TEXT NOT NULL,
    raw_base64_length INTEGER NOT NULL CHECK (raw_base64_length >= 0),
    decoded_bytes BYTEA,
    decoded_byte_length INTEGER CHECK (decoded_byte_length IS NULL OR decoded_byte_length >= 0),
    decode_status TEXT NOT NULL CHECK (decode_status IN ('decoded', 'invalid_base64', 'not_attempted')),
    payload_summary JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transactions_block_position_unique UNIQUE (block_height, tx_index),
    CONSTRAINT transactions_decoded_length_requires_bytes CHECK (
        (decoded_bytes IS NULL AND decoded_byte_length IS NULL)
        OR (decoded_bytes IS NOT NULL AND decoded_byte_length IS NOT NULL)
    )
);

COMMENT ON TABLE transactions IS 'Ordered transactions within a block. The block position uniqueness makes reprocessing idempotent.';
COMMENT ON COLUMN transactions.raw_base64 IS 'Raw transaction string exactly as returned by result.block.data.txs.';
COMMENT ON COLUMN transactions.decoded_bytes IS 'Decoded bytes when base64 decoding succeeds; full Gno transaction parsing is deferred.';
COMMENT ON COLUMN transactions.payload_summary IS 'Limited JSONB for future decoded payload summaries, not raw unbounded application data.';

-- Block detail pages fetch transactions by block and position.
CREATE INDEX transactions_block_height_index_idx ON transactions (block_height, tx_index);

CREATE TABLE validators (
    signing_address TEXT PRIMARY KEY,
    public_key_type TEXT NOT NULL,
    public_key_value TEXT NOT NULL,
    first_seen_height BIGINT NOT NULL CHECK (first_seen_height >= 0),
    last_seen_height BIGINT NOT NULL CHECK (last_seen_height >= first_seen_height),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT validators_public_key_unique UNIQUE (public_key_type, public_key_value)
);

COMMENT ON TABLE validators IS 'Validator identity keyed by the signing address used to match validator sets and commit precommits.';
COMMENT ON COLUMN validators.public_key_type IS 'TM2 public key type, for example /tm.PubKeyEd25519.';
COMMENT ON COLUMN validators.public_key_value IS 'Public key value exactly as returned by RPC.';

CREATE TABLE validator_set_members (
    height BIGINT NOT NULL,
    signing_address TEXT NOT NULL REFERENCES validators(signing_address) ON DELETE RESTRICT,
    voting_power NUMERIC(78, 0) NOT NULL CHECK (voting_power >= 0),
    proposer_priority NUMERIC(78, 0),
    validator_index INTEGER CHECK (validator_index IS NULL OR validator_index >= 0),
    raw_validator JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (height, signing_address)
);

COMMENT ON TABLE validator_set_members IS 'Active validator set by finalized height. Voting power is height-specific to support validator-set changes.';
COMMENT ON COLUMN validator_set_members.height IS 'Finalized signing height from /validators?height=H-1, not necessarily the latest block metadata height H.';
COMMENT ON COLUMN validator_set_members.raw_validator IS 'Optional short-retention validator JSON for auditing RPC shape changes.';

-- Active validator page for a height and voting-power ordering.
CREATE INDEX validator_set_members_height_power_idx ON validator_set_members (height, voting_power DESC, signing_address);
-- Validator detail pages need membership history by validator.
CREATE INDEX validator_set_members_signing_height_idx ON validator_set_members (signing_address, height DESC);

CREATE TABLE validator_signatures (
    height BIGINT NOT NULL,
    signing_address TEXT NOT NULL REFERENCES validators(signing_address) ON DELETE RESTRICT,
    signed BOOLEAN NOT NULL,
    precommit_is_null BOOLEAN NOT NULL DEFAULT false,
    block_id_flag TEXT,
    signature_base64 TEXT,
    raw_precommit JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (height, signing_address),
    FOREIGN KEY (height, signing_address)
        REFERENCES validator_set_members(height, signing_address)
        ON DELETE CASCADE,
    CONSTRAINT validator_signatures_null_precommit_not_signed CHECK (NOT precommit_is_null OR signed = false),
    CONSTRAINT validator_signatures_signed_has_evidence CHECK (signed = false OR signature_base64 IS NOT NULL OR block_id_flag IS NOT NULL)
);

COMMENT ON TABLE validator_signatures IS 'One signed/missed result per validator per finalized height. Primary key makes reprocessing idempotent.';
COMMENT ON COLUMN validator_signatures.precommit_is_null IS 'True when the commit precommit entry was null; this is treated as a missed height.';
COMMENT ON COLUMN validator_signatures.raw_precommit IS 'Optional short-retention precommit JSON for parser auditing.';

-- Uptime over latest 1,000 finalized heights and recent 100 signature squares filter by validator and height.
CREATE INDEX validator_signatures_signing_height_signed_idx ON validator_signatures (signing_address, height DESC, signed);
-- Recent network-wide misses group by height and filter missed signatures.
CREATE INDEX validator_signatures_height_signed_idx ON validator_signatures (height DESC, signed, signing_address);

CREATE TABLE rpc_endpoints (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url TEXT NOT NULL,
    chain_id TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    is_selected BOOLEAN NOT NULL DEFAULT false,
    last_checked_at TIMESTAMPTZ,
    last_selected_at TIMESTAMPTZ,
    latest_observed_height BIGINT CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0),
    observed_lag BIGINT CHECK (observed_lag IS NULL OR observed_lag >= 0),
    catching_up BOOLEAN,
    healthy BOOLEAN,
    last_error TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT rpc_endpoints_url_unique UNIQUE (url),
    CONSTRAINT rpc_endpoints_no_secret_url CHECK (url !~* '(password|token|apikey|api_key|secret)=')
);

COMMENT ON TABLE rpc_endpoints IS 'Non-secret RPC endpoint health and selection metadata. Credentials must not be stored here.';
COMMENT ON CONSTRAINT rpc_endpoints_no_secret_url ON rpc_endpoints IS 'Best-effort guard against committing common credential query parameters.';

-- Endpoint selection checks enabled healthy endpoints by chain and observed freshness.
CREATE INDEX rpc_endpoints_health_idx ON rpc_endpoints (chain_id, is_enabled, healthy, latest_observed_height DESC);
-- Only one selected endpoint is allowed per chain at a time.
CREATE UNIQUE INDEX rpc_endpoints_one_selected_per_chain_idx ON rpc_endpoints (chain_id) WHERE is_selected;

CREATE TABLE indexer_state (
    state_key TEXT PRIMARY KEY,
    chain_id TEXT NOT NULL,
    last_finalized_height BIGINT NOT NULL CHECK (last_finalized_height >= 0),
    last_latest_block_height BIGINT CHECK (last_latest_block_height IS NULL OR last_latest_block_height >= last_finalized_height),
    selected_rpc_endpoint_id BIGINT REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT indexer_state_default_key CHECK (state_key = 'default')
);

COMMENT ON TABLE indexer_state IS 'Singleton checkpoint for resumable indexing. Advance only after a finalized height transaction succeeds.';
COMMENT ON COLUMN indexer_state.last_finalized_height IS 'Most recent fully processed signing height. Do not update after partial processing.';
COMMENT ON COLUMN indexer_state.last_latest_block_height IS 'Latest block metadata height H observed while processing finalized height H-1.';

-- The default row is expected to be created by deployment or migration tooling before indexing starts.
