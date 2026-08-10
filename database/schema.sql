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
    tx_hash_hex TEXT,
    payload_summary JSONB,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transactions_block_position_unique UNIQUE (block_height, tx_index),
    CONSTRAINT transactions_raw_base64_length_matches CHECK (raw_base64_length = char_length(raw_base64)),
    CONSTRAINT transactions_decode_status_consistent CHECK (
        (decode_status = 'decoded' AND decoded_bytes IS NOT NULL AND decoded_byte_length = octet_length(decoded_bytes))
        OR (decode_status IN ('invalid_base64', 'not_attempted') AND decoded_bytes IS NULL AND decoded_byte_length IS NULL)
    ),
    CONSTRAINT transactions_tx_hash_hex_format CHECK (tx_hash_hex IS NULL OR tx_hash_hex ~ '^[0-9A-F]{64}$'),
    CONSTRAINT transactions_tx_hash_consistent CHECK (
        (decode_status = 'decoded' AND tx_hash_hex IS NOT NULL)
        OR (decode_status IN ('invalid_base64', 'not_attempted') AND tx_hash_hex IS NULL)
    )
);

COMMENT ON TABLE transactions IS 'Ordered transactions within a block. The block position uniqueness makes reprocessing idempotent.';
COMMENT ON COLUMN transactions.raw_base64 IS 'Raw transaction string exactly as returned by result.block.data.txs.';
COMMENT ON COLUMN transactions.decoded_bytes IS 'Decoded bytes when base64 decoding succeeds; full Gno transaction parsing is deferred.';
COMMENT ON COLUMN transactions.tx_hash_hex IS 'SHA-256 of the exact decoded Tendermint2 transaction bytes, in the Explorer canonical uppercase hexadecimal display/search form.';
COMMENT ON COLUMN transactions.payload_summary IS 'Limited JSONB for future decoded payload summaries, not raw unbounded application data.';
CREATE INDEX transactions_tx_hash_hex_idx ON transactions(tx_hash_hex) WHERE tx_hash_hex IS NOT NULL;

CREATE TABLE transaction_participants (
    block_height BIGINT NOT NULL CONSTRAINT transaction_participants_block_height_check CHECK (block_height > 0),
    tx_index INTEGER NOT NULL CONSTRAINT transaction_participants_tx_index_check CHECK (tx_index >= 0),
    message_index INTEGER NOT NULL CONSTRAINT transaction_participants_message_index_check CHECK (message_index BETWEEN 0 AND 19),
    role TEXT NOT NULL CONSTRAINT transaction_participants_role_check CHECK (role IN ('sender', 'recipient')),
    address TEXT NOT NULL CONSTRAINT transaction_participants_address_check CHECK (
        char_length(address) = 40 AND address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'
    ),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (block_height, tx_index, message_index, role, address),
    FOREIGN KEY (block_height, tx_index)
        REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE
);

