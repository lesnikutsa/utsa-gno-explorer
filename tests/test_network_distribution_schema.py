from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_schema_and_migration_constraints_match():
 schema=(ROOT/'database/schema.sql').read_text(); migration=(ROOT/'database/migrations/0003_add_network_distribution.sql').read_text()
 for text in [schema,migration]:
  for fragment in ['ip INET PRIMARY KEY','jsonb_typeof(regions)', 'ON DELETE CASCADE','ON DELETE SET NULL','network_distribution_geo_cache_state_check','char_length(lookup_provider) BETWEEN 1 AND 128','network_distribution_snapshots_chain_latest_idx']:
   assert fragment in text
 assert migration.strip() in schema
