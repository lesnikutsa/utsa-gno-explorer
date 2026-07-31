import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import init_database


def snapshot(expectations):
    return copy.deepcopy({
        "tables": expectations["tables"], "columns": expectations["columns"],
        "primary_keys": expectations["primary_keys"],
        "unique_constraints": expectations["unique_constraints"],
        "foreign_keys": expectations["foreign_keys"],
        "check_constraints": expectations["check_constraints"],
        "indexes": expectations["indexes"],
    })


def test_participant_authoritative_contract_is_exact():
    table = "transaction_participants"
    assert table in init_database.EXPECTED_TABLES
    assert init_database.EXPECTED_COLUMNS[table] == {
        "block_height": ("bigint", "NO", "", None),
        "tx_index": ("integer", "NO", "", None),
        "message_index": ("integer", "NO", "", None),
        "role": ("text", "NO", "", None),
        "address": ("text", "NO", "", None),
        "inserted_at": ("timestamp with time zone", "NO", "", "now()"),
    }
    assert init_database.EXPECTED_PRIMARY_KEYS[table] == ("block_height", "tx_index", "message_index", "role", "address")
    assert (table, ("block_height", "tx_index"), "transactions", ("block_height", "tx_index"), "c") in init_database.EXPECTED_FOREIGN_KEYS
    assert init_database.EXPECTED_INDEXES["transaction_participants_address_position_idx"][2] == (("address", "ASC"), ("block_height", "DESC"), ("tx_index", "DESC"))


def test_execution_result_authoritative_contract_is_exact():
    table = "transaction_execution_results"
    assert table not in init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS["tables"]
    assert table in init_database.FINAL_SCHEMA_EXPECTATIONS["tables"]
    assert init_database.EXPECTED_PRIMARY_KEYS[table] == ("block_height", "tx_index")
    assert (table, ("block_height", "tx_index"), "transactions", ("block_height", "tx_index"), "c") in init_database.EXPECTED_FOREIGN_KEYS
    assert (table, ("source_rpc_endpoint_id",), "rpc_endpoints", ("id",), "n") in init_database.EXPECTED_FOREIGN_KEYS
    assert not any(index[0] == table for index in init_database.EXPECTED_INDEXES.values())


def test_execution_result_migration_envelope_is_safe():
    body = init_database.migration_body_for_outer_transaction(
        init_database.EXECUTION_RESULT_MIGRATION.read_text()
    )
    assert "CREATE TABLE transaction_execution_results" in body
    assert not body.lstrip().upper().startswith("BEGIN;")
    assert not body.rstrip().upper().endswith("COMMIT;")


def test_pre_0007_stage_runs_only_execution_result_migration():
    connection = Connection(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS["tables"])
    snapshots = [
        snapshot(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS),
        snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS),
    ]
    with patch.object(init_database, "fetch_schema_snapshot", side_effect=snapshots):
        init_database.initialize_or_validate(
            "postgresql://example.invalid/db", connect=lambda _: connection
        )
    sql = "\n".join(statement for statement, _ in connection.cursor_value.executed)
    assert "CREATE TABLE transaction_execution_results" in sql
    assert "CREATE TABLE IF NOT EXISTS transaction_participants" not in sql
    assert connection.commits == 1


def test_checks_and_privilege_contract_are_registered():
    checks = init_database.EXPECTED_CHECKS
    for name in ("block_height", "tx_index", "message_index", "role", "address"):
        assert f"transaction_participants_{name}_check" in checks
    assert init_database.EXPECTED_TABLE_PRIVILEGES == {
        "utsa_gno_api": {
            "transaction_participants": {"SELECT"},
            "transaction_execution_results": {"SELECT"},
        },
        "utsa_gno_indexer": {
            "transaction_participants": {"SELECT", "INSERT", "DELETE"},
            "transaction_execution_results": {"SELECT", "INSERT", "UPDATE"},
        },
    }


