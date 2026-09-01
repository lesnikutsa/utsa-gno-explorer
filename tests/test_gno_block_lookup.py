from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.gno_block_lookup import (GnoBlockLookupUnavailable,
                                  _normalize_timestamp_fraction, _timestamp,
                                  clear_gno_eta_cache, lookup_future_block)
from scripts.inspect_rpc import RpcError


CHAIN = "test-chain"
LATEST = datetime(2026, 8, 31, tzinfo=timezone.utc)
REAL_GNO_TIME = "2026-08-31T22:31:32.202247944"


def status(height=2_000, chain=CHAIN):
    return {"result": {"node_info": {"network": chain}, "sync_info": {
        "latest_block_height": str(height), "catching_up": False}}}


def block(height, seconds=5, chain=CHAIN, returned_height=None):
    timestamp = LATEST - timedelta(seconds=(2_000 - height) * seconds)
    return {"result": {"block": {"header": {"chain_id": chain,
        "height": str(returned_height or height), "time": timestamp.isoformat()}}}}


class Client:
    def __init__(self, available=(2000, 1000, 1500, 1800, 1920), seconds=5,
                 latest_chain=CHAIN, latest_height=2_000, latest_time=LATEST):
        self.available = set(available)
        self.seconds = seconds
        self.latest_chain = latest_chain
        self.latest_height = latest_height
        self.latest_time = latest_time
        self.calls = []

    def get(self, method, height):
        self.calls.append((method, height))
        if height not in self.available:
            raise OSError("pruned")
        if height == 2_000:
            timestamp = self.latest_time.isoformat() if isinstance(self.latest_time, datetime) else self.latest_time
            return {"result": {"block": {"header": {"chain_id": self.latest_chain,
                "height": str(self.latest_height), "time": timestamp}}}}
        return block(height, self.seconds)

    def close(self):
        pass


def config():
    return SimpleNamespace(rpc_urls=("https://rpc.example",), chain_id=CHAIN,
                           rpc_max_height_lag=10, account_rpc_timeout_seconds=3)


def run(target, client, *, payload=None, clock=lambda: 0, wall_clock=lambda: LATEST):
    probe = SimpleNamespace(latest_height=2_000, status_payload=payload or status(),
                            client=client, healthy=True)
    with patch("api.gno_block_lookup.probe_rpc_endpoints", return_value=[probe]), \
         patch("api.gno_block_lookup.suitable_rpc_probes", return_value=[probe]):
        return lookup_future_block(target, config(), clock=clock, wall_clock=wall_clock)


@pytest.fixture(autouse=True)
def empty_cache():
    clear_gno_eta_cache()


@pytest.mark.parametrize(("available", "span"), [
    ((1000,), 1000), ((1500,), 500), ((1800,), 200), ((1920,), 80),
])
def test_sparse_checkpoint_preference_and_fallbacks(available, span):
    result = run(2_100, Client((2000, *available)))
    assert result["state"] == "future"
    assert result["eta"]["sample_intervals"] == span
    assert result["eta"]["average_block_seconds"] == 5


def test_all_checkpoints_unavailable_still_reports_future_without_eta():
    result = run(2_100, Client((2000,)))
    assert result == {"state": "future", "current_height": 2_000, "eta": None}


def test_past_or_current_missing_height_is_not_future_and_makes_no_block_calls():
    client = Client()
    assert run(2_000, client)["state"] == "not_indexed"
    assert run(1_999, client)["state"] == "not_indexed"
    assert client.calls == []


def test_distant_future_height_has_bounded_valid_eta():
    result = run(1_000_000, Client((2000, 1000)))
    assert result["eta"]["remaining_blocks"] == 998_000
    assert result["eta"]["estimated_at"].endswith("Z")


def test_cache_reused_for_different_targets_until_five_minute_expiry():
    now = [0.0]
    client = Client((2000, 1000))
    first = run(2_100, client, clock=lambda: now[0])
    second = run(2_200, client, clock=lambda: now[0])
    assert client.calls == [("block", 2_000), ("block", 1_000)]
    assert first["eta"]["average_block_seconds"] == second["eta"]["average_block_seconds"]
    now[0] = 301
    run(2_300, client, clock=lambda: now[0])
    assert client.calls == [("block", 2_000), ("block", 1_000)] * 2


