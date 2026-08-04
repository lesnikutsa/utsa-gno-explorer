from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import repair_realm_activity_coverage as repair


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        state = self.connection.working
        if "FROM realm_catalog_state" in sql:
            self.row = state.get("coverage")
        elif "FROM indexer_state" in sql:
            self.row = state.get("indexer")
        elif sql.startswith("SELECT count(*) FROM blocks"):
            self.row = (sum(params[0] <= height <= params[1] for height in state["blocks"]),)
        elif sql.startswith("SELECT count(*), min(height), max(height)"):
            found = sorted(height for height in state["blocks"] if params[0] <= height <= params[1])
            self.row = (len(found), min(found) if found else None, max(found) if found else None)
        elif sql.startswith("UPDATE realm_catalog_state"):
            state["coverage"] = (state["coverage"][0], params[0])
            self.row = None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, state):
        self.persistent = state
        self.working = deepcopy(state)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.persistent.clear()
        self.persistent.update(deepcopy(self.working))

    def rollback(self):
        self.working = deepcopy(self.persistent)


def invoke(monkeypatch, capsys, state, apply=False, database_url="postgresql://user:password@db/test"):
    connection = FakeConnection(state)
    monkeypatch.setattr(repair, "load_config", lambda: SimpleNamespace(
        chain_id="topaz-1", database_url=database_url, rpc_urls=("https://secret.rpc",)))
    monkeypatch.setattr(repair, "PostgresDatabase", lambda _: SimpleNamespace(connect=lambda: connection))
    code = repair.run(apply)
    return code, capsys.readouterr(), state


def state(through=20, indexed=25, blocks=range(21, 26)):
    return {"coverage": (10, through), "indexer": ("topaz-1", indexed),
            "blocks": set(blocks), "counter": 7}


def test_default_dry_run_is_ready_and_rolls_back(monkeypatch, capsys):
    original = state()
    before = deepcopy(original)
    code, output, persisted = invoke(monkeypatch, capsys, original)
    assert code == 0 and "status=ready" in output.out and "missing_block_count=0" in output.out
    assert persisted == before


def test_apply_changes_only_through_height_and_uses_shared_helper(monkeypatch, capsys):
    original = state()
    shared = Mock(wraps=repair.advance_realm_activity_coverage)
    monkeypatch.setattr(repair, "advance_realm_activity_coverage", shared)
    code, output, persisted = invoke(monkeypatch, capsys, original, apply=True)
    assert code == 0 and "status=success" in output.out
    assert persisted == {**state(), "coverage": (10, 25)}
    shared.assert_called_once()


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(blocks={21, 22, 24, 25}),
    lambda value: value.update(coverage=None),
    lambda value: value.update(indexer=None),
    lambda value: value.update(coverage=(None, None)),
    lambda value: value.update(indexer=("other-1", 25)),
])
def test_invalid_state_fails_and_rolls_back(monkeypatch, capsys, mutation):
    original = state()
    mutation(original)
    before = deepcopy(original)
    code, output, persisted = invoke(monkeypatch, capsys, original)
    assert code != 0 and persisted == before and "status=ready" not in output.out


def test_coverage_ahead_of_indexer_fails_closed(monkeypatch, capsys):
    original = state(through=20, indexed=19, blocks=())
    before = deepcopy(original)
    code, output, persisted = invoke(monkeypatch, capsys, original)
    assert code != 0 and persisted == before and "status=ready" not in output.out


def test_equal_coverage_is_idempotently_ready(monkeypatch, capsys):
    code, output, _ = invoke(monkeypatch, capsys, state(through=20, indexed=20, blocks=()))
    assert code == 0 and "status=ready" in output.out


def test_errors_do_not_disclose_configuration_or_sql(monkeypatch, capsys):
    url = "postgresql://user:password@db/test"
    code, output, _ = invoke(monkeypatch, capsys, state(through=20, indexed=19), database_url=url)
    combined = output.out + output.err
    assert code != 0
    for secret in (url, "password", "https://secret.rpc", "SELECT", "realm_catalog_state"):
        assert secret not in combined
