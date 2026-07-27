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
