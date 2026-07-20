CREATE TABLE validator_profiles (
    operator_address TEXT PRIMARY KEY,
    moniker TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    server_type TEXT,
    keep_running BOOLEAN,
    consensus_pubkey TEXT NOT NULL,
    normalized_public_key_type TEXT,
    normalized_public_key_value TEXT,
    signing_address TEXT REFERENCES validators(signing_address) ON DELETE SET NULL,
    match_status TEXT NOT NULL,
    source_realm TEXT NOT NULL,
    source_profile_path TEXT,
    source_height BIGINT NOT NULL,
    profile_hash TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT validator_profiles_match_status_check CHECK (match_status IN ('matched', 'unmatched', 'invalid_pubkey', 'ambiguous')),
    CONSTRAINT validator_profiles_source_height_check CHECK (source_height >= 0),
    CONSTRAINT validator_profiles_required_text_check CHECK (
        char_length(operator_address) BETWEEN 1 AND 128
        AND char_length(moniker) BETWEEN 1 AND 256
        AND char_length(consensus_pubkey) BETWEEN 1 AND 256
        AND char_length(source_realm) BETWEEN 1 AND 256
        AND profile_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT validator_profiles_bounded_text_check CHECK (
        char_length(description) <= 2048
        AND char_length(moniker) <= 32
        AND server_type IN ('cloud', 'on-prem', 'data-center')
        AND (source_profile_path IS NULL OR char_length(source_profile_path) <= 512)
    ),
    CONSTRAINT validator_profiles_match_consistency_check CHECK (
        (normalized_public_key_type IS NULL) = (normalized_public_key_value IS NULL)
        AND (
            (match_status = 'matched' AND signing_address IS NOT NULL AND normalized_public_key_type IS NOT NULL)
            OR (match_status IN ('unmatched', 'ambiguous') AND signing_address IS NULL AND normalized_public_key_type IS NOT NULL)
            OR (match_status = 'invalid_pubkey' AND signing_address IS NULL AND normalized_public_key_type IS NULL)
        )
    )
);

COMMENT ON TABLE validator_profiles IS 'Public Valopers realm profiles; rows are retained when absent from a later crawl.';
COMMENT ON COLUMN validator_profiles.operator_address IS 'Owner/profile address from Valopers; it is not a TM2 consensus signing address.';
COMMENT ON COLUMN validator_profiles.signing_address IS 'TM2 consensus signing address matched only through the exact normalized consensus public key.';
COMMENT ON COLUMN validator_profiles.keep_running IS 'Source profile preference only; it is not active-set, signing-health, governance, or punishment state.';
COMMENT ON COLUMN validator_profiles.source_height IS 'Pinned committed chain height used for every VM query in this synchronization.';
CREATE INDEX validator_profiles_signing_address_idx ON validator_profiles (signing_address);
CREATE INDEX validator_profiles_consensus_pubkey_idx ON validator_profiles (consensus_pubkey);
CREATE INDEX validator_profiles_moniker_lower_idx ON validator_profiles (lower(moniker));