CREATE INDEX transaction_participants_address_position_idx
    ON transaction_participants (address, block_height DESC, tx_index DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
        EXECUTE 'GRANT SELECT ON TABLE transaction_participants TO utsa_gno_api';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_indexer') THEN
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON TABLE transaction_participants TO utsa_gno_indexer';
    END IF;
END $$;

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
    latency_ms INTEGER CONSTRAINT rpc_endpoints_latency_ms_check CHECK (latency_ms IS NULL OR latency_ms BETWEEN 0 AND 30000),
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

-- Aggregated observed network-distribution samples. This schema stores no raw RPC or GeoIP payloads.
CREATE TABLE network_distribution_geo_cache (
    ip INET PRIMARY KEY,
    lookup_success BOOLEAN NOT NULL,
    continent_name TEXT CONSTRAINT network_distribution_geo_cache_continent_name_check CHECK (continent_name IS NULL OR char_length(continent_name) <= 128),
    country_code TEXT CONSTRAINT network_distribution_geo_cache_country_code_check CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    country_name TEXT CONSTRAINT network_distribution_geo_cache_country_name_check CHECK (country_name IS NULL OR char_length(country_name) <= 128),
    region_name TEXT CONSTRAINT network_distribution_geo_cache_region_name_check CHECK (region_name IS NULL OR char_length(region_name) <= 255),
    asn BIGINT CONSTRAINT network_distribution_geo_cache_asn_check CHECK (asn IS NULL OR asn > 0),
    provider_name TEXT CONSTRAINT network_distribution_geo_cache_provider_name_check CHECK (provider_name IS NULL OR char_length(provider_name) <= 255),
    lookup_provider TEXT NOT NULL CONSTRAINT network_distribution_geo_cache_lookup_provider_check CHECK (char_length(lookup_provider) BETWEEN 1 AND 128),
    fetched_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    error_code TEXT CONSTRAINT network_distribution_geo_cache_error_code_check CHECK (error_code IS NULL OR char_length(error_code) <= 64),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT network_distribution_geo_cache_expiry_check CHECK (expires_at >= fetched_at),
    CONSTRAINT network_distribution_geo_cache_state_check CHECK (
        (lookup_success AND error_code IS NULL)
        OR (NOT lookup_success AND error_code IS NOT NULL AND continent_name IS NULL
            AND country_code IS NULL AND country_name IS NULL AND region_name IS NULL
            AND asn IS NULL AND provider_name IS NULL)
    )
);
CREATE INDEX network_distribution_geo_cache_expires_idx ON network_distribution_geo_cache (expires_at);
CREATE INDEX network_distribution_geo_cache_country_idx ON network_distribution_geo_cache (country_code) WHERE lookup_success AND country_code IS NOT NULL;
CREATE INDEX network_distribution_geo_cache_asn_idx ON network_distribution_geo_cache (asn, provider_name) WHERE lookup_success AND asn IS NOT NULL;

CREATE TABLE network_distribution_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chain_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    scanned_at TIMESTAMPTZ NOT NULL,
    rpc_sources_total INTEGER NOT NULL,
    rpc_sources_ok INTEGER NOT NULL,
    visible_node_ids INTEGER NOT NULL,
    unique_public_ips INTEGER NOT NULL,
    geolocated_node_ids INTEGER NOT NULL,
    geolocated_public_ips INTEGER NOT NULL,
    node_id_ip_conflicts INTEGER NOT NULL DEFAULT 0,
    region_count INTEGER NOT NULL,
    country_count INTEGER NOT NULL,
    provider_count INTEGER NOT NULL,
    regions JSONB NOT NULL,
    countries JSONB NOT NULL,
    providers JSONB NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT network_distribution_snapshots_counts_check CHECK (rpc_sources_total >= 0 AND rpc_sources_ok >= 0 AND visible_node_ids >= 0 AND unique_public_ips >= 0 AND geolocated_node_ids >= 0 AND geolocated_public_ips >= 0 AND node_id_ip_conflicts >= 0 AND region_count >= 0 AND country_count >= 0 AND provider_count >= 0 AND rpc_sources_ok <= rpc_sources_total AND geolocated_node_ids <= visible_node_ids AND geolocated_public_ips <= unique_public_ips),
    CONSTRAINT network_distribution_snapshots_arrays_check CHECK (jsonb_typeof(regions) = 'array' AND jsonb_typeof(countries) = 'array' AND jsonb_typeof(providers) = 'array')
);
CREATE INDEX network_distribution_snapshots_chain_latest_idx ON network_distribution_snapshots (chain_id, scanned_at DESC, id DESC);

CREATE TABLE network_distribution_snapshot_sources (
    snapshot_id BIGINT NOT NULL REFERENCES network_distribution_snapshots(id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL,
    rpc_endpoint_id BIGINT REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
    success BOOLEAN NOT NULL,
    reported_peer_count INTEGER,
    accepted_peer_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    error_code TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, source_order),
    CONSTRAINT network_distribution_snapshot_sources_values_check CHECK (source_order >= 0 AND (reported_peer_count IS NULL OR reported_peer_count >= 0) AND accepted_peer_count >= 0 AND (duration_ms IS NULL OR duration_ms >= 0) AND (error_code IS NULL OR char_length(error_code) <= 64)),
    CONSTRAINT network_distribution_snapshot_sources_state_check CHECK ((success AND error_code IS NULL) OR (NOT success AND error_code IS NOT NULL))
);

