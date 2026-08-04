import pytest

from indexer.database import RealmActivityCoverageError, advance_realm_activity_coverage


class Cursor:
    def __init__(self, state=(1, 10), blocks=()):
        self.state, self.blocks, self.result, self.updated = state, set(blocks), None, False

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        if "FROM realm_catalog_state" in sql and "FOR UPDATE" in sql:
            self.result = self.state
        elif sql.startswith("SELECT count(*), min(height), max(height)"):
            found = sorted(h for h in self.blocks if params[0] <= h <= params[1])
            self.result = (len(found), min(found) if found else None, max(found) if found else None)
        elif sql.startswith("UPDATE realm_catalog_state"):
            self.state, self.updated, self.result = (self.state[0], params[0]), True, None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result


@pytest.mark.parametrize("height", [0, -1, True, 1.5, "1", None])
def test_invalid_height_rejected(height):
    with pytest.raises(ValueError):
        advance_realm_activity_coverage(Cursor(), "topaz-1", height)


@pytest.mark.parametrize("chain_id", ["", "  ", None, 1])
def test_invalid_chain_rejected(chain_id):
    with pytest.raises(ValueError):
        advance_realm_activity_coverage(Cursor(), chain_id, 11)


def test_missing_and_uninitialized_state_are_noops():
    assert not advance_realm_activity_coverage(Cursor(None), "topaz-1", 11).advanced
    assert not advance_realm_activity_coverage(Cursor((None, None)), "topaz-1", 11).advanced


@pytest.mark.parametrize("state", [(None, 10), (1, None)])
def test_partial_range_fails_closed(state):
    with pytest.raises(RealmActivityCoverageError, match="Incompatible"):
        advance_realm_activity_coverage(Cursor(state), "topaz-1", 11)


def test_next_height_advances_without_range_query():
    cursor = Cursor()
    result = advance_realm_activity_coverage(cursor, "topaz-1", 11)
    assert (result.previous_through_height, result.new_through_height, result.advanced, result.caught_up) == (10, 11, True, False)


@pytest.mark.parametrize("height", [10, 9])
def test_replay_or_lower_height_is_an_idempotent_noop(height):
    cursor = Cursor()
    result = advance_realm_activity_coverage(cursor, "topaz-1", height)
    assert result.new_through_height == 10 and not result.advanced and not cursor.updated


def test_contiguous_lag_catches_up():
    result = advance_realm_activity_coverage(Cursor(blocks=range(11, 15)), "topaz-1", 14)
    assert (result.new_through_height, result.caught_up) == (14, True)


def test_lag_gap_fails_without_update():
    cursor = Cursor(blocks=(11, 13, 14))
    with pytest.raises(RealmActivityCoverageError, match="observed count 3"):
        advance_realm_activity_coverage(cursor, "topaz-1", 14)
    assert cursor.state == (1, 10) and not cursor.updated
