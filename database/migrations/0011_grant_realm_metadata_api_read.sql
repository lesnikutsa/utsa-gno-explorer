BEGIN;

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='utsa_gno_api') THEN
  GRANT SELECT ON realm_metadata,realm_metadata_files,realm_metadata_imports TO utsa_gno_api;
 END IF;
END $$;

COMMIT;
