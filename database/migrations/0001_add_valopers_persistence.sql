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