def test_final_snapshot_accepts_participants_and_rejects_schema_drift():
    final = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    init_database.validate_schema_snapshot(final)
    without = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    without["tables"].remove("transaction_participants")
    with pytest.raises(init_database.SchemaCompatibilityError, match="missing expected tables"):
        init_database.validate_schema_snapshot(without)
    extra = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    extra["columns"]["transaction_participants"]["unexpected"] = ("text", "YES", "", None)
    with pytest.raises(init_database.SchemaCompatibilityError, match="incompatible column set"):
        init_database.validate_schema_snapshot(extra)
    missing_check = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    missing_check["check_constraints"].pop("transaction_participants_role_check")
    with pytest.raises(init_database.SchemaCompatibilityError, match="check constraint set"):
        init_database.validate_schema_snapshot(missing_check)


def test_wrong_index_order_and_delete_action_fail_closed():
    wrong_index = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    value = wrong_index["indexes"]["transaction_participants_address_position_idx"]
    wrong_index["indexes"]["transaction_participants_address_position_idx"] = (value[0], value[1], tuple(reversed(value[2])), value[3])
    with pytest.raises(init_database.SchemaCompatibilityError, match="incompatible index"):
        init_database.validate_schema_snapshot(wrong_index)
    wrong_fk = snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)
    fk = next(item for item in wrong_fk["foreign_keys"] if item[0] == "transaction_participants")
    wrong_fk["foreign_keys"].remove(fk)
    wrong_fk["foreign_keys"].add((*fk[:-1], "r"))
    with pytest.raises(init_database.SchemaCompatibilityError, match="incompatible foreign keys"):
        init_database.validate_schema_snapshot(wrong_fk)


class Cursor:
    def __init__(self, existing):
        self.existing, self.executed, self._last = existing, [], None
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.executed.append((str(sql), params)); self._last = str(sql)
    def fetchall(self): return [(table,) for table in self.existing]
    def fetchone(self): return (False,)


class Connection:
    def __init__(self, existing): self.cursor_value, self.commits = Cursor(existing), 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self.cursor_value
    def commit(self): self.commits += 1


def test_migration_envelope_loader_accepts_0006_without_returning_control_statements():
    body = init_database.migration_body_for_outer_transaction(init_database.PARTICIPANT_MIGRATION.read_text())
    assert "CREATE TABLE IF NOT EXISTS transaction_participants" in body
    assert not body.lstrip().upper().startswith("BEGIN;")
    assert not body.rstrip().upper().endswith("COMMIT;")


@pytest.mark.parametrize("sql", [
    "BEGIN;\nSELECT 1;\nCOMMIT;\nCOMMIT;",
    "BEGIN;\nSELECT 1; COMMIT;\nCOMMIT;",
    "BEGIN;\nSELECT 1;\nBEGIN;\nCOMMIT;",
    "BEGIN;\nROLLBACK;\nCOMMIT;",
    "SELECT 1;\nCOMMIT;",
    "BEGIN;\nSELECT 1;",
])
def test_migration_envelope_loader_rejects_invalid_control(sql):
    with pytest.raises(init_database.SchemaCompatibilityError):
        init_database.migration_body_for_outer_transaction(sql)


def test_pre_0006_stage_runs_migration_before_final_verification():
    connection = Connection(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"])
    snapshots = [snapshot(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS), snapshot(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS), snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)]
    with patch.object(init_database, "fetch_schema_snapshot", side_effect=snapshots) as fetch:
        init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    migration_calls = [sql for sql, _ in connection.cursor_value.executed if "CREATE TABLE IF NOT EXISTS transaction_participants" in sql]
    execution_calls = [sql for sql, _ in connection.cursor_value.executed if "CREATE TABLE transaction_execution_results" in sql]
    assert len(migration_calls) == 1
    assert len(execution_calls) == 1
    assert fetch.call_count == 3 and connection.commits == 1
    executed = migration_calls[0].strip().upper()
    assert not executed.startswith("BEGIN;") and not executed.endswith("COMMIT;")


def test_post_0006_stage_does_not_reapply_migration():
    connection = Connection(init_database.FINAL_SCHEMA_EXPECTATIONS["tables"])
    with patch.object(init_database, "fetch_schema_snapshot", return_value=snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)):
        init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    assert not any("CREATE TABLE IF NOT EXISTS transaction_participants" in sql for sql, _ in connection.cursor_value.executed)