@pytest.mark.parametrize("client", [
    Client(latest_chain="wrong-chain"),
    Client(latest_height=1_999),
    Client(latest_time="bad"),
])
def test_invalid_latest_block_is_rejected_safely(client):
    with pytest.raises(GnoBlockLookupUnavailable):
        run(2_100, client)


def test_rpc_unavailable_is_safe():
    with patch("api.gno_block_lookup.probe_rpc_endpoints", return_value=[]), \
         patch("api.gno_block_lookup.suitable_rpc_probes", return_value=[]):
        with pytest.raises(GnoBlockLookupUnavailable):
            lookup_future_block(2_100, config())


def test_wrong_height_checkpoint_is_rejected_and_falls_back():
    client = Client((2000, 1000, 1500))
    original = client.get
    client.get = lambda method, height: block(height, returned_height=999) if height == 1000 else original(method, height)
    assert run(2_100, client)["eta"]["sample_intervals"] == 500


def test_status_without_latest_time_fetches_latest_block_and_uses_its_time():
    client = Client((2000, 1000))
    result = run(2_001, client, payload=status())
    assert client.calls[:2] == [("block", 2_000), ("block", 1_000)]
    assert result["eta"]["estimated_at"] == "2026-08-31T00:00:05.000000Z"


def test_real_timezone_less_gno_timestamp_is_accepted_as_utc():
    parsed = _timestamp(REAL_GNO_TIME)
    assert parsed == datetime(2026, 8, 31, 22, 31, 32, 202247, tzinfo=timezone.utc)


@pytest.mark.parametrize(("value", "normalized"), [
    (REAL_GNO_TIME, "2026-08-31T22:31:32.202247"),
    (f"{REAL_GNO_TIME}Z", "2026-08-31T22:31:32.202247Z"),
    ("2026-09-01T00:31:32.202247944+02:00",
     "2026-09-01T00:31:32.202247+02:00"),
    ("2026-08-31T22:31:32.202247", "2026-08-31T22:31:32.202247"),
    ("2026-08-31T22:31:32Z", "2026-08-31T22:31:32Z"),
    ("2026-08-31T22:31:32", "2026-08-31T22:31:32"),
])
def test_timestamp_fraction_normalization_is_python_310_compatible(value, normalized):
    assert _normalize_timestamp_fraction(value) == normalized


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-08-31T22:31:32.202247944Z",
     datetime(2026, 8, 31, 22, 31, 32, 202247, tzinfo=timezone.utc)),
    ("2026-09-01T00:31:32.202247944+02:00",
     datetime(2026, 8, 31, 22, 31, 32, 202247, tzinfo=timezone.utc)),
    ("2026-08-31T22:31:32Z",
     datetime(2026, 8, 31, 22, 31, 32, tzinfo=timezone.utc)),
    ("2026-08-31T22:31:32",
     datetime(2026, 8, 31, 22, 31, 32, tzinfo=timezone.utc)),
])
def test_explicit_timezone_is_accepted_and_normalized(value, expected):
    assert _timestamp(value) == expected


@pytest.mark.parametrize("value", [None, "", "not-a-timestamp"])
def test_malformed_timestamp_is_rejected(value):
    with pytest.raises(RpcError, match="Malformed RPC timestamp"):
        _timestamp(value)


def test_future_lookup_accepts_real_timezone_less_latest_block_time():
    client = Client((2000, 1000), latest_time=REAL_GNO_TIME)
    now = datetime(2026, 8, 31, 22, 32, tzinfo=timezone.utc)
    result = run(2_100, client, wall_clock=lambda: now)
    assert result["state"] == "future"
    assert result["eta"] is not None
    assert result["eta"]["estimated_at"].endswith("Z")


def test_stale_latest_block_reports_future_without_eta():
    latest = _timestamp(REAL_GNO_TIME)
    result = run(2_100, Client((2000, 1000), latest_time=REAL_GNO_TIME),
                 wall_clock=lambda: latest + timedelta(hours=2))
    assert result == {"state": "future", "current_height": 2_000, "eta": None}
