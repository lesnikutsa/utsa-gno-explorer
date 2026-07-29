"""Live account retrieval using the shared RPC freshness selector."""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from api.account_adapters import AccountParseError, parse_auth_account, parse_bank_balances
from api.network_profile import topaz_profile
from indexer.rpc import RpcProbeResult, probe_rpc_endpoints, suitable_rpc_candidates
from scripts.inspect_rpc import RpcError

LOGGER = logging.getLogger(__name__)
ACCOUNT_RPC_PROBE_CACHE_TTL_SECONDS = 15.0

_ProbeCacheKey = tuple[tuple[str, ...], str, int, int]
_probe_cache: dict[_ProbeCacheKey, tuple[float, tuple[RpcProbeResult, ...]]] = {}
_probe_cache_lock = threading.Lock()


class AccountUnavailableError(RuntimeError):
    """No fresh RPC candidate returned consistent account data."""


def public_rpc_url(value: str) -> str:
    """Return a bounded credential- and parameter-free public HTTP RPC URL."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ord(char) < 33 for char in value):
        raise AccountParseError("invalid RPC URL")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        port = parsed.port
    except ValueError as exc:
        raise AccountParseError("invalid RPC URL") from exc
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{hostname}:{port}" if port is not None else hostname
    result = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    if len(result) > 2048:
        raise AccountParseError("invalid RPC URL")
    return result


def _safe_rpc_hostname(value: str) -> str:
    try:
        return urlsplit(public_rpc_url(value)).hostname or "invalid"
    except AccountParseError:
        return "invalid"


def _account_probes(config) -> tuple[list[RpcProbeResult], bool, float | None]:
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
            return list(cached[1]), True, None

        started_at = time.perf_counter()
        try:
            probes = probe_rpc_endpoints(
                list(config.rpc_urls), config.chain_id, config.rpc_max_height_lag,
                timeout=config.account_rpc_timeout_seconds,
            )
        except Exception:
            LOGGER.info(
                "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_total_seconds=%.6f",
                time.perf_counter() - started_at,
            )
            raise
        duration = time.perf_counter() - started_at
        if suitable_rpc_candidates(probes):
            _probe_cache[key] = (time.monotonic(), tuple(probes))
        else:
            _probe_cache.pop(key, None)
        return list(probes), False, duration


def _timed_account_query(client, path: str, height: int) -> tuple[str, float]:
    started_at = time.perf_counter()
    value = client.abci_query(path, "", height=height)
    return value, time.perf_counter() - started_at


def fetch_live_account(address: str, config) -> dict:
    total_started_at = time.perf_counter()
    profile = topaz_profile(config.chain_id)
    try:
        try:
            probes, cache_hit, probe_duration = _account_probes(config)
            candidates = suitable_rpc_candidates(probes)
        except Exception:
            LOGGER.warning("account_rpc_discovery rpc_probe_cache_hit=false")
            raise AccountUnavailableError from None

        if probe_duration is None:
            LOGGER.info("account_rpc_discovery rpc_probe_cache_hit=true")
        else:
            LOGGER.info(
                "account_rpc_discovery rpc_probe_cache_hit=false rpc_probe_total_seconds=%.6f",
                probe_duration,
            )
        for probe in probes:
            LOGGER.info(
                "account_rpc_probe rpc_hostname=%s response_seconds=%s",
                _safe_rpc_hostname(getattr(probe, "url", "")),
                "unavailable" if getattr(probe, "response_seconds", None) is None
                else f"{probe.response_seconds:.6f}",
            )

        for candidate_number, candidate in enumerate(candidates, 1):
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
                    "account_query_parallel_total_seconds=%.6f failover_candidate_number=%s",
                    _safe_rpc_hostname(candidate.client.base_url), query_height, auth_duration,
                    bank_duration, parallel_duration, candidate_number,
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
        LOGGER.info("account_request_timing account_total_seconds=%.6f", time.perf_counter() - total_started_at)
