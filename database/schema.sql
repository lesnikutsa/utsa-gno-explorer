-- PostgreSQL schema for the UTSA Gno.land explorer design checkpoint.
-- This file is intentionally limited to tables required by the first explorer version.

CREATE TABLE blocks (
    height BIGINT PRIMARY KEY,
    block_hash_base64 TEXT NOT NULL,
    block_hash_hex TEXT NOT NULL,
    time_utc TIMESTAMPTZ NOT NULL,
    proposer_address TEXT,
    tx_count INTEGER NOT NULL CONSTRAINT blocks_tx_count_check CHECK (tx_count >= 0),
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

-- Latest block pages use the primary-key B-tree on height, which PostgreSQL can scan backward.
-- Block time can power future recent-block and time-range filters.
CREATE INDEX blocks_time_utc_idx ON blocks (time_utc DESC);

CREATE TABLE transactions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    block_height BIGINT NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
    tx_index INTEGER NOT NULL CONSTRAINT transactions_tx_index_check CHECK (tx_index >= 0),
    raw_base64 TEXT NOT NULL,
    raw_base64_length INTEGER NOT NULL CONSTRAINT transactions_raw_base64_length_check CHECK (raw_base64_length >= 0),
    decoded_bytes BYTEA,
    decoded_byte_length INTEGER CONSTRAINT transactions_decoded_byte_length_check CHECK (decoded_byte_length IS NULL OR decoded_byte_length >= 0),
    decode_status TEXT NOT NULL CONSTRAINT transactions_decode_status_check CHECK (decode_status IN ('decoded', 'invalid_base64', 'not_attempted')),
    payload_summary JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transactions_block_position_unique UNIQUE (block_height, tx_index),
    CONSTRAINT transactions_raw_base64_length_matches CHECK (raw_base64_length = char_length(raw_base64)),
    CONSTRAINT transactions_decode_status_consistent CHECK (
        (decode_status = 'decoded' AND decoded_bytes IS NOT NULL AND decoded_byte_length = octet_length(decoded_bytes))
        OR (decode_status IN ('invalid_base64', 'not_attempted') AND decoded_bytes IS NULL AND decoded_byte_length IS NULL)
    )
);

COMMENT ON TABLE transactions IS 'Ordered transactions within a block. The block position uniqueness makes reprocessing idempotent.';
COMMENT ON COLUMN transactions.raw_base64 IS 'Raw transaction string exactly as returned by result.block.data.txs.';
COMMENT ON COLUMN transactions.decoded_bytes IS 'Decoded bytes when base64 decoding succeeds; full Gno transaction parsing is deferred.';
COMMENT ON COLUMN transactions.payload_summary IS 'Limited JSONB for future decoded payload summaries, not raw unbounded application data.';

-- Block detail pages use the unique constraint index on (block_height, tx_index).

CREATE TABLE validators (
    signing_address TEXT PRIMARY KEY,
    public_key_type TEXT NOT NULL,
    public_key_value TEXT NOT NULL,
    first_seen_height BIGINT NOT NULL CONSTRAINT validators_first_seen_height_check CHECK (first_seen_height >= 0),
    last_seen_height BIGINT NOT NULL CONSTRAINT validators_last_seen_height_check CHECK (last_seen_height >= first_seen_height),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT validators_public_key_unique UNIQUE (public_key_type, public_key_value)
);

COMMENT ON TABLE validators IS 'Validator identity keyed by the signing address used to match validator sets and commit precommits.';
COMMENT ON COLUMN validators.public_key_type IS 'TM2 public key type, for example /tm.PubKeyEd25519.';
COMMENT ON COLUMN validators.public_key_value IS 'Public key value exactly as returned by RPC.';

CREATE TABLE validator_set_members (
    height BIGINT NOT NULL REFERENCES blocks(height) ON DELETE CASCADE,
    signing_address TEXT NOT NULL REFERENCES validators(signing_address) ON DELETE RESTRICT,
    voting_power NUMERIC(78, 0) NOT NULL CONSTRAINT validator_set_members_voting_power_check CHECK (voting_power >= 0),
    proposer_priority NUMERIC(78, 0),
    validator_index INTEGER CONSTRAINT validator_set_members_validator_index_check CHECK (validator_index IS NULL OR validator_index >= 0),
    raw_validator JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (height, signing_address)
);

COMMENT ON TABLE validator_set_members IS 'Active validator set by finalized height. Voting power is height-specific to support validator-set changes.';
COMMENT ON COLUMN validator_set_members.height IS 'Target finalized height S from /validators?height=S; it references blocks.height for the same S.';
COMMENT ON COLUMN validator_set_members.raw_validator IS 'Optional short-retention validator JSON for auditing RPC shape changes.';

