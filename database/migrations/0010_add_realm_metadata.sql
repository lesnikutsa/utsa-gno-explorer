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
 CONSTRAINT realm_metadata_refresh_state_completion_check CHECK (((run_status='running' AND completed_at IS NULL) OR (run_status<>'running' AND completed_at IS NOT NULL)) AND (completed_at IS NULL OR completed_at>=started_at)),
 CONSTRAINT realm_metadata_refresh_state_success_check CHECK ((last_successful_height IS NULL)=(last_successful_at IS NULL) AND (last_successful_height IS NULL OR (last_successful_height>0 AND last_successful_height<=observed_height)))
);

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_indexer') THEN
  GRANT SELECT,INSERT,UPDATE,DELETE ON realm_metadata,realm_metadata_files,realm_metadata_imports,realm_metadata_refresh_state TO utsa_gno_indexer;
 END IF;
END $$;

COMMIT;
