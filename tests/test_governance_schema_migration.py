from pathlib import Path
from unittest.mock import Mock
import pytest
from scripts import migrate_governance_schema as migration


class Cursor:
    def __init__(self): self.executed = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): self.executed.append((sql, params))


class Connection:
    def __init__(self): self.value = Cursor(); self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self.value
    def commit(self): self.commits += 1


def connect_for(connection): return lambda _: connection


def test_empty_database_rejected(monkeypatch):
    connection = Connection(); monkeypatch.setattr(migration, "fetch_schema_snapshot", lambda _: {"tables": set()})
    with pytest.raises(RuntimeError, match="empty public schema"):
        migration.migrate("postgresql://redacted", connect=connect_for(connection))
    assert connection.commits == 0


def test_exact_pre_governance_applies_and_commits_after_validation(monkeypatch, tmp_path):
    connection = Connection(); sql = tmp_path / "migration.sql"; sql.write_text("CREATE TABLE marker(value integer);")
    snapshots = iter([{"tables": {"blocks"}}, {"tables": migration.TABLES | {"blocks"}}])
    monkeypatch.setattr(migration, "fetch_schema_snapshot", lambda _: next(snapshots))
    pre = Mock(); final = Mock(); monkeypatch.setattr(migration, "validate_schema_stage", pre); monkeypatch.setattr(migration, "validate_schema_snapshot", final)
    assert migration.migrate("postgresql://redacted", sql, connect_for(connection)) == "applied"
    pre.assert_called_once(); final.assert_called_once(); assert connection.commits == 1
    assert connection.value.executed == [("CREATE TABLE marker(value integer);", None)]


def test_post_validation_failure_does_not_commit(monkeypatch, tmp_path):
    connection = Connection(); sql = tmp_path / "migration.sql"; sql.write_text("CREATE TABLE marker(value integer);")
    snapshots = iter([{"tables": {"blocks"}}, {"tables": migration.TABLES | {"blocks"}}])
    monkeypatch.setattr(migration, "fetch_schema_snapshot", lambda _: next(snapshots))
    monkeypatch.setattr(migration, "validate_schema_stage", Mock())
    monkeypatch.setattr(migration, "validate_schema_snapshot", Mock(side_effect=RuntimeError("bad target")))
    with pytest.raises(RuntimeError, match="bad target"):
        migration.migrate("postgresql://redacted", sql, connect_for(connection))
    assert connection.commits == 0


@pytest.mark.parametrize("present", [{"governance_proposals"}, {"governance_proposals", "governance_votes"}])
def test_partial_governance_schema_rejected(monkeypatch, present):
    connection = Connection(); monkeypatch.setattr(migration, "fetch_schema_snapshot", lambda _: {"tables": present})
    with pytest.raises(RuntimeError, match="partial"):
        migration.migrate("postgresql://redacted", connect=connect_for(connection))
    assert connection.commits == 0


def test_final_schema_is_already_compatible(monkeypatch):
    connection = Connection(); monkeypatch.setattr(migration, "fetch_schema_snapshot", lambda _: {"tables": migration.TABLES})
    validate = Mock(); monkeypatch.setattr(migration, "validate_schema_snapshot", validate)
    assert migration.migrate("postgresql://redacted", connect=connect_for(connection)) == "already-compatible"
    validate.assert_called_once(); assert connection.commits == 1 and not connection.value.executed


def test_cli_redacts_database_url(monkeypatch, capsys):
    secret = "postgresql://user:password@db/name"; monkeypatch.setenv("DATABASE_URL", secret)
    monkeypatch.setattr(migration, "migrate", Mock(side_effect=RuntimeError(secret)))
    assert migration.main([]) == 1
    error = capsys.readouterr().err
    assert secret not in error and "password" not in error and "Traceback" not in error