CREATE TABLE governance_proposals (
    chain_id TEXT NOT NULL CONSTRAINT governance_proposals_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    realm_path TEXT NOT NULL CONSTRAINT governance_proposals_realm_path_check CHECK (char_length(realm_path) BETWEEN 1 AND 512),
    proposal_id BIGINT NOT NULL CONSTRAINT governance_proposals_proposal_id_check CHECK (proposal_id >= 0),
    title TEXT NOT NULL CONSTRAINT governance_proposals_title_check CHECK (char_length(title) BETWEEN 1 AND 1000),
    author_display TEXT CONSTRAINT governance_proposals_author_display_check CHECK (author_display IS NULL OR char_length(author_display) <= 1000),
    author_address TEXT CONSTRAINT governance_proposals_author_address_check CHECK (author_address IS NULL OR author_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    status TEXT NOT NULL CONSTRAINT governance_proposals_status_check CHECK (status IN ('ACTIVE', 'ACCEPTED', 'REJECTED', 'UNKNOWN')),
    eligible_tiers JSONB NOT NULL CONSTRAINT governance_proposals_eligible_tiers_check CHECK (jsonb_typeof(eligible_tiers) = 'array'),
    description TEXT NOT NULL CONSTRAINT governance_proposals_description_check CHECK (char_length(description) <= 100000),
    executor_text TEXT CONSTRAINT governance_proposals_executor_text_check CHECK (executor_text IS NULL OR char_length(executor_text) <= 100000),
    executor_creation_realm TEXT CONSTRAINT governance_proposals_executor_creation_realm_check CHECK (executor_creation_realm IS NULL OR char_length(executor_creation_realm) <= 1000),
    rejection_reason TEXT CONSTRAINT governance_proposals_rejection_reason_check CHECK (rejection_reason IS NULL OR char_length(rejection_reason) <= 10000),
    yes_percent NUMERIC(7,4), no_percent NUMERIC(7,4), abstain_percent NUMERIC(7,4),
    detail_parse_status TEXT NOT NULL CONSTRAINT governance_proposals_detail_parse_status_check CHECK (detail_parse_status IN ('parsed', 'partial')),
    votes_parse_status TEXT NOT NULL CONSTRAINT governance_proposals_votes_parse_status_check CHECK (votes_parse_status IN ('parsed', 'empty', 'unparsed')),
    parse_warnings JSONB NOT NULL CONSTRAINT governance_proposals_parse_warnings_check CHECK (jsonb_typeof(parse_warnings) = 'array'),
    raw_detail_render TEXT, raw_votes_render TEXT,
    first_observed_height BIGINT NOT NULL, last_observed_height BIGINT NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, realm_path, proposal_id),
    CONSTRAINT governance_proposals_percentages_check CHECK ((yes_percent IS NULL OR yes_percent BETWEEN 0 AND 100) AND (no_percent IS NULL OR no_percent BETWEEN 0 AND 100) AND (abstain_percent IS NULL OR abstain_percent BETWEEN 0 AND 100)),
    CONSTRAINT governance_proposals_raw_size_check CHECK ((raw_detail_render IS NULL OR octet_length(raw_detail_render) <= 1048576) AND (raw_votes_render IS NULL OR octet_length(raw_votes_render) <= 1048576)),
    CONSTRAINT governance_proposals_heights_check CHECK (first_observed_height >= 1 AND last_observed_height >= first_observed_height),
    CONSTRAINT governance_proposals_times_check CHECK (last_observed_at >= first_observed_at)
);
CREATE INDEX governance_proposals_realm_id_idx ON governance_proposals (chain_id, realm_path, proposal_id DESC);
CREATE INDEX governance_proposals_realm_status_id_idx ON governance_proposals (chain_id, realm_path, status, proposal_id DESC);

CREATE TABLE governance_votes (
    chain_id TEXT NOT NULL, realm_path TEXT NOT NULL, proposal_id BIGINT NOT NULL,
    voter_key TEXT NOT NULL CONSTRAINT governance_votes_voter_key_check CHECK (char_length(voter_key) BETWEEN 1 AND 1100),
    voter_display TEXT NOT NULL CONSTRAINT governance_votes_voter_display_check CHECK (char_length(voter_display) BETWEEN 1 AND 1000),
    voter_address TEXT CONSTRAINT governance_votes_voter_address_check CHECK (voter_address IS NULL OR voter_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    option TEXT NOT NULL CONSTRAINT governance_votes_option_check CHECK (option IN ('YES', 'NO', 'ABSTAIN')),
    tier TEXT NOT NULL CONSTRAINT governance_votes_tier_check CHECK (char_length(tier) BETWEEN 1 AND 64),
    voting_power NUMERIC(78,0) NOT NULL CONSTRAINT governance_votes_voting_power_check CHECK (voting_power >= 0),
    first_observed_height BIGINT NOT NULL, last_observed_height BIGINT NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, realm_path, proposal_id, voter_key),
    FOREIGN KEY (chain_id, realm_path, proposal_id) REFERENCES governance_proposals(chain_id, realm_path, proposal_id) ON DELETE CASCADE,
    CONSTRAINT governance_votes_heights_check CHECK (first_observed_height >= 1 AND last_observed_height >= first_observed_height),
    CONSTRAINT governance_votes_times_check CHECK (last_observed_at >= first_observed_at)
);
CREATE INDEX governance_votes_voter_address_idx ON governance_votes (voter_address) WHERE voter_address IS NOT NULL;

CREATE TABLE governance_sync_state (
    chain_id TEXT NOT NULL CONSTRAINT governance_sync_state_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    realm_path TEXT NOT NULL CONSTRAINT governance_sync_state_realm_path_check CHECK (char_length(realm_path) BETWEEN 1 AND 512),
    source_height BIGINT NOT NULL CONSTRAINT governance_sync_state_source_height_check CHECK (source_height >= 1),
    page_count INTEGER NOT NULL CONSTRAINT governance_sync_state_page_count_check CHECK (page_count BETWEEN 1 AND 100),
    proposal_count INTEGER NOT NULL CONSTRAINT governance_sync_state_proposal_count_check CHECK (proposal_count BETWEEN 0 AND 1000),
    first_proposal_id BIGINT, latest_proposal_id BIGINT,
    last_success_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, realm_path),
    CONSTRAINT governance_sync_state_counts_check CHECK ((proposal_count = 0 AND first_proposal_id IS NULL AND latest_proposal_id IS NULL AND page_count >= 1) OR (proposal_count > 0 AND first_proposal_id IS NOT NULL AND latest_proposal_id IS NOT NULL AND first_proposal_id >= 0 AND latest_proposal_id >= first_proposal_id AND page_count >= 1))
);

