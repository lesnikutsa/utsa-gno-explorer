from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import indexer.governance_updater as updater
from governance.gno import (GovernanceListDiscovery, GovernanceProposalSummary,
                            GovernanceSource)
from indexer.governance_persistence import (GovernanceChainIdentityError,
                                            GovernanceSnapshotConflict,
                                            GovernanceStoredStateError)
from indexer.rpc import RpcProbeResult


def config(**changes):
    values = dict(database_url="postgresql://user:secret@db/name", rpc_urls=["https://user:secret@rpc"],
                  chain_id="topaz-1", realm="gno.land/r/gov/dao", max_height_lag=10,
                  refresh_interval_seconds=30, full_reconcile_interval_seconds=21600,
                  error_backoff_seconds=5, max_backoff_seconds=60)
    values.update(changes)
    return updater.GovernanceUpdaterConfig(**values)


class ClockStop:
    def __init__(self): self.now = 0; self.requested = False; self.waits = []
    def wait(self, seconds): self.waits.append(seconds); self.now += seconds; return self.requested
    def clock(self): return self.now


def test_initial_then_quick_and_six_hour_full_schedule(monkeypatch):
    stop, calls = ClockStop(), []
    monkeypatch.setattr(updater, "run_full_cycle", lambda *args: calls.append(("full", stop.now)))
    monkeypatch.setattr(updater, "run_quick_cycle", lambda *args: calls.append(("quick", stop.now)))
    updater.run_updater(config(refresh_interval_seconds=10800), object(), stop, max_cycles=4, clock=stop.clock)
    assert calls == [("full", 0), ("quick", 10800), ("full", 21600), ("quick", 32400)]
    assert stop.waits == [10800, 10800, 10800]


@pytest.mark.parametrize("kwargs", [{"once": True}, {"full_once": True}, {"max_cycles": 2}])
def test_cycle_count_controls(monkeypatch, kwargs):
    stop, calls = ClockStop(), []
    monkeypatch.setattr(updater, "run_full_cycle", lambda *args: calls.append("full"))
    monkeypatch.setattr(updater, "run_quick_cycle", lambda *args: calls.append("quick"))
    updater.run_updater(config(), object(), stop, clock=stop.clock, **kwargs)
    assert len(calls) == (2 if "max_cycles" in kwargs else 1)
    if kwargs.get("full_once"): assert calls == ["full"]


def test_backoff_caps_and_success_resets_after_completed_cycle(monkeypatch):
    stop, outcomes = ClockStop(), iter([RuntimeError(), RuntimeError(), RuntimeError(), None, RuntimeError()])
    def cycle(*args):
        outcome = next(outcomes)
        if outcome: raise outcome
        stop.requested = False
    monkeypatch.setattr(updater, "run_full_cycle", cycle)
    monkeypatch.setattr(updater, "run_quick_cycle", cycle)
    original_wait = stop.wait
    def wait(seconds):
        result = original_wait(seconds)
        if len(stop.waits) == 6: stop.requested = True
        return result
    stop.wait = wait
    updater.run_updater(config(error_backoff_seconds=5, max_backoff_seconds=10,
                               refresh_interval_seconds=30), object(), stop, clock=stop.clock)
    assert stop.waits == [5, 10, 10, 30, 5, 10]


@pytest.mark.parametrize("error", [GovernanceChainIdentityError("chain"), GovernanceStoredStateError("state")])
def test_stored_identity_errors_are_fatal(monkeypatch, error):
    monkeypatch.setattr(updater, "run_full_cycle", Mock(side_effect=error))
    with pytest.raises(type(error)):
        updater.run_updater(config(), object(), ClockStop(), once=True)


def test_stop_aware_wait_exits_without_another_cycle(monkeypatch):
    stop, calls = ClockStop(), []
    monkeypatch.setattr(updater, "run_full_cycle", lambda *args: calls.append("full"))
    def wait(seconds): stop.requested = True; stop.waits.append(seconds); return True
    stop.wait = wait
    updater.run_updater(config(), object(), stop, clock=stop.clock)
    assert calls == ["full"] and stop.waits == [30]


