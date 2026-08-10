from types import SimpleNamespace
from unittest.mock import patch

import pytest

from indexer.database import (
    DatabaseError,
    REALM_CALL_INDEX_LOCK_ID,
    RealmCallCoverageError,
    RealmCallCoverageResult,
    _replace_realm_calls_for_height,
    advance_realm_call_coverage,
    lock_realm_call_index,
)
from indexer.realm_catalog import RealmCallRecord


class Cursor:
    def __init__(self, row=None):
        self.row = row
        self.queries = []
        self.rowcount = 0

    def execute(self, sql, params):
        self.queries.append((" ".join(sql.split()), params))
        self.rowcount = 1

    def fetchone(self):
        return self.row


def transaction(index):
    return {"index": index, "decode_status": "decoded", "payload_summary": None}


def call(path="gno.land/r/demo", index=0, function="Render"):
    return RealmCallRecord(path, index, None, function, 0, None)


def test_shared_lock_uses_exact_constant():
    cursor = Cursor()
    lock_realm_call_index(cursor)
    assert cursor.queries == [("SELECT pg_advisory_xact_lock(%s)", (0x52434C4C494458,))]
    assert REALM_CALL_INDEX_LOCK_ID == 0x52434C4C494458


def test_exact_replacement_multiple_transactions_and_calls():
    cursor = Cursor()
    parsed = SimpleNamespace(height=12, transactions=[transaction(0), transaction(1)])
    with patch("indexer.database.extract_realm_calls", side_effect=[
        (call(index=0), call(index=1)), (call("gno.land/r/other", index=0),)
    ]):
        assert _replace_realm_calls_for_height(cursor, parsed, "dev") == 3
    assert cursor.queries[0][0].startswith("DELETE FROM realm_call_index")
    assert len([sql for sql, _ in cursor.queries if sql.startswith("INSERT INTO")]) == 3
    assert "ON CONFLICT" not in " ".join(sql for sql, _ in cursor.queries)


def test_replacement_with_no_calls_still_deletes_stale_rows():
    cursor = Cursor()
    parsed = SimpleNamespace(height=12, transactions=[transaction(0)])
    with patch("indexer.database.extract_realm_calls", return_value=()):
        assert _replace_realm_calls_for_height(cursor, parsed, "dev") == 0
    assert len(cursor.queries) == 1
    assert cursor.queries[0][0].startswith("DELETE FROM realm_call_index")


def test_changed_call_is_inserted_only_after_height_delete():
    cursor = Cursor()
    parsed = SimpleNamespace(height=12, transactions=[transaction(0)])
    with patch("indexer.database.extract_realm_calls", return_value=(call("gno.land/r/new", function="New"),)):
        _replace_realm_calls_for_height(cursor, parsed, "dev")
    assert cursor.queries[1][1][4:7] == ("gno.land/r/new", None, "New")


def test_duplicate_derived_position_fails_closed():
    cursor = Cursor()
    parsed = SimpleNamespace(height=12, transactions=[transaction(0)])
    with patch("indexer.database.extract_realm_calls", return_value=(call(), call(function="Again"))):
        with pytest.raises(DatabaseError, match="Duplicate"):
            _replace_realm_calls_for_height(cursor, parsed, "dev")


def test_separate_coverage_result_and_absent_state():
    result = advance_realm_call_coverage(Cursor(None), "dev", 10)
    assert type(result) is RealmCallCoverageResult
    assert result == RealmCallCoverageResult(None, None, False)


def test_exact_next_replay_and_empty_call_height_coverage():
    assert advance_realm_call_coverage(Cursor((1, 9)), "dev", 10).advanced
    assert not advance_realm_call_coverage(Cursor((1, 10)), "dev", 10).advanced


def test_coverage_gap_and_malformed_state_fail_closed():
    with pytest.raises(RealmCallCoverageError):
        advance_realm_call_coverage(Cursor((1, 8)), "dev", 10)
    with pytest.raises(RealmCallCoverageError, match="Incompatible"):
        advance_realm_call_coverage(Cursor((None, 8)), "dev", 9)


def test_schema_contains_exact_pagination_envelope_and_exclusions():
    migration = open("database/migrations/0009_add_realm_call_index.sql").read()
    schema = open("database/schema.sql").read()
    assert migration.strip().startswith("BEGIN;") and migration.strip().endswith("COMMIT;")
    create_pos = schema.find("CREATE TABLE realm_call_index")
    begin_pos = schema.rfind("BEGIN;", 0, create_pos)
    commit_pos = schema.find("COMMIT;", create_pos)
    assert create_pos >= 0
    assert begin_pos >= 0
    assert commit_pos >= 0
    assert begin_pos < create_pos < commit_pos
    assert "(chain_id, path, block_height DESC, tx_index DESC, message_index DESC)" in migration
    assert "ON DELETE CASCADE" in migration
    for excluded in ("raw_result", "error_text", "gas_used", "tx_hash_hex"):
        assert excluded not in migration


def test_live_writer_locks_before_call_replacement_and_checkpoint():
    from indexer.database import write_height_cursor

    cursor = Cursor()
    parsed = SimpleNamespace(height=12)
    order = []

    def record(name):
        return lambda *args, **kwargs: order.append(name)

    with patch("indexer.database.get_checkpoint_cursor", return_value=11), \
         patch("indexer.database._verify_finalized_conflicts", side_effect=record("conflicts")), \
         patch("indexer.database._upsert_block", side_effect=record("block")), \
         patch("indexer.database._upsert_transactions", side_effect=record("transactions")), \
         patch("indexer.database._replace_realm_calls_for_height", side_effect=record("calls")), \
         patch("indexer.database._upsert_realm_catalog", side_effect=record("catalog")), \
         patch("indexer.database.advance_realm_call_coverage", side_effect=record("call_coverage")), \
         patch("indexer.database.advance_realm_activity_coverage", side_effect=record("activity")), \
         patch("indexer.database._upsert_validators_and_members", side_effect=record("validators")), \
         patch("indexer.database._upsert_signatures", side_effect=record("signatures")), \
         patch("indexer.database._advance_checkpoint", side_effect=record("checkpoint")):
        write_height_cursor(cursor, parsed, "dev", 12, None)

    assert cursor.queries[0][0] == "SELECT pg_advisory_xact_lock(%s)"
    assert order.index("calls") < order.index("call_coverage") < order.index("checkpoint")
