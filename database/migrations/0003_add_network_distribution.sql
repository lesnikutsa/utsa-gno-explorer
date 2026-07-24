-- Aggregated observed network-distribution samples. This schema stores no raw RPC or GeoIP payloads.
CREATE TABLE network_distribution_geo_cache (
    ip INET PRIMARY KEY,
    lookup_success BOOLEAN NOT NULL,
    continent_name TEXT,
    country_code TEXT CONSTRAINT network_distribution_geo_cache_country_code_check CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    country_name TEXT,
    region_name TEXT,
    asn BIGINT CONSTRAINT network_distribution_geo_cache_asn_check CHECK (asn IS NULL OR asn > 0),
    provider_name TEXT CONSTRAINT network_distribution_geo_cache_provider_name_check CHECK (provider_name IS NULL OR char_length(provider_name) <= 255),
    lookup_provider TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    error_code TEXT CONSTRAINT network_distribution_geo_cache_error_code_check CHECK (error_code IS NULL OR char_length(error_code) <= 64),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT network_distribution_geo_cache_expiry_check CHECK (expires_at >= fetched_at)
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
