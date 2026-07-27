import copy
from pathlib import Path
from scripts import init_database


def test_governance_catalog_is_final_and_independent():
    assert init_database.FINAL_SCHEMA_EXPECTATIONS["tables"] - init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS["tables"] == {"governance_proposals", "governance_votes", "governance_sync_state"}
    governance = [item for item in init_database.FINAL_SCHEMA_EXPECTATIONS["foreign_keys"] if item[0].startswith("governance_")]
    assert governance == [("governance_votes", ("chain_id", "realm_path", "proposal_id"), "governance_proposals", ("chain_id", "realm_path", "proposal_id"), "c")]


def test_pre_governance_expectations_are_a_deep_snapshot():
    before = copy.deepcopy(init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS)
    init_database.EXPECTED_TABLES.add("temporary_test_table")
    try:
        assert init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS == before
    finally:
        init_database.EXPECTED_TABLES.remove("temporary_test_table")


def test_schema_and_migration_contract():
    schema = Path("database/schema.sql").read_text()
    migration = Path("database/migrations/0004_add_governance_persistence.sql").read_text()
    for table in ("governance_proposals", "governance_votes", "governance_sync_state"):
        assert f"CREATE TABLE {table}" in schema and f"CREATE TABLE {table}" in migration
    assert "BEGIN;" not in migration.upper() and "COMMIT;" not in migration.upper()
    required = "proposal_count > 0 AND first_proposal_id IS NOT NULL AND latest_proposal_id IS NOT NULL"
    assert required in schema and required in migration
    assert "proposal_count = 0 AND first_proposal_id IS NULL AND latest_proposal_id IS NULL AND page_count >= 1" in schema