-- Active validator page for a height and voting-power ordering.
CREATE INDEX validator_set_members_height_power_idx ON validator_set_members (height, voting_power DESC, signing_address);
-- Validator detail pages need membership history by validator.
CREATE INDEX validator_set_members_signing_height_idx ON validator_set_members (signing_address, height DESC);

CREATE TABLE validator_signatures (
    height BIGINT NOT NULL,
    signing_address TEXT NOT NULL,
    vote_status TEXT NOT NULL CONSTRAINT validator_signatures_vote_status_check CHECK (vote_status IN ('commit', 'nil', 'absent', 'invalid')),
    signed BOOLEAN NOT NULL,
    vote_block_id_hash_base64 TEXT,
    vote_block_id_hash_hex TEXT,
    vote_block_id_parts_total INTEGER CONSTRAINT validator_signatures_vote_block_id_parts_total_check CHECK (vote_block_id_parts_total IS NULL OR vote_block_id_parts_total >= 0),
    vote_block_id_parts_hash_base64 TEXT,
    vote_block_id_parts_hash_hex TEXT,
    vote_block_id_is_zero BOOLEAN NOT NULL DEFAULT false,
    block_id_matches_commit BOOLEAN NOT NULL DEFAULT false,
    signature_base64 TEXT,
    raw_precommit JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (height, signing_address),
    FOREIGN KEY (height, signing_address)
        REFERENCES validator_set_members(height, signing_address)
        ON DELETE CASCADE,
    CONSTRAINT validator_signatures_signed_only_matching_commit CHECK (signed = (vote_status = 'commit' AND block_id_matches_commit)),
    CONSTRAINT validator_signatures_commit_vote_consistent CHECK (
        vote_status <> 'commit'
        OR (
            block_id_matches_commit
            AND NOT vote_block_id_is_zero
            AND vote_block_id_hash_base64 IS NOT NULL
            AND vote_block_id_hash_hex IS NOT NULL
            AND vote_block_id_parts_total IS NOT NULL
            AND vote_block_id_parts_hash_base64 IS NOT NULL
            AND vote_block_id_parts_hash_hex IS NOT NULL
            AND signature_base64 IS NOT NULL
        )
    ),
    CONSTRAINT validator_signatures_nil_vote_consistent CHECK (
        vote_status <> 'nil'
        OR (
            NOT signed
            AND vote_block_id_is_zero
            AND NOT block_id_matches_commit
        )
    ),
    CONSTRAINT validator_signatures_absent_vote_consistent CHECK (
        vote_status <> 'absent'
        OR (
            NOT signed
            AND NOT vote_block_id_is_zero
            AND NOT block_id_matches_commit
            AND vote_block_id_hash_base64 IS NULL
            AND vote_block_id_hash_hex IS NULL
            AND vote_block_id_parts_total IS NULL
            AND vote_block_id_parts_hash_base64 IS NULL
            AND vote_block_id_parts_hash_hex IS NULL
            AND signature_base64 IS NULL
            AND raw_precommit IS NULL
        )
    ),
    CONSTRAINT validator_signatures_invalid_vote_consistent CHECK (
        vote_status <> 'invalid'
        OR (NOT signed AND NOT block_id_matches_commit)
    ),
    CONSTRAINT validator_signatures_vote_hash_hex_uppercase CHECK (
        vote_block_id_hash_hex IS NULL OR vote_block_id_hash_hex = upper(vote_block_id_hash_hex)
    ),
    CONSTRAINT validator_signatures_vote_parts_hash_hex_uppercase CHECK (
        vote_block_id_parts_hash_hex IS NULL OR vote_block_id_parts_hash_hex = upper(vote_block_id_parts_hash_hex)
    )
);

