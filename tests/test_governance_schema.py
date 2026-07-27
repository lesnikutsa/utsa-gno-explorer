from pathlib import Path
from scripts import init_database

def test_governance_catalog_is_final_and_independent():
    assert init_database.FINAL_SCHEMA_EXPECTATIONS["tables"] - init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS["tables"] == {"governance_proposals","governance_votes","governance_sync_state"}
    foreign=init_database.FINAL_SCHEMA_EXPECTATIONS["foreign_keys"]
    governance=[item for item in foreign if item[0].startswith("governance_")]
    assert governance == [("governance_votes",("chain_id","realm_path","proposal_id"),"governance_proposals",("chain_id","realm_path","proposal_id"),"c")]

def test_schema_and_transactional_migration_contain_governance():
    schema=Path("database/schema.sql").read_text(); migration=Path("database/migrations/0004_add_governance_persistence.sql").read_text()
    for table in ("governance_proposals","governance_votes","governance_sync_state"):
        assert f"CREATE TABLE {table}" in schema and f"CREATE TABLE {table}" in migration
    assert migration.startswith("BEGIN;") and migration.rstrip().endswith("COMMIT;")
