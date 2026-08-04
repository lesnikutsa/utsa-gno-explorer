from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.check_realm_call_index_coverage import run
from scripts.rebuild_realm_call_index import RebuildError, rebuild_cursor


class RebuildCursor:
    def __init__(self, checkpoint=5, blocks=(5, 1, 5), state=None, transactions=()):
        self.fetchone_values = [checkpoint and (checkpoint,), blocks, state]
        self.transactions = list(transactions)
        self.queries = []
        self.rowcount = 1

    def execute(self, sql, params):
        self.queries.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.fetchone_values.pop(0)

    def fetchall(self):
        return self.transactions


def legacy_summary(path="gno.land/r/legacy"):
    return {"parse_status": "parsed", "messages": [
        {"type": "gno.vm.MsgCall", "package_path": path, "function": "Render"}
    ]}


def test_omitted_through_is_resolved_after_shared_lock_and_indexes_legacy():
    cursor = RebuildCursor(transactions=[(5, 0, legacy_summary())])
    count, through = rebuild_cursor(cursor, "dev", 1, None)
    assert (count, through) == (1, 5)
    assert cursor.queries[0][0] == "SELECT pg_advisory_xact_lock(%s)"
    assert "last_finalized_height" in cursor.queries[1][0]
    assert any(params[4] == "gno.land/r/legacy" for sql, params in cursor.queries
               if sql.startswith("INSERT INTO realm_call_index("))


def test_initial_partial_and_lagging_repairs_fail_before_writes():
    initial = RebuildCursor(checkpoint=5, blocks=(3, 1, 3))
    with pytest.raises(RebuildError, match="behind"):
        rebuild_cursor(initial, "dev", 1, 3)
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql, _ in initial.queries)

    lagging = RebuildCursor(checkpoint=5, blocks=(2, 3, 4), state=(1, 2))
    with pytest.raises(RebuildError, match="behind"):
        rebuild_cursor(lagging, "dev", 3, 4)
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql, _ in lagging.queries)


def test_initial_complete_and_healthy_subset_rebuilds_end_at_locked_checkpoint():
    initial = RebuildCursor()
    assert rebuild_cursor(initial, "dev", 1, None) == (0, 5)
    healthy = RebuildCursor(blocks=(2, 2, 3), state=(1, 5))
    assert rebuild_cursor(healthy, "dev", 2, 3) == (0, 3)
    state_write = [params for sql, params in healthy.queries
                   if sql.startswith("INSERT INTO realm_call_index_state")]
    assert state_write == [("dev", 1, 5)]


def test_dry_run_resolves_locked_checkpoint_without_projection_writes():
    cursor = RebuildCursor(transactions=[(5, 0, legacy_summary())])
    assert rebuild_cursor(cursor, "dev", 1, None, dry_run=True) == (1, 5)
    assert not any(sql.startswith(("DELETE", "INSERT")) for sql, _ in cursor.queries)


def test_missing_blocks_beyond_checkpoint_and_separated_ranges_fail_closed():
    with pytest.raises(RebuildError, match="missing local blocks"):
        rebuild_cursor(RebuildCursor(blocks=(4, 1, 5)), "dev", 1, None)
    with pytest.raises(RebuildError, match="exceeds"):
        rebuild_cursor(RebuildCursor(), "dev", 1, 6)
    with pytest.raises(RebuildError, match="separated"):
        rebuild_cursor(RebuildCursor(blocks=(1, 5, 5), state=(1, 3)), "dev", 5, 5)


class InspectorCursor:
    def __init__(self, state, checkpoint, count=0, failure=None):
        self.values = [state, checkpoint, (count,)]
        self.failure = failure

    def execute(self, sql, params):
        if self.failure:
            raise self.failure

    def fetchone(self):
        return self.values.pop(0)


class InspectorConnection:
    def __init__(self, cursor):
        self.value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @contextmanager
    def cursor(self):
        yield self.value


@pytest.mark.parametrize("state,checkpoint,expected", [
    ((1, 5), (5,), 0),
    (None, (5,), 2),
    ((1, 4), (5,), 3),
    ((1, 6), (5,), 3),
    ((1, 5), None, 3),
])
def test_inspector_exit_codes(state, checkpoint, expected, capsys):
    cursor = InspectorCursor(state, checkpoint)
    config = SimpleNamespace(chain_id="dev", database_url="postgresql://user:secret@host/db")
    with patch("scripts.check_realm_call_index_coverage.load_config", return_value=config), \
         patch("scripts.check_realm_call_index_coverage.PostgresDatabase.connect",
               return_value=InspectorConnection(cursor)):
        assert run() == expected
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


def test_inspector_database_failure_is_bounded_and_secret_free(capsys):
    cursor = InspectorCursor(None, None, failure=RuntimeError("postgresql://user:secret@host/db"))
    config = SimpleNamespace(chain_id="dev", database_url="postgresql://user:secret@host/db")
    with patch("scripts.check_realm_call_index_coverage.load_config", return_value=config), \
         patch("scripts.check_realm_call_index_coverage.PostgresDatabase.connect",
               return_value=InspectorConnection(cursor)):
        assert run() == 4
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
