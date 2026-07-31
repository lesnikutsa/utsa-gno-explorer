import copy
from pathlib import Path
import pytest
from scripts import init_database


@pytest.mark.parametrize("between,expanded", [
    (
        "CHECK (char_length(chain_id) BETWEEN 1 AND 128)",
        "CHECK ((char_length(chain_id) >= 1) AND (char_length(chain_id) <= 128))",
    ),
    (
        "CHECK (page_count BETWEEN 1 AND 100)",
        "CHECK ((page_count >= 1) AND (page_count <= 100))",
    ),
    (
        """CHECK (
            (yes_percent IS NULL OR yes_percent BETWEEN 0 AND 100)
            AND (no_percent IS NULL OR no_percent BETWEEN 0 AND 100)
            AND (abstain_percent IS NULL OR abstain_percent BETWEEN 0 AND 100)
        )""",
        """CHECK (
            ((yes_percent IS NULL) OR ((yes_percent >= 0) AND (yes_percent <= 100)))
            AND ((no_percent IS NULL) OR ((no_percent >= 0) AND (no_percent <= 100)))
            AND ((abstain_percent IS NULL) OR ((abstain_percent >= 0) AND (abstain_percent <= 100)))
        )""",
    ),
])
def test_norm_treats_numeric_between_as_postgres_expanded_bounds(between, expanded):
    assert init_database._norm(between) == init_database._norm(expanded)


def test_norm_keeps_different_or_exclusive_bounds_distinct():
    expected = init_database._norm("CHECK (page_count BETWEEN 1 AND 128)")
    assert expected != init_database._norm("CHECK (page_count >= 0 AND page_count <= 128)")
    assert expected != init_database._norm("CHECK (page_count >= 1 AND page_count < 128)")


def test_norm_does_not_rewrite_string_between_expression():
    value = "CHECK (label BETWEEN 'a' AND 'z')"
    assert init_database._normalize_numeric_between(value.lower()) == value.lower()


def test_norm_preserves_existing_cast_any_parentheses_and_boolean_rules():
    assert init_database._norm("CHECK ((value)::integer >= (1)::integer)") == "value >= 1"
    assert init_database._norm("CHECK (status = ANY (ARRAY['a'::text, 'b'::text]))") == init_database._norm("CHECK (status IN ('a', 'b'))")
    assert init_database._norm("CHECK (((enabled = true) AND (healthy = true)) OR (enabled = false))") == "(enabled = true and healthy = true) or enabled = false"


def test_governance_catalog_is_final_and_independent():
    assert init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"] - init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS["tables"] == {"governance_proposals", "governance_votes", "governance_sync_state"}
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