def test_quick_cycle_targets_only_mutable_ids_at_one_height(monkeypatch):
    source = GovernanceSource("topaz-1", "https://rpc", 88, "gno.land/r/gov/dao")
    summaries = (GovernanceProposalSummary(2, "New", None, None, "ACCEPTED"),
                 GovernanceProposalSummary(1, "Active", None, None, "ACTIVE"),
                 GovernanceProposalSummary(0, "Frozen", None, None, "ACCEPTED"))
    listed = GovernanceListDiscovery(source, True, 1, summaries)
    selected = SimpleNamespace(client=SimpleNamespace(base_url="https://rpc"), latest_height=88)
    monkeypatch.setattr(updater, "_candidates", lambda *args: [selected])
    monkeypatch.setattr(updater, "discover_governance_list", lambda client, actual, capture_raw: listed)
    fetched = []
    monkeypatch.setattr(updater, "discover_governance_proposal",
                        lambda client, actual, summary, capture_raw: fetched.append((summary.proposal_id, actual.observed_height)) or SimpleNamespace())
    database = SimpleNamespace(
        governance_statuses=lambda *args: {0: "ACCEPTED", 1: "ACTIVE"},
        persist_governance_incremental=lambda actual, targeted, chain: SimpleNamespace(
            source_height=88, page_count=1, proposal_count=3, inserted_proposals=1,
            updated_proposals=1, action="applied"))
    updater.run_quick_cycle(config(), database)
    assert fetched == [(2, 88), (1, 88)]


def test_quick_cycle_retries_complete_operation_without_mixing_candidates(monkeypatch):
    candidates = [
        SimpleNamespace(client=SimpleNamespace(base_url="https://first.rpc"), latest_height=90),
        SimpleNamespace(client=SimpleNamespace(base_url="https://second.rpc"), latest_height=88),
    ]
    summaries = (GovernanceProposalSummary(1, "Active", None, None, "ACTIVE"),)
    calls = []

    def discover_list(client, source, capture_raw):
        calls.append(("list", client.base_url, source.observed_height))
        return GovernanceListDiscovery(source, True, 1, summaries)

    def discover_proposal(client, source, summary, capture_raw):
        calls.append(("proposal", client.base_url, source.observed_height))
        if client.base_url == "https://first.rpc":
            raise ValueError("malformed render")
        return SimpleNamespace()

    persisted = []
    database = SimpleNamespace(
        governance_statuses=lambda *args: {1: "ACTIVE"},
        persist_governance_incremental=lambda listed, targeted, chain: persisted.append(
            (listed.source.rpc_url, listed.source.observed_height)) or SimpleNamespace(
                source_height=listed.source.observed_height, page_count=1, proposal_count=1,
                inserted_proposals=0, updated_proposals=1, action="applied"))
    monkeypatch.setattr(updater, "_candidates", lambda *args: candidates)
    monkeypatch.setattr(updater, "discover_governance_list", discover_list)
    monkeypatch.setattr(updater, "discover_governance_proposal", discover_proposal)

    updater.run_quick_cycle(config(), database)

    assert calls == [
        ("list", "https://first.rpc", 90),
        ("proposal", "https://first.rpc", 90),
        ("list", "https://second.rpc", 88),
        ("proposal", "https://second.rpc", 88),
    ]
    assert persisted == [("https://second.rpc", 88)]


def test_first_success_stops_candidate_attempts(monkeypatch):
    candidates = [
        SimpleNamespace(client=SimpleNamespace(base_url="https://first.rpc"), latest_height=90),
        SimpleNamespace(client=SimpleNamespace(base_url="https://second.rpc"), latest_height=90),
    ]
    calls = []
    discovery = SimpleNamespace(proposals=())
    result = SimpleNamespace(source_height=90, page_count=1, proposal_count=0,
                             inserted_proposals=0, updated_proposals=0, action="unchanged")
    monkeypatch.setattr(updater, "_candidates", lambda *args: candidates)
    monkeypatch.setattr(updater, "discover_governance",
                        lambda client, *args, **kwargs: calls.append(client.base_url) or discovery)
    updater.run_full_cycle(config(), SimpleNamespace(
        persist_governance_snapshot=lambda *args: result))
    assert calls == ["https://first.rpc"]


