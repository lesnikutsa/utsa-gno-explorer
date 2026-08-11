"""Live account retrieval using the shared RPC freshness selector."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import ipaddress
import logging
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from api.account_adapters import AccountParseError, parse_auth_account, parse_bank_balances
from api.network_profile import gno_profile
from indexer.rpc import RpcProbeResult, probe_rpc_endpoints, suitable_rpc_candidates
from scripts.inspect_rpc import RpcError

LOGGER = logging.getLogger(__name__)
ACCOUNT_RPC_PROBE_CACHE_TTL_SECONDS = 15.0

_ProbeCacheKey = tuple[tuple[str, ...], str, int, int]
_probe_cache: dict[_ProbeCacheKey, tuple[float, tuple[RpcProbeResult, ...]]] = {}
_probe_cache_lock = threading.Lock()
_probe_inflight: dict[_ProbeCacheKey, Future[tuple[RpcProbeResult, ...]]] = {}


@dataclass(frozen=True)
class _ProbeLookup:
    probes: list[RpcProbeResult]
    cache_hit: bool
    probe_performed: bool
    shared_inflight: bool
    probe_duration: float | None


class AccountUnavailableError(RuntimeError):
    """No fresh RPC candidate returned consistent account data."""


def public_rpc_url(value: str) -> str:
    """Return a bounded public HTTP RPC origin without any private URL components."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(char) < 33 for char in value):
        raise AccountParseError("invalid RPC URL")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        hostname_value = parsed.hostname
        try:
            ipaddress.ip_address(hostname_value)
        except ValueError:
            dns_name = hostname_value[:-1] if hostname_value.endswith(".") else hostname_value
            labels = dns_name.split(".")
            if (
                not dns_name or len(dns_name) > 253
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)
            ):
                raise ValueError
        port = parsed.port
        if parsed.netloc.rsplit("@", 1)[-1].endswith(":"):
            raise ValueError
    except ValueError as exc:
        raise AccountParseError("invalid RPC URL") from exc
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{hostname}:{port}" if port is not None else hostname
    result = urlunsplit((parsed.scheme, netloc, "", "", ""))
    if len(result) > 2048:
        raise AccountParseError("invalid RPC URL")
    return result


def _safe_rpc_hostname(value: str) -> str:
    try:
        return urlsplit(public_rpc_url(value)).hostname or "invalid"
    except AccountParseError:
        return "invalid"


def _account_probes(config) -> _ProbeLookup:
    key = (tuple(config.rpc_urls), config.chain_id, config.rpc_max_height_lag,
           config.account_rpc_timeout_seconds)
    with _probe_cache_lock:
        now = time.monotonic()
        expired_keys = [
            cached_key for cached_key, (stored_at, _) in _probe_cache.items()
            if now - stored_at >= ACCOUNT_RPC_PROBE_CACHE_TTL_SECONDS
        ]
        for expired_key in expired_keys:
            _probe_cache.pop(expired_key, None)
        cached = _probe_cache.get(key)
        if cached is not None and now - cached[0] < ACCOUNT_RPC_PROBE_CACHE_TTL_SECONDS:
            return _ProbeLookup(list(cached[1]), True, False, False, None)

        inflight = _probe_inflight.get(key)
        leader = inflight is None
        if leader:
            inflight = Future()
            _probe_inflight[key] = inflight

    if not leader:
        try:
            probes = inflight.result()
        except Exception:
            LOGGER.info(
                "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_shared_inflight=true",
            )
            raise
        return _ProbeLookup(list(probes), False, False, True, None)

    started_at = time.perf_counter()
    try:
        probes = probe_rpc_endpoints(
            list(config.rpc_urls), config.chain_id, config.rpc_max_height_lag,
            timeout=config.account_rpc_timeout_seconds,
        )
        frozen_probes = tuple(probes)
    except Exception as exc:
        duration = time.perf_counter() - started_at
        with _probe_cache_lock:
            inflight.set_exception(exc)
            _probe_inflight.pop(key, None)
        LOGGER.info(
            "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_total_seconds=%.6f",
            duration,
        )
        raise

    duration = time.perf_counter() - started_at
    cacheable = bool(suitable_rpc_candidates(probes))
    with _probe_cache_lock:
        if cacheable:
            _probe_cache[key] = (time.monotonic(), frozen_probes)
        else:
            _probe_cache.pop(key, None)
        inflight.set_result(frozen_probes)
        _probe_inflight.pop(key, None)
    return _ProbeLookup(list(frozen_probes), False, True, False, duration)


