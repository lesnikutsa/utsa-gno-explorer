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


def test_commit_aggregation_is_block_centric_and_unknown_safe():
    strip = {}
    active = {"AA", "BB"}
    aggregate_commit(strip, active, {"signatures": [{"validator_address": "aa", "block_id_flag": 2}]})
    aggregate_commit(strip, active, None)
    assert strip == {"AA": ["signed", "unknown"], "BB": ["missed", "unknown"]}
    assert "CC" not in strip  # inactive validators never receive false misses


def test_snapshot_requires_complete_24_hour_history():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert nearest_snapshot([(now - timedelta(hours=23), {"v": 1})], now) is None
    assert nearest_snapshot([(now - timedelta(hours=24, minutes=5), {"v": 2})], now) == {"v": 2}