COMMENT ON TABLE validator_signatures IS 'One vote result per validator per finalized height. Primary key makes reprocessing idempotent.';
COMMENT ON COLUMN validator_signatures.vote_status IS 'Normalized vote status: commit, nil, absent, or invalid.';
COMMENT ON COLUMN validator_signatures.signed IS 'True only for commit votes whose Vote.BlockID matches the enclosing Commit.BlockID; a non-null signature alone is insufficient.';
COMMENT ON COLUMN validator_signatures.vote_block_id_hash_base64 IS 'Parsed Vote.BlockID hash from a non-null precommit, preserved as base64 when present.';
COMMENT ON COLUMN validator_signatures.vote_block_id_hash_hex IS 'Uppercase hex form of Vote.BlockID hash when present.';
COMMENT ON COLUMN validator_signatures.vote_block_id_parts_hash_base64 IS 'Parsed Vote.BlockID part-set hash from a non-null precommit, preserved as base64 when present.';
COMMENT ON COLUMN validator_signatures.vote_block_id_parts_hash_hex IS 'Uppercase hex form of the parsed Vote.BlockID part-set hash when present.';
COMMENT ON COLUMN validator_signatures.vote_block_id_is_zero IS 'True when the parsed Vote.BlockID is zero, which represents a nil vote.';
COMMENT ON COLUMN validator_signatures.block_id_matches_commit IS 'True only when the parsed Vote.BlockID matches the enclosing Commit.BlockID for the same height.';
COMMENT ON COLUMN validator_signatures.raw_precommit IS 'Optional short-retention precommit JSON for parser auditing. Nil and invalid votes may retain it.';

-- Uptime over latest 1,000 finalized heights and recent 100 signature squares filter by validator, height, and normalized vote status.
CREATE INDEX validator_signatures_signing_height_status_idx ON validator_signatures (signing_address, height DESC, vote_status, signed);
-- Recent network-wide miss/nil/invalid summaries group by height and filter normalized vote status.
CREATE INDEX validator_signatures_height_status_idx ON validator_signatures (height DESC, vote_status, signing_address);

CREATE TABLE rpc_endpoints (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url TEXT NOT NULL,
    chain_id TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    is_selected BOOLEAN NOT NULL DEFAULT false,
    last_checked_at TIMESTAMPTZ,
    last_selected_at TIMESTAMPTZ,
    latest_observed_height BIGINT CONSTRAINT rpc_endpoints_latest_observed_height_check CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0),
    observed_lag BIGINT CONSTRAINT rpc_endpoints_observed_lag_check CHECK (observed_lag IS NULL OR observed_lag >= 0),
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

CREATE TABLE rpc_endpoint_checks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rpc_endpoint_id BIGINT NOT NULL REFERENCES rpc_endpoints(id) ON DELETE CASCADE,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    chain_id TEXT NOT NULL,
    latest_observed_height BIGINT CONSTRAINT rpc_endpoint_checks_latest_observed_height_check CHECK (latest_observed_height IS NULL OR latest_observed_height >= 0),
    observed_lag BIGINT CONSTRAINT rpc_endpoint_checks_observed_lag_check CHECK (observed_lag IS NULL OR observed_lag >= 0),
    catching_up BOOLEAN,
    healthy BOOLEAN NOT NULL,
    selected_for_cycle BOOLEAN NOT NULL DEFAULT false,
    switch_reason TEXT,
    error_message TEXT
);

COMMENT ON TABLE rpc_endpoint_checks IS 'Append-only RPC health and selection history for auditing endpoint switching.';
COMMENT ON COLUMN rpc_endpoint_checks.selected_for_cycle IS 'True when this health check led to or confirmed endpoint selection for an indexing cycle.';
COMMENT ON COLUMN rpc_endpoint_checks.switch_reason IS 'Optional non-secret reason recorded when selected endpoint changes.';

-- RPC operations pages query recent checks by endpoint and time.
CREATE INDEX rpc_endpoint_checks_endpoint_time_idx ON rpc_endpoint_checks (rpc_endpoint_id, checked_at DESC);
-- Switching audit queries inspect selected historical checks by chain and time.
CREATE INDEX rpc_endpoint_checks_chain_selected_time_idx ON rpc_endpoint_checks (chain_id, selected_for_cycle, checked_at DESC);

CREATE TABLE indexer_state (
    state_key TEXT PRIMARY KEY,
    chain_id TEXT NOT NULL,
    last_finalized_height BIGINT NOT NULL CONSTRAINT indexer_state_last_finalized_height_check CHECK (last_finalized_height >= 0),
    finalized_tip_height BIGINT CONSTRAINT indexer_state_finalized_tip_height_check CHECK (finalized_tip_height IS NULL OR finalized_tip_height >= last_finalized_height),
    selected_rpc_endpoint_id BIGINT REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT indexer_state_default_key CHECK (state_key = 'default')
);

COMMENT ON TABLE indexer_state IS 'Singleton checkpoint for resumable indexing. Advance only after a finalized height transaction succeeds.';
COMMENT ON COLUMN indexer_state.last_finalized_height IS 'Most recent fully processed signing height. Do not update after partial processing.';
COMMENT ON COLUMN indexer_state.finalized_tip_height IS 'Most recent finalized tip derived as latest RPC height H minus one; indexing still advances one target height S at a time.';

-- The default row is expected to be created by deployment or migration tooling before indexing starts.