CREATE TABLE valoper_profiles (
    operator_address TEXT PRIMARY KEY,
    moniker TEXT NOT NULL,
    description TEXT NOT NULL,
    server_type TEXT NOT NULL,
    signing_address TEXT NOT NULL,
    signing_pubkey TEXT NOT NULL,
    source_height BIGINT NOT NULL,
    list_position INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT valoper_profiles_signing_address_unique UNIQUE (signing_address),
    CONSTRAINT valoper_profiles_signing_pubkey_unique UNIQUE (signing_pubkey),
    CONSTRAINT valoper_profiles_source_height_check CHECK (source_height >= 1),
    CONSTRAINT valoper_profiles_list_position_check CHECK (list_position >= 0),
    CONSTRAINT valoper_profiles_moniker_length_check CHECK (char_length(moniker) BETWEEN 1 AND 32),
    CONSTRAINT valoper_profiles_description_length_check CHECK (octet_length(description) BETWEEN 1 AND 2048),
    CONSTRAINT valoper_profiles_server_type_check CHECK (server_type IN ('cloud', 'on-prem', 'data-center')),
    CONSTRAINT valoper_profiles_operator_address_check CHECK (operator_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    CONSTRAINT valoper_profiles_signing_address_check CHECK (signing_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    CONSTRAINT valoper_profiles_signing_pubkey_check CHECK (
        signing_pubkey ~ '^gpub1[023456789acdefghjklmnpqrstuvwxyz]+$'
        AND octet_length(signing_pubkey) BETWEEN 91 AND 256
    )
);

COMMENT ON TABLE valoper_profiles IS 'Current complete official Valopers registry, replaced atomically by future persistence tooling.';
COMMENT ON COLUMN valoper_profiles.operator_address IS 'Official Valoper operator address; parser-level lowercase syntax is enforced without Bech32 checksum validation.';
COMMENT ON COLUMN valoper_profiles.signing_address IS 'Official signing address; intentionally has no foreign key to the active validators table.';
COMMENT ON COLUMN valoper_profiles.signing_pubkey IS 'Official gpub signing public key retained without PostgreSQL Amino decoding.';
COMMENT ON COLUMN valoper_profiles.source_height IS 'Pinned chain height from which this complete profile snapshot was collected.';
COMMENT ON COLUMN valoper_profiles.list_position IS 'Zero-based order of the profile in the complete official registry.';

CREATE INDEX valoper_profiles_list_position_idx ON valoper_profiles (list_position, operator_address);
CREATE INDEX valoper_profiles_moniker_idx ON valoper_profiles (moniker, operator_address);

CREATE TABLE valopers_snapshot_state (
    state_key TEXT PRIMARY KEY,
    chain_id TEXT NOT NULL,
    source_height BIGINT NOT NULL,
    page_count INTEGER NOT NULL,
    profile_count INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT valopers_snapshot_state_default_key CHECK (state_key = 'default'),
    CONSTRAINT valopers_snapshot_state_source_height_check CHECK (source_height >= 1),
    CONSTRAINT valopers_snapshot_state_page_count_check CHECK (page_count BETWEEN 0 AND 20),
    CONSTRAINT valopers_snapshot_state_profile_count_check CHECK (profile_count BETWEEN 0 AND 1000),
    CONSTRAINT valopers_snapshot_state_counts_consistent CHECK (
        (profile_count = 0 AND page_count = 0)
        OR (profile_count > 0 AND page_count >= 1)
    )
);

COMMENT ON TABLE valopers_snapshot_state IS 'Singleton metadata for the complete snapshot represented by valoper_profiles, including an empty registry.';
COMMENT ON COLUMN valopers_snapshot_state.state_key IS 'Singleton key; the only permitted value is default.';
COMMENT ON COLUMN valopers_snapshot_state.chain_id IS 'Chain identifier for the complete snapshot.';
COMMENT ON COLUMN valopers_snapshot_state.source_height IS 'Pinned chain height shared by the complete snapshot.';
COMMENT ON COLUMN valopers_snapshot_state.page_count IS 'Number of registry list pages collected; zero only for an empty registry.';
COMMENT ON COLUMN valopers_snapshot_state.profile_count IS 'Number of complete profile rows represented by the snapshot.';
COMMENT ON COLUMN valopers_snapshot_state.updated_at IS 'Time at which future persistence tooling atomically replaced the snapshot.';
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
BEGIN;

CREATE TABLE realm_catalog (
 chain_id TEXT NOT NULL, path TEXT NOT NULL, path_kind TEXT NOT NULL,
 seen_via_rpc BOOLEAN NOT NULL DEFAULT false, seen_via_transactions BOOLEAN NOT NULL DEFAULT false,
 rpc_visible BOOLEAN NOT NULL DEFAULT false, deployer_address TEXT, deploy_height BIGINT,
 deploy_tx_index INTEGER, first_seen_height BIGINT, last_activity_height BIGINT,
 last_activity_tx_index INTEGER, last_activity_at TIMESTAMPTZ, call_count BIGINT NOT NULL DEFAULT 0,
 successful_call_count BIGINT NOT NULL DEFAULT 0, failed_call_count BIGINT NOT NULL DEFAULT 0,
 unknown_result_call_count BIGINT NOT NULL DEFAULT 0, last_counted_height BIGINT,
 first_discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_rpc_seen_at TIMESTAMPTZ,
 inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (chain_id, path),
 CONSTRAINT realm_catalog_path_kind_check CHECK (path_kind IN ('realm','package')),
 CONSTRAINT realm_catalog_path_check CHECK (char_length(path) BETWEEN 1 AND 256 AND path ~ '^gno\.land/[rp]/[!-\.0-~]+(/[!-\.0-~]+)*$' AND path !~ '[?#]' AND ((path_kind='realm' AND path LIKE 'gno.land/r/%') OR (path_kind='package' AND path LIKE 'gno.land/p/%'))),
 CONSTRAINT realm_catalog_deployer_check CHECK (deployer_address IS NULL OR deployer_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
 CONSTRAINT realm_catalog_deploy_position_check CHECK ((deploy_height IS NULL) = (deploy_tx_index IS NULL) AND (deploy_height IS NULL OR (deploy_height > 0 AND deploy_tx_index >= 0))),
 CONSTRAINT realm_catalog_activity_position_check CHECK ((last_activity_height IS NULL) = (last_activity_tx_index IS NULL) AND (last_activity_height IS NULL) = (last_activity_at IS NULL) AND (last_activity_height IS NULL OR (last_activity_height > 0 AND last_activity_tx_index >= 0))),
 CONSTRAINT realm_catalog_counters_check CHECK (call_count >= 0 AND successful_call_count >= 0 AND failed_call_count >= 0 AND unknown_result_call_count >= 0 AND successful_call_count + failed_call_count + unknown_result_call_count = call_count),
 CONSTRAINT realm_catalog_counted_height_check CHECK ((call_count = 0 AND last_counted_height IS NULL) OR (call_count > 0 AND last_counted_height IS NOT NULL AND last_counted_height > 0)),
 CONSTRAINT realm_catalog_first_seen_check CHECK (first_seen_height IS NULL OR first_seen_height > 0),
 CONSTRAINT realm_catalog_rpc_visibility_check CHECK (NOT rpc_visible OR seen_via_rpc),
 CONSTRAINT realm_catalog_rpc_seen_at_check CHECK ((NOT seen_via_rpc AND last_rpc_seen_at IS NULL) OR (seen_via_rpc AND last_rpc_seen_at IS NOT NULL)),
 CONSTRAINT realm_catalog_transaction_metadata_check CHECK (seen_via_transactions OR (deployer_address IS NULL AND deploy_height IS NULL AND first_seen_height IS NULL AND last_activity_height IS NULL AND call_count = 0))
);
CREATE INDEX realm_catalog_kind_path_idx ON realm_catalog(chain_id,path_kind,path);
CREATE INDEX realm_catalog_visibility_idx ON realm_catalog(chain_id,rpc_visible,path_kind);
CREATE INDEX realm_catalog_activity_idx ON realm_catalog(chain_id,last_activity_height DESC,path);
CREATE INDEX realm_catalog_calls_idx ON realm_catalog(chain_id,call_count DESC,path);

CREATE TABLE realm_catalog_state (
 chain_id TEXT PRIMARY KEY, observed_height BIGINT NOT NULL, rpc_path_count INTEGER NOT NULL,
 activity_from_height BIGINT, activity_through_height BIGINT,
 source_rpc_endpoint_id BIGINT REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
 refreshed_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT realm_catalog_state_observed_height_check CHECK (observed_height > 0),
 CONSTRAINT realm_catalog_state_path_count_check CHECK (rpc_path_count BETWEEN 0 AND 10000),
 CONSTRAINT realm_catalog_state_activity_range_check CHECK ((activity_from_height IS NULL AND activity_through_height IS NULL) OR (activity_from_height > 0 AND activity_through_height >= activity_from_height))
);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_api') THEN GRANT SELECT ON realm_catalog, realm_catalog_state TO utsa_gno_api; END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_indexer') THEN GRANT SELECT,INSERT,UPDATE ON realm_catalog, realm_catalog_state TO utsa_gno_indexer; END IF;
END $$;
COMMIT;

BEGIN;

CREATE TABLE realm_call_index (
    chain_id TEXT NOT NULL,
    block_height BIGINT NOT NULL,
    tx_index INTEGER NOT NULL,
    message_index INTEGER NOT NULL,
    path TEXT NOT NULL,
    caller_address TEXT,
    function_name TEXT,
    args_count INTEGER,
    send_amount TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, block_height, tx_index, message_index),
    FOREIGN KEY (block_height, tx_index)
        REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE,
    CONSTRAINT realm_call_index_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    CONSTRAINT realm_call_index_block_height_check CHECK (block_height > 0),
    CONSTRAINT realm_call_index_tx_index_check CHECK (tx_index >= 0),
    CONSTRAINT realm_call_index_message_index_check CHECK (message_index BETWEEN 0 AND 19),
    CONSTRAINT realm_call_index_path_check CHECK (char_length(path) BETWEEN 1 AND 256 AND path ~ '^gno\.land/r/[!-\.0-~]+(/[!-\.0-~]+)*$' AND path !~ '[?#]'),
    CONSTRAINT realm_call_index_caller_check CHECK (caller_address IS NULL OR caller_address ~ '^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$'),
    CONSTRAINT realm_call_index_function_check CHECK (function_name IS NULL OR char_length(function_name) BETWEEN 1 AND 160),
    CONSTRAINT realm_call_index_args_count_check CHECK (args_count IS NULL OR args_count BETWEEN 0 AND 100000),
    CONSTRAINT realm_call_index_send_check CHECK (send_amount IS NULL OR char_length(send_amount) BETWEEN 1 AND 160)
);
CREATE INDEX realm_call_index_path_position_idx ON realm_call_index
    (chain_id, path, block_height DESC, tx_index DESC, message_index DESC);

CREATE TABLE realm_call_index_state (
    chain_id TEXT PRIMARY KEY,
    from_height BIGINT NOT NULL,
    through_height BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT realm_call_index_state_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
    CONSTRAINT realm_call_index_state_from_height_check CHECK (from_height > 0),
    CONSTRAINT realm_call_index_state_range_check CHECK (through_height >= from_height)
);

COMMENT ON TABLE realm_call_index IS 'Compact locator projection of bounded MsgCall summaries; heavy call payloads remain excluded.';
COMMENT ON TABLE realm_call_index_state IS 'Continuous block range whose bounded MsgCall observations were processed into realm_call_index.';

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_api') THEN
  GRANT SELECT ON realm_call_index, realm_call_index_state TO utsa_gno_api;
 END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_indexer') THEN
  GRANT SELECT,INSERT,UPDATE,DELETE ON realm_call_index, realm_call_index_state TO utsa_gno_indexer;
 END IF;
END $$;

COMMIT;
BEGIN;

CREATE TABLE realm_metadata (
 chain_id TEXT NOT NULL CONSTRAINT realm_metadata_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
 path TEXT NOT NULL, path_kind TEXT NOT NULL, observed_height BIGINT NOT NULL,
 collection_status TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 file_count INTEGER NOT NULL, gno_file_count INTEGER NOT NULL, test_file_count INTEGER NOT NULL,
 has_gnomod BOOLEAN NOT NULL, total_file_bytes BIGINT NOT NULL, total_file_lines BIGINT NOT NULL,
 dependency_count INTEGER NOT NULL, source_rpc_endpoint_id BIGINT,
 qdoc_status TEXT NOT NULL, qdoc_summary JSONB, qdoc_last_successful_height BIGINT, qdoc_payload JSONB,
 qpkg_json_status TEXT NOT NULL, qpkg_json_summary JSONB, qpkg_json_last_successful_height BIGINT, qpkg_json_payload JSONB,
 qfuncs_status TEXT NOT NULL, qfuncs_summary JSONB, qfuncs_last_successful_height BIGINT, qfuncs_payload JSONB,
 qrender_status TEXT NOT NULL, qrender_last_successful_height BIGINT, qrender_sha256 TEXT,
 qrender_byte_count BIGINT, qrender_line_count BIGINT, qrender_non_empty BOOLEAN,
 qstorage_status TEXT NOT NULL, qstorage_last_successful_height BIGINT,
 qstorage_bytes NUMERIC(40,0), qstorage_deposit_ugnot NUMERIC(40,0),
 collected_at TIMESTAMPTZ NOT NULL, inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (chain_id,path),
 FOREIGN KEY (chain_id,path) REFERENCES realm_catalog(chain_id,path) ON DELETE CASCADE,
 FOREIGN KEY (source_rpc_endpoint_id) REFERENCES rpc_endpoints(id) ON DELETE SET NULL,
 CONSTRAINT realm_metadata_path_kind_check CHECK (path_kind IN ('realm','package')),
 CONSTRAINT realm_metadata_path_check CHECK (char_length(path) BETWEEN 1 AND 256 AND path ~ '^gno\.land/[rp]/[!-\.0-~]+(/[!-\.0-~]+)*$' AND path !~ '[?#]' AND ((path_kind='realm' AND path LIKE 'gno.land/r/%') OR (path_kind='package' AND path LIKE 'gno.land/p/%'))),
 CONSTRAINT realm_metadata_height_check CHECK (observed_height > 0),
 CONSTRAINT realm_metadata_collection_status_check CHECK (collection_status IN ('complete','partial')),
 CONSTRAINT realm_metadata_sha256_check CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
 CONSTRAINT realm_metadata_counts_check CHECK (file_count BETWEEN 1 AND 256 AND gno_file_count BETWEEN 0 AND file_count AND test_file_count BETWEEN 0 AND gno_file_count AND total_file_bytes BETWEEN 0 AND 8388608 AND total_file_lines BETWEEN 0 AND 25600000 AND dependency_count BETWEEN 0 AND 256000),
 CONSTRAINT realm_metadata_capability_status_check CHECK (qdoc_status IN ('ok','not_applicable','application_error','rpc_error','invalid_response') AND qpkg_json_status IN ('ok','not_applicable','application_error','rpc_error','invalid_response') AND qfuncs_status IN ('ok','not_applicable','application_error','rpc_error','invalid_response') AND qrender_status IN ('ok','not_applicable','application_error','rpc_error','invalid_response') AND qstorage_status IN ('ok','not_applicable','application_error','rpc_error','invalid_response')),
 CONSTRAINT realm_metadata_json_types_check CHECK ((qdoc_summary IS NULL OR jsonb_typeof(qdoc_summary)='object') AND (qpkg_json_summary IS NULL OR jsonb_typeof(qpkg_json_summary)='object') AND (qfuncs_summary IS NULL OR jsonb_typeof(qfuncs_summary)='object') AND (qdoc_payload IS NULL OR jsonb_typeof(qdoc_payload)='object') AND (qpkg_json_payload IS NULL OR jsonb_typeof(qpkg_json_payload) IN ('object','array')) AND (qfuncs_payload IS NULL OR jsonb_typeof(qfuncs_payload)='array')),
 CONSTRAINT realm_metadata_success_heights_check CHECK ((qdoc_last_successful_height IS NULL OR qdoc_last_successful_height > 0) AND (qpkg_json_last_successful_height IS NULL OR qpkg_json_last_successful_height > 0) AND (qfuncs_last_successful_height IS NULL OR qfuncs_last_successful_height > 0) AND (qrender_last_successful_height IS NULL OR qrender_last_successful_height > 0) AND (qstorage_last_successful_height IS NULL OR qstorage_last_successful_height > 0)),
 CONSTRAINT realm_metadata_json_success_check CHECK (((qdoc_summary IS NULL AND qdoc_payload IS NULL AND qdoc_last_successful_height IS NULL) OR (qdoc_summary IS NOT NULL AND qdoc_payload IS NOT NULL AND qdoc_last_successful_height IS NOT NULL)) AND ((qdoc_status='ok' AND qdoc_last_successful_height IS NOT NULL AND qdoc_last_successful_height=observed_height) OR (qdoc_status<>'ok' AND (qdoc_last_successful_height IS NULL OR qdoc_last_successful_height<=observed_height))) AND ((qpkg_json_summary IS NULL AND qpkg_json_payload IS NULL AND qpkg_json_last_successful_height IS NULL) OR (qpkg_json_summary IS NOT NULL AND qpkg_json_payload IS NOT NULL AND qpkg_json_last_successful_height IS NOT NULL)) AND ((qpkg_json_status='ok' AND qpkg_json_last_successful_height IS NOT NULL AND qpkg_json_last_successful_height=observed_height) OR (qpkg_json_status<>'ok' AND (qpkg_json_last_successful_height IS NULL OR qpkg_json_last_successful_height<=observed_height))) AND ((qfuncs_summary IS NULL AND qfuncs_payload IS NULL AND qfuncs_last_successful_height IS NULL) OR (qfuncs_summary IS NOT NULL AND qfuncs_payload IS NOT NULL AND qfuncs_last_successful_height IS NOT NULL)) AND ((qfuncs_status='ok' AND qfuncs_last_successful_height IS NOT NULL AND qfuncs_last_successful_height=observed_height) OR (qfuncs_status<>'ok' AND (qfuncs_last_successful_height IS NULL OR qfuncs_last_successful_height<=observed_height)))),
 CONSTRAINT realm_metadata_qrender_check CHECK (((qrender_sha256 IS NULL AND qrender_byte_count IS NULL AND qrender_line_count IS NULL AND qrender_non_empty IS NULL AND qrender_last_successful_height IS NULL) OR (qrender_sha256 ~ '^[0-9a-f]{64}$' AND qrender_byte_count BETWEEN 0 AND 1048576 AND qrender_line_count BETWEEN 0 AND 1048576 AND qrender_non_empty IS NOT NULL AND qrender_last_successful_height IS NOT NULL)) AND ((qrender_status='ok' AND qrender_last_successful_height IS NOT NULL AND qrender_last_successful_height=observed_height) OR (qrender_status<>'ok' AND (qrender_last_successful_height IS NULL OR qrender_last_successful_height<=observed_height)))),
 CONSTRAINT realm_metadata_qstorage_check CHECK (((qstorage_bytes IS NULL AND qstorage_deposit_ugnot IS NULL AND qstorage_last_successful_height IS NULL) OR (qstorage_bytes BETWEEN 0 AND 9999999999999999999999999999999999999999 AND qstorage_deposit_ugnot BETWEEN 0 AND 9999999999999999999999999999999999999999 AND qstorage_last_successful_height IS NOT NULL)) AND ((qstorage_status='ok' AND qstorage_last_successful_height IS NOT NULL AND qstorage_last_successful_height=observed_height) OR (qstorage_status<>'ok' AND (qstorage_last_successful_height IS NULL OR qstorage_last_successful_height<=observed_height)))),
 CONSTRAINT realm_metadata_package_capabilities_check CHECK (path_kind <> 'package' OR (qrender_status='not_applicable' AND qrender_last_successful_height IS NULL AND qstorage_status='not_applicable' AND qstorage_last_successful_height IS NULL))
);

CREATE TABLE realm_metadata_files (
 chain_id TEXT NOT NULL, path TEXT NOT NULL, filename TEXT NOT NULL, file_kind TEXT NOT NULL,
 content TEXT NOT NULL, byte_count INTEGER NOT NULL, line_count INTEGER NOT NULL, sha256 TEXT NOT NULL,
 package_declared BOOLEAN NOT NULL, import_candidate_count INTEGER NOT NULL,
 inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(chain_id,path,filename),
 FOREIGN KEY(chain_id,path) REFERENCES realm_metadata(chain_id,path) ON DELETE CASCADE,
 CONSTRAINT realm_metadata_files_filename_check CHECK (char_length(filename) BETWEEN 1 AND 160 AND filename !~ '^/' AND filename !~ '^[A-Za-z]:/' AND filename !~ E'\\\\' AND filename !~ '[[:cntrl:]]' AND filename !~ '(^|/)(\.|\.\.|)(/|$)'),
 CONSTRAINT realm_metadata_files_kind_check CHECK (file_kind IN ('gno_source','gno_test','gnomod','other')),
 CONSTRAINT realm_metadata_files_size_check CHECK (byte_count BETWEEN 0 AND 1048576 AND octet_length(content)=byte_count AND line_count BETWEEN 0 AND 100000),
 CONSTRAINT realm_metadata_files_sha256_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 CONSTRAINT realm_metadata_files_import_count_check CHECK (import_candidate_count BETWEEN 0 AND 1000)
);

CREATE TABLE realm_metadata_imports (
 chain_id TEXT NOT NULL, path TEXT NOT NULL, source_filename TEXT NOT NULL,
 imported_path TEXT NOT NULL, imported_kind TEXT NOT NULL,
 PRIMARY KEY(chain_id,path,source_filename,imported_path),
 FOREIGN KEY(chain_id,path,source_filename) REFERENCES realm_metadata_files(chain_id,path,filename) ON DELETE CASCADE,
 CONSTRAINT realm_metadata_imports_kind_check CHECK (imported_kind IN ('realm','package')),
 CONSTRAINT realm_metadata_imports_path_check CHECK (char_length(imported_path) BETWEEN 1 AND 256 AND imported_path ~ '^gno\.land/[rp]/[!-\.0-~]+(/[!-\.0-~]+)*$' AND imported_path !~ '[?#]' AND ((imported_kind='realm' AND imported_path LIKE 'gno.land/r/%') OR (imported_kind='package' AND imported_path LIKE 'gno.land/p/%')))
);
CREATE INDEX realm_metadata_imports_source_idx ON realm_metadata_imports(chain_id,path);
CREATE INDEX realm_metadata_imports_reverse_idx ON realm_metadata_imports(chain_id,imported_path);

CREATE TABLE realm_metadata_refresh_state (
 chain_id TEXT PRIMARY KEY CONSTRAINT realm_metadata_refresh_state_chain_id_check CHECK (char_length(chain_id) BETWEEN 1 AND 128),
 observed_height BIGINT NOT NULL, run_status TEXT NOT NULL, selected_path_count INTEGER NOT NULL,
 published_path_count INTEGER NOT NULL, failed_path_count INTEGER NOT NULL,
 started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
 last_successful_height BIGINT, last_successful_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT realm_metadata_refresh_state_height_check CHECK (observed_height > 0),
 CONSTRAINT realm_metadata_refresh_state_status_check CHECK (run_status IN ('running','complete','partial','failed')),
 CONSTRAINT realm_metadata_refresh_state_counts_check CHECK (selected_path_count >= 0 AND published_path_count >= 0 AND failed_path_count >= 0 AND published_path_count + failed_path_count <= selected_path_count),
 CONSTRAINT realm_metadata_refresh_state_completion_check CHECK ((run_status='running' AND completed_at IS NULL) OR (run_status<>'running' AND completed_at IS NOT NULL)),
 CONSTRAINT realm_metadata_refresh_state_success_check CHECK ((last_successful_height IS NULL)=(last_successful_at IS NULL) AND (last_successful_height IS NULL OR last_successful_height > 0))
);

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_indexer') THEN
  GRANT SELECT,INSERT,UPDATE,DELETE ON realm_metadata,realm_metadata_files,realm_metadata_imports,realm_metadata_refresh_state TO utsa_gno_indexer;
 END IF;
END $$;

COMMIT;
