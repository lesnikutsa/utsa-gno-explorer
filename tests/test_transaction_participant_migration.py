from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "database/migrations/0006_add_transaction_participants.sql").read_text()
SCHEMA = (ROOT / "database/schema.sql").read_text()


def participant_definition(text):
    return text[text.index("CREATE TABLE transaction_participants"):text.index(");", text.index("CREATE TABLE transaction_participants")) + 2]


def test_migration_is_next_and_schema_columns_match():
    assert [path.name for path in sorted((ROOT / "database/migrations").glob("*.sql"))][-1] == "0006_add_transaction_participants.sql"
    for column in ("block_height", "tx_index", "message_index", "role", "address", "inserted_at"):
        assert column in participant_definition(MIGRATION.replace("IF NOT EXISTS ", ""))
        assert column in participant_definition(SCHEMA)


def test_constraints_foreign_key_and_index_match_requirements():
    for text in (MIGRATION, SCHEMA):
        normalized = re.sub(r"\s+", " ", text)
        assert "CHECK (block_height > 0)" in normalized
        assert "CHECK (message_index BETWEEN 0 AND 19)" in normalized
        assert "CHECK (role IN ('sender', 'recipient'))" in normalized
        assert "PRIMARY KEY (block_height, tx_index, message_index, role, address)" in normalized
        assert "FOREIGN KEY (block_height, tx_index) REFERENCES transactions(block_height, tx_index) ON DELETE CASCADE" in normalized
        assert "(address, block_height DESC, tx_index DESC)" in normalized


def test_backfill_is_bounded_safe_and_grants_are_least_privilege():
    assert "$.messages[0 to 19]" in MIGRATION
    assert "parse_status' = 'parsed'" in MIGRATION and "ELSE '[]'::jsonb" in MIGRATION
    assert "message->>'sender'" in MIGRATION and "message->>'recipient'" in MIGRATION
    backfill = MIGRATION[MIGRATION.index("WITH bounded_messages"):MIGRATION.index("DO $$")]
    for forbidden in ("memo", "arguments", "signature", "decoder", "raw_base64"):
        assert forbidden not in backfill.lower()
    assert "GRANT SELECT ON TABLE transaction_participants TO utsa_gno_api" in MIGRATION
    assert "GRANT SELECT, INSERT, DELETE ON TABLE transaction_participants TO utsa_gno_indexer" in MIGRATION
    assert "GRANT INSERT" not in MIGRATION[MIGRATION.index("utsa_gno_api") - 60:MIGRATION.index("utsa_gno_api") + 100]
    assert "production" not in MIGRATION.lower() and "example.com" not in MIGRATION.lower()
