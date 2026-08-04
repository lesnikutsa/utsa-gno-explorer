from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import check_realm_activity_coverage as check


class Cursor:
    def __init__(self, state): self.state, self.row, self.queries = state, None, []
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def execute(self, sql, params=()):
        self.queries.append(sql)
        self.row = self.state.get("coverage") if "realm_catalog_state" in sql else self.state.get("indexer")
    def fetchone(self): return self.row


class Connection:
    def __init__(self, state): self.state, self.cursor_value = state, Cursor(state)
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return self.cursor_value


def invoke(monkeypatch, capsys, state, url="postgresql://user:password@db/test"):
    connection = Connection(state)
    monkeypatch.setattr(check, "load_config", lambda: SimpleNamespace(
        chain_id="topaz-1", database_url=url, rpc_urls=("https://secret.rpc",)))
    monkeypatch.setattr(check, "PostgresDatabase", lambda _: SimpleNamespace(connect=lambda: connection))
    before = deepcopy(state)
    code = check.run()
    return code, capsys.readouterr(), before, state, connection.cursor_value.queries


def state(through=20, indexed=20):
    return {"coverage": (10, through), "indexer": ("topaz-1", indexed)}


def test_aligned_state(monkeypatch, capsys):
    code, output, before, after, queries = invoke(monkeypatch, capsys, state())
    assert code == 0 and "status=aligned" in output.out and before == after
    assert all("UPDATE" not in query.upper() for query in queries)


def test_lag_requires_rebuild_without_writing(monkeypatch, capsys):
    code, output, before, after, _ = invoke(monkeypatch, capsys, state(indexed=25))
    assert code == 0 and "status=rebuild_required" in output.out
    assert "recommended_from_height=10" in output.out and "recommended_through_height=25" in output.out
    assert before == after


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(coverage=None),
    lambda value: value.update(indexer=None),
    lambda value: value.update(coverage=(None, None)),
    lambda value: value.update(coverage=(10, None)),
    lambda value: value.update(indexer=("other-1", 20)),
    lambda value: value.update(coverage=(10, 21)),
])
def test_invalid_state_is_error(monkeypatch, capsys, mutation):
    value = state(); mutation(value)
    code, output, before, after, _ = invoke(monkeypatch, capsys, value)
    assert code != 0 and "status=error" in output.err and before == after


def test_output_does_not_disclose_secrets_or_sql(monkeypatch, capsys):
    url = "postgresql://user:password@db/test"
    _, output, _, _, _ = invoke(monkeypatch, capsys, state(through=21), url)
    combined = output.out + output.err
    for secret in (url, "password", "https://secret.rpc", "SELECT", "realm_catalog_state"):
        assert secret not in combined
