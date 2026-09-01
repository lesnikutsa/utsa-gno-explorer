from datetime import datetime, timedelta, timezone

from api.cosmos.validators import aggregate_commit, category, miss_metrics, nearest_snapshot


def test_categories_keep_jailed_separate():
    assert category({"status": "BOND_STATUS_BONDED", "jailed": False}) == "active"
    assert category({"status": "BOND_STATUS_UNBONDED", "jailed": False}) == "inactive"
    assert category({"status": "BOND_STATUS_BONDED", "jailed": True}) == "jailed"


def test_slashing_budget_signed_percent_and_eta():
    value = miss_metrics(443, 10000, "0.05", 5.5)
    assert value == {"signed_percent": 95.57, "allowed_misses": 9500,
                     "remaining_budget": 9057, "jail_eta_seconds": 49814}
    assert miss_metrics(443, 10000, "0.05", None)["jail_eta_seconds"] is None


def test_commit_aggregation_is_block_centric_and_unknown_safe():
    strip = {}
    active = {"AA", "BB"}
    aggregate_commit(strip, active, {"signatures": [{"validator_address": "aa", "block_id_flag": 2}]})
    aggregate_commit(strip, active, None)
    assert strip == {"AA": ["signed", "unknown"], "BB": ["unknown", "unknown"]}
    assert "CC" not in strip  # inactive validators never receive false misses


def test_snapshot_requires_complete_24_hour_history():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert nearest_snapshot([(now - timedelta(hours=23), {"v": 1})], now) is None
    assert nearest_snapshot([(now - timedelta(hours=24, minutes=5), {"v": 2})], now) == {"v": 2}


def test_explicit_miss_and_joined_later_are_conservative():
    strip = {}
    aggregate_commit(strip, {"AA", "NEW"}, {"signatures": [
        {"validator_address": "AA", "block_id_flag": 1},
    ]})
    assert strip == {"AA": ["missed"], "NEW": ["unknown"]}


def test_signing_height_range_caps_large_idle_gap():
    from api.cosmos.validators import signing_height_range
    assert list(signing_height_range(100, 100_000)) == list(range(99_951, 100_001))
    assert list(signing_height_range(100, 103)) == [101, 102, 103]