def test_full_discovery_failure_falls_back_to_next_candidate(monkeypatch):
    candidates = [
        SimpleNamespace(client=SimpleNamespace(base_url="https://first.rpc"), latest_height=90),
        SimpleNamespace(client=SimpleNamespace(base_url="https://second.rpc"), latest_height=89),
    ]
    calls = []
    discovery = SimpleNamespace(proposals=())
    result = SimpleNamespace(source_height=89, page_count=1, proposal_count=0,
                             inserted_proposals=0, updated_proposals=0, action="applied")

    def discover(client, source, capture_raw):
        calls.append((client.base_url, source.observed_height))
        if client.base_url == "https://first.rpc":
            raise ValueError("incomplete response")
        return discovery

    monkeypatch.setattr(updater, "_candidates", lambda *args: candidates)
    monkeypatch.setattr(updater, "discover_governance", discover)
    updater.run_full_cycle(config(), SimpleNamespace(
        persist_governance_snapshot=lambda *args: result))
    assert calls == [("https://first.rpc", 90), ("https://second.rpc", 89)]


@pytest.mark.parametrize("error", [GovernanceChainIdentityError("chain"),
                                    GovernanceStoredStateError("state"),
                                    GovernanceSnapshotConflict("conflict")])
def test_fatal_persistence_error_does_not_try_next_candidate(monkeypatch, error):
    candidates = [
        SimpleNamespace(client=SimpleNamespace(base_url="https://first.rpc"), latest_height=90),
        SimpleNamespace(client=SimpleNamespace(base_url="https://second.rpc"), latest_height=90),
    ]
    calls = []
    monkeypatch.setattr(updater, "_candidates", lambda *args: candidates)
    monkeypatch.setattr(updater, "discover_governance",
                        lambda client, *args, **kwargs: calls.append(client.base_url) or SimpleNamespace(proposals=()))
    with pytest.raises(type(error)):
        updater.run_full_cycle(config(), SimpleNamespace(
            persist_governance_snapshot=Mock(side_effect=error)))
    assert calls == ["https://first.rpc"]


def test_safe_rpc_host_removes_credentials_port_and_query():
    assert updater.safe_rpc_host("https://rpc.example/path") == "rpc.example"
    assert updater.safe_rpc_host("https://user:secret@rpc.example:443/path?token=secret") == "rpc.example"


def test_probe_failure_and_stale_candidate_are_skipped_in_configured_order(monkeypatch):
    clients = [SimpleNamespace(base_url=f"https://rpc-{number}.example") for number in range(3)]
    probes = [
        RpcProbeResult("https://rpc-0.example", False, False, error_message="rpc_error"),
        RpcProbeResult("https://rpc-1.example", False, False, latest_height=70,
                       observed_lag=20, error_message="stale endpoint", client=clients[1]),
        RpcProbeResult("https://rpc-2.example", True, True, chain_id="topaz-1",
                       latest_height=90, observed_lag=0, catching_up=False,
                       client=clients[2], status_payload={"result": {}}),
    ]
    monkeypatch.setattr(updater, "probe_rpc_endpoints", lambda *args: probes)
    candidates = updater._candidates(config(rpc_urls=[probe.url for probe in probes]), "quick")
    assert [(candidate.client.base_url, candidate.latest_height) for candidate in candidates] == [
        ("https://rpc-2.example", 90)
    ]


def test_attempt_log_contains_safe_fields_without_sensitive_values(caplog):
    selected = SimpleNamespace(
        client=SimpleNamespace(base_url="https://user:rpc-secret@rpc.example/path?token=raw-render"),
        latest_height=90,
    )
    with caplog.at_level("INFO"):
        updater._attempt_log("quick", selected, 1, 2, "votes", 0, "failed", "RpcError", 7)
    assert "rpc_host=rpc.example" in caplog.text
    assert "stage=votes" in caplog.text
    assert "proposal_id=7" in caplog.text
    assert "rpc-secret" not in caplog.text
    assert "raw-render" not in caplog.text
    assert "postgresql://" not in caplog.text


def test_failure_log_does_not_leak_urls(caplog, monkeypatch):
    stop = ClockStop()
    monkeypatch.setattr(updater, "run_full_cycle", Mock(side_effect=RuntimeError(config().database_url)))
    stop.wait = lambda seconds: setattr(stop, "requested", True) or True
    updater.run_updater(config(), object(), stop)
    assert "secret" not in caplog.text and "postgresql://" not in caplog.text
