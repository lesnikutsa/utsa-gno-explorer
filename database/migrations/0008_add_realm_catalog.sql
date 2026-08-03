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