def _timed_account_query(client, path: str, height: int) -> tuple[str, float]:
    started_at = time.perf_counter()
    value = client.abci_query(path, "", height=height)
    return value, time.perf_counter() - started_at


def _prefer_account_candidate(candidates: list, preferred_rpc_url: str | None) -> tuple[list, bool]:
    """Return a stable copy with the exact suitable preferred probe first."""
    ordered = list(candidates)
    if preferred_rpc_url is None:
        return ordered, False
    preferred_index = next((
        index for index, candidate in enumerate(ordered)
        if candidate.probes and candidate.probes[0].url == preferred_rpc_url
    ), None)
    if preferred_index is None:
        return ordered, False
    return [ordered[preferred_index], *ordered[:preferred_index], *ordered[preferred_index + 1:]], True


def fetch_live_account(address: str, config, *, preferred_rpc_url: str | None = None) -> dict:
    total_started_at = time.perf_counter()
    profile = gno_profile(config.chain_id)
    try:
        try:
            lookup = _account_probes(config)
            probes = lookup.probes
            candidates, preferred_suitable = _prefer_account_candidate(
                suitable_rpc_candidates(probes), preferred_rpc_url,
            )
        except Exception:
            LOGGER.warning("account_rpc_discovery rpc_probe_cache_hit=false")
            raise AccountUnavailableError from None

        if lookup.cache_hit:
            LOGGER.info("account_rpc_discovery rpc_probe_cache_hit=true")
        elif lookup.shared_inflight:
            LOGGER.info(
                "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_shared_inflight=true",
            )
        else:
            LOGGER.info(
                "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_total_seconds=%.6f",
                lookup.probe_duration,
            )
        for probe in probes:
            LOGGER.info(
                "account_rpc_probe rpc_hostname=%s response_seconds=%s",
                _safe_rpc_hostname(getattr(probe, "url", "")),
                "unavailable" if getattr(probe, "response_seconds", None) is None
                else f"{probe.response_seconds:.6f}",
            )

        LOGGER.info(
            "account_rpc_preference preferred_rpc_present=%s preferred_candidate_suitable=%s",
            preferred_rpc_url is not None, preferred_suitable,
        )

        for candidate_number, candidate in enumerate(candidates, 1):
            candidate_is_preferred = bool(
                preferred_rpc_url is not None and candidate.probes
                and candidate.probes[0].url == preferred_rpc_url
            )
            query_height = candidate.finalized_tip
            parallel_started_at = time.perf_counter()
            try:
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="account-query") as executor:
                    auth_future = executor.submit(
                        _timed_account_query, candidate.client, f"auth/accounts/{address}", query_height,
                    )
                    bank_future = executor.submit(
                        _timed_account_query, candidate.client, f"bank/balances/{address}", query_height,
                    )
                    auth_text, auth_duration = auth_future.result()
                    bank_text, bank_duration = bank_future.result()
                parallel_duration = time.perf_counter() - parallel_started_at
                account = parse_auth_account(auth_text, address)
                balances = parse_bank_balances(bank_text, profile)
                if account is None:
                    if balances:
                        raise AccountParseError("inconsistent missing account")
                    account = {"account_number": None, "sequence": None, "public_key": None}
                LOGGER.info(
                    "account_rpc_query selected_rpc_hostname=%s selected_query_height=%s "
                    "auth_query_seconds=%.6f bank_query_seconds=%.6f "
                    "account_query_parallel_total_seconds=%.6f failover_candidate_number=%s "
                    "successful_candidate_kind=%s",
                    _safe_rpc_hostname(candidate.client.base_url), query_height, auth_duration,
                    bank_duration, parallel_duration, candidate_number,
                    "canonical" if candidate_is_preferred else (
                        "fallback" if preferred_rpc_url is not None else "unowned"
                    ),
                )
                return {
                    "address": address, "found": account["account_number"] is not None,
                    "balances": balances, **account,
                    "source": {"kind": "rpc", "chain_id": config.chain_id,
                               "rpc_url": public_rpc_url(candidate.client.base_url)},
                    "observed_height": query_height,
                }
            except (RpcError, AccountParseError, TypeError, ValueError, OSError):
                LOGGER.warning(
                    "account_rpc_candidate_failed selected_rpc_hostname=%s selected_query_height=%s "
                    "account_query_parallel_total_seconds=%.6f failover_candidate_number=%s",
                    _safe_rpc_hostname(candidate.client.base_url), query_height,
                    time.perf_counter() - parallel_started_at, candidate_number,
                )
        raise AccountUnavailableError
    finally:
        LOGGER.info(
            "account_live_rpc_timing account_live_rpc_seconds=%.6f",
            time.perf_counter() - total_started_at,
        )
