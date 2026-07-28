"""Sequential continuous Governance updater."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from governance.gno import (GovernanceSource, discover_governance,
                            discover_governance_list, discover_governance_proposal)
from indexer.governance_persistence import (GovernanceChainIdentityError,
                                            GovernancePersistenceError,
                                            StaleGovernanceSnapshot,
                                            GovernanceStoredStateError,
                                            select_governance_refresh_ids)
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_candidates
from scripts.inspect_rpc import RpcError
from indexer.runner import StopController

LOGGER = logging.getLogger(__name__)


class FatalGovernanceUpdaterError(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernanceUpdaterConfig:
    database_url: str
    rpc_urls: list[str]
    chain_id: str
    realm: str
    max_height_lag: int
    refresh_interval_seconds: int = 30
    full_reconcile_interval_seconds: int = 21600
    error_backoff_seconds: int = 5
    max_backoff_seconds: int = 60


def validate_config(config: GovernanceUpdaterConfig) -> None:
    if not config.database_url:
        raise FatalGovernanceUpdaterError("DATABASE_URL is required")
    if not config.realm.startswith("gno.land/r/") or ":" in config.realm:
        raise FatalGovernanceUpdaterError("invalid governance realm")
    values = (config.refresh_interval_seconds, config.full_reconcile_interval_seconds,
              config.error_backoff_seconds, config.max_backoff_seconds)
    if any(type(value) is not int or value < 1 for value in values):
        raise FatalGovernanceUpdaterError("governance intervals must be positive integers")
    if config.refresh_interval_seconds > config.full_reconcile_interval_seconds:
        raise FatalGovernanceUpdaterError("refresh interval must not exceed full reconcile interval")
    if config.error_backoff_seconds > config.max_backoff_seconds:
        raise FatalGovernanceUpdaterError("error backoff must not exceed max backoff")


def _source(config, selected):
    return GovernanceSource(config.chain_id, selected.client.base_url.rstrip("/"),
                            selected.latest_height, config.realm)


def safe_rpc_host(url: str) -> str:
    """Extract a log-safe endpoint hostname, excluding credentials, port and query."""
    return urlsplit(url).hostname or "unknown"


def _candidates(config, cycle_type):
    started = time.monotonic()
    probes = probe_rpc_endpoints(config.rpc_urls, config.chain_id, config.max_height_lag, 10)
    candidates = suitable_rpc_candidates(probes)
    for index, probe in enumerate(probes, 1):
        LOGGER.info(
            "cycle_type=%s rpc_host=%s source_height=%s attempt=%s candidate_count=%s "
            "stage=probe result=%s error_type=%s duration_seconds=%.3f",
            cycle_type, safe_rpc_host(probe.url), probe.latest_height, index, len(candidates),
            "succeeded" if probe.healthy else "failed", probe.error_message or "none",
            time.monotonic() - started,
        )
    if not candidates:
        raise RpcError("No suitable Governance RPC candidates")
    return candidates


def _attempt_log(cycle_type, selected, attempt, count, stage, started, result,
                 error_type="none", proposal_id=None):
    LOGGER.info(
        "cycle_type=%s rpc_host=%s source_height=%s attempt=%s candidate_count=%s "
        "stage=%s proposal_id=%s result=%s error_type=%s duration_seconds=%.3f",
        cycle_type, safe_rpc_host(selected.client.base_url), selected.latest_height, attempt,
        count, stage, proposal_id if proposal_id is not None else "none", result,
        error_type, time.monotonic() - started,
    )


def _is_fatal_attempt_error(exc):
    return (isinstance(exc, GovernancePersistenceError)
            and not isinstance(exc, StaleGovernanceSnapshot))


def run_full_cycle(config, database):
    started = time.monotonic()
    candidates = _candidates(config, "full")
    for attempt, selected in enumerate(candidates, 1):
        attempt_started, stage = time.monotonic(), "list"
        try:
            discovery = discover_governance(selected.client, _source(config, selected), capture_raw=True)
            stage = "persist"
            result = database.persist_governance_snapshot(discovery, config.chain_id)
        except Exception as exc:
            _attempt_log("full", selected, attempt, len(candidates), stage, attempt_started,
                         "failed", type(exc).__name__)
            if _is_fatal_attempt_error(exc):
                raise
            continue
        _attempt_log("full", selected, attempt, len(candidates), stage, attempt_started, "succeeded")
        break
    else:
        raise RpcError("All suitable Governance RPC attempts failed")
    LOGGER.info("cycle_type=full source_height=%s page_count=%s proposal_count=%s targeted_count=%s inserted_count=%s updated_count=%s active_count=%s duration_seconds=%.3f action=%s",
                result.source_height, result.page_count, result.proposal_count, result.proposal_count,
                result.inserted_proposals, result.updated_proposals,
                sum(p.status == "ACTIVE" for p in discovery.proposals), time.monotonic() - started, result.action)
    return result


def run_quick_cycle(config, database):
    started = time.monotonic()
    candidates = _candidates(config, "quick")
    for attempt, selected in enumerate(candidates, 1):
        attempt_started, stage, proposal_id = time.monotonic(), "list", None
        try:
            source = _source(config, selected)
            listed = discover_governance_list(selected.client, source, capture_raw=True)
            stored = database.governance_statuses(config.chain_id, config.realm)
            selected_ids = set(select_governance_refresh_ids(listed.proposals, stored))
            targeted = []
            stage = "proposal"
            for summary in listed.proposals:
                if summary.proposal_id in selected_ids:
                    proposal_id = summary.proposal_id
                    targeted.append(discover_governance_proposal(
                        selected.client, source, summary, capture_raw=True))
            stage, proposal_id = "persist", None
            result = database.persist_governance_incremental(listed, targeted, config.chain_id)
        except Exception as exc:
            _attempt_log("quick", selected, attempt, len(candidates), stage, attempt_started,
                         "failed", type(exc).__name__, proposal_id)
            if _is_fatal_attempt_error(exc):
                raise
            continue
        _attempt_log("quick", selected, attempt, len(candidates), stage, attempt_started, "succeeded")
        break
    else:
        raise RpcError("All suitable Governance RPC attempts failed")
    LOGGER.info("cycle_type=quick source_height=%s page_count=%s proposal_count=%s targeted_count=%s inserted_count=%s updated_count=%s active_count=%s duration_seconds=%.3f action=%s",
                result.source_height, result.page_count, result.proposal_count, len(targeted),
                result.inserted_proposals, result.updated_proposals,
                sum(p.status == "ACTIVE" for p in listed.proposals), time.monotonic() - started, result.action)
    return result


def run_updater(config, database, stop: StopController, *, once=False, full_once=False,
                max_cycles=None, clock=time.monotonic) -> int:
    validate_config(config)
    cycles = 0
    last_full = None
    backoff = config.error_backoff_seconds
    while not stop.requested:
        try:
            now = clock()
            full = full_once or last_full is None or now - last_full >= config.full_reconcile_interval_seconds
            (run_full_cycle if full else run_quick_cycle)(config, database)
            if full:
                last_full = clock()
            cycles += 1
            backoff = config.error_backoff_seconds
            if once or full_once or (max_cycles is not None and cycles >= max_cycles):
                return 0
            stop.wait(config.refresh_interval_seconds)
        except (GovernanceChainIdentityError, GovernanceStoredStateError):
            raise
        except Exception as exc:
            LOGGER.warning("All suitable Governance RPC attempts failed; retrying after %s seconds; error_type=%s",
                           backoff, type(exc).__name__)
            stop.wait(backoff)
            backoff = min(backoff * 2, config.max_backoff_seconds)
    return 0