def test_migration_failure_does_not_commit_or_report_ready():
    class FailingCursor(Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "CREATE TABLE IF NOT EXISTS transaction_participants" in str(sql):
                raise RuntimeError("bounded migration failure")
    connection = Connection(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"])
    connection.cursor_value = FailingCursor(connection.cursor_value.existing)
    with patch.object(init_database, "fetch_schema_snapshot", return_value=snapshot(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS)):
        with pytest.raises(RuntimeError, match="bounded migration failure"):
            init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    assert connection.commits == 0

class PrivilegeCursor:
    def __init__(self, grants): self.grants, self.params = grants, None
    def execute(self, sql, params=None): self.params = params
    def fetchone(self):
        if len(self.params) == 1: return (self.params[0] in self.grants,)
        role, table, privilege = self.params
        table = table.removeprefix("public.")
        return (privilege in self.grants.get(role, {}).get(table, set()),)


def test_participant_privilege_validation_accepts_least_privilege():
    init_database.validate_participant_privileges(PrivilegeCursor({
        "utsa_gno_api": {
            "transaction_participants": {"SELECT"},
            "transaction_execution_results": {"SELECT"},
        },
        "utsa_gno_indexer": {
            "transaction_participants": {"SELECT", "INSERT", "DELETE"},
            "transaction_execution_results": {"SELECT", "INSERT", "UPDATE"},
        },
    }))


def test_api_writes_and_missing_indexer_grants_fail_closed():
    with pytest.raises(init_database.SchemaCompatibilityError, match="API role"):
        init_database.validate_participant_privileges(PrivilegeCursor({
            "utsa_gno_api": {
                "transaction_participants": {"SELECT", "INSERT"},
                "transaction_execution_results": {"SELECT"},
            },
            "utsa_gno_indexer": {
                "transaction_participants": {"SELECT", "INSERT", "DELETE"},
                "transaction_execution_results": {"SELECT", "INSERT", "UPDATE"},
            },
        }))
    with pytest.raises(init_database.SchemaCompatibilityError, match="Indexer role"):
        init_database.validate_participant_privileges(PrivilegeCursor({
            "utsa_gno_api": {
                "transaction_participants": {"SELECT"},
                "transaction_execution_results": {"SELECT"},
            },
            "utsa_gno_indexer": {
                "transaction_participants": {"SELECT", "INSERT"},
                "transaction_execution_results": {"SELECT", "INSERT", "UPDATE"},
            },
        }))


def test_final_schema_failure_occurs_after_body_and_before_commit():
    connection = Connection(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"])
    snapshots = [snapshot(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS), snapshot(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS), snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)]
    validations = []
    def validate(value, expectations=None):
        validations.append(expectations)
        if len(validations) == 3:
            raise init_database.SchemaCompatibilityError("forced final verification failure")
    with patch.object(init_database, "fetch_schema_snapshot", side_effect=snapshots), patch.object(init_database, "validate_schema_snapshot", side_effect=validate):
        with pytest.raises(init_database.SchemaCompatibilityError, match="forced final"):
            init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    assert any("CREATE TABLE IF NOT EXISTS transaction_participants" in sql for sql, _ in connection.cursor_value.executed)
    assert connection.commits == 0


def test_privilege_failure_occurs_before_single_commit():
    connection = Connection(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"])
    snapshots = [snapshot(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS), snapshot(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS), snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)]
    with patch.object(init_database, "fetch_schema_snapshot", side_effect=snapshots), patch.object(
        init_database, "validate_participant_privileges",
        side_effect=init_database.SchemaCompatibilityError("forced privilege failure"),
    ) as privileges:
        with pytest.raises(init_database.SchemaCompatibilityError, match="forced privilege"):
            init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    privileges.assert_called_once_with(connection.cursor_value)
    assert connection.commits == 0


def test_success_verifies_privileges_before_exactly_one_commit():
    events = []
    class OrderedConnection(Connection):
        def commit(self):
            events.append("commit")
            super().commit()
    connection = OrderedConnection(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS["tables"])
    snapshots = [snapshot(init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS), snapshot(init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS), snapshot(init_database.FINAL_SCHEMA_EXPECTATIONS)]
    with patch.object(init_database, "fetch_schema_snapshot", side_effect=snapshots), patch.object(
        init_database, "validate_participant_privileges", side_effect=lambda cursor: events.append("privileges"),
    ):
        init_database.initialize_or_validate("postgresql://example.invalid/db", connect=lambda _: connection)
    assert events == ["privileges", "commit"]
    assert connection.commits == 1
