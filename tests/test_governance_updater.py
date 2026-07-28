from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import indexer.governance_updater as updater
from governance.gno import (GovernanceListDiscovery, GovernanceProposalSummary,
                            GovernanceSource)
from indexer.governance_persistence import (GovernanceChainIdentityError,
                                            GovernanceStoredStateError)


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
    monkeypatch.setattr(updater, "select_rpc", lambda *args: selected)
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


def test_failure_log_does_not_leak_urls(caplog, monkeypatch):
    stop = ClockStop()
    monkeypatch.setattr(updater, "run_full_cycle", Mock(side_effect=RuntimeError(config().database_url)))
    stop.wait = lambda seconds: setattr(stop, "requested", True) or True
    updater.run_updater(config(), object(), stop)
    assert "secret" not in caplog.text and "postgresql://" not in caplog.text
