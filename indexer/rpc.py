"""RPC selection and finalized-height fetching for bounded runs."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from scripts.inspect_rpc import GnoRpcClient, RpcError, decode_base64, parse_status, validate_status_for_health

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RpcProbeResult:
    url: str
    healthy: bool
    selected: bool
    chain_id: str | None = None
    latest_height: int | None = None
    observed_lag: int | None = None
    catching_up: bool | None = None
    error_message: str | None = None
    client: GnoRpcClient | None = None
    status_payload: dict[str, Any] | None = None


class RpcContinuityError(RpcError):
    """An endpoint cannot prove continuity with the persisted canonical chain."""


@dataclass(frozen=True)
class SelectedRpc:
    client: GnoRpcClient
    status_payload: dict[str, Any]
    latest_height: int
    finalized_tip: int
    probes: list[RpcProbeResult]


def probe_rpc_endpoints(urls: list[str], chain_id: str, max_height_lag: int, timeout: int = 10) -> list[RpcProbeResult]:
    if not urls:
        raise RpcError("Set GNO_RPC_URLS to a comma-separated RPC list, or temporarily set legacy GNO_RPC_URL")
    raw_probes = [_probe_endpoint(url, chain_id, timeout) for url in urls]
    healthy_heights = [probe.latest_height for probe in raw_probes if probe.healthy and probe.latest_height is not None]
    if not healthy_heights:
        return raw_probes
    highest_height = max(healthy_heights)
    probes_with_lag = [_with_lag(probe, highest_height, max_height_lag) for probe in raw_probes]
    selected_index = _selected_probe_index(probes_with_lag, max_height_lag)
    return [
        RpcProbeResult(**{**probe.__dict__, "selected": index == selected_index})
        for index, probe in enumerate(probes_with_lag)
    ]


def selected_rpc_from_probes(probes: list[RpcProbeResult], max_height_lag: int) -> SelectedRpc:
    healthy_heights = [probe.latest_height for probe in probes if probe.healthy and probe.latest_height is not None]
    if not healthy_heights:
        raise RpcError("All RPC endpoints are rejected or unavailable")
    highest_height = max(healthy_heights)
    selected_probe = next((probe for probe in probes if probe.selected), None)
    if selected_probe is None:
        raise RpcError(
            f"No suitable RPC endpoint is within RPC_MAX_HEIGHT_LAG={max_height_lag} "
            f"of highest healthy height {highest_height}"
        )
    if selected_probe.client is None or selected_probe.status_payload is None or selected_probe.latest_height is None:
        raise RpcError("Selected RPC probe is missing successful payload data")
    return SelectedRpc(
        client=selected_probe.client,
        status_payload=selected_probe.status_payload,
        latest_height=selected_probe.latest_height,
        finalized_tip=selected_probe.latest_height - 1,
        probes=probes,
    )


def select_rpc(urls: list[str], chain_id: str, max_height_lag: int, timeout: int = 10) -> SelectedRpc:
    probes = probe_rpc_endpoints(urls, chain_id, max_height_lag, timeout)
    return selected_rpc_from_probes(probes, max_height_lag)


def _probe_endpoint(url: str, expected_chain_id: str, timeout: int) -> RpcProbeResult:
    client = GnoRpcClient(url, timeout=timeout)
    try:
        status_payload = client.get("status")
        status = parse_status(status_payload)
        validate_status_for_health(status, expected_chain_id)
    except RpcError as exc:
        status = locals().get("status", {})
        return RpcProbeResult(
            url=url,
            healthy=False,
            selected=False,
            chain_id=status.get("chain_id"),
            latest_height=status.get("latest_height"),
            catching_up=status.get("catching_up"),
            error_message=str(exc),
            client=client,
        )
    return RpcProbeResult(
        url=url,
        healthy=True,
        selected=False,
        chain_id=status["chain_id"],
        latest_height=status["latest_height"],
        catching_up=status["catching_up"],
        client=client,
        status_payload=status_payload,
    )


def _with_lag(probe: RpcProbeResult, highest_height: int, max_height_lag: int) -> RpcProbeResult:
    if not probe.healthy or probe.latest_height is None:
        return probe
    lag = highest_height - probe.latest_height
    if lag > max_height_lag:
        return RpcProbeResult(**{**probe.__dict__, "healthy": False, "observed_lag": lag, "error_message": "stale endpoint"})
    return RpcProbeResult(**{**probe.__dict__, "observed_lag": lag})


def _selected_probe_index(probes: list[RpcProbeResult], max_height_lag: int) -> int | None:
    for index, probe in enumerate(probes):
        if probe.healthy and probe.observed_lag is not None and probe.observed_lag <= max_height_lag:
            return index
    return None



def canonical_block_hash_hex(payload: dict[str, Any]) -> str:
    """Return the canonical TM2 block hash as normalized uppercase hexadecimal."""
    try:
        value = payload["result"]["block_meta"]["block_id"]["hash"]
    except (KeyError, TypeError) as exc:
        raise RpcContinuityError("malformed_block_hash") from exc
    if not isinstance(value, str) or not value:
        raise RpcContinuityError("missing_block_hash")
    try:
        decoded = decode_base64(value, "BlockID.Hash")
    except RpcError as exc:
        raise RpcContinuityError("malformed_block_hash") from exc
    if not decoded:
        raise RpcContinuityError("missing_block_hash")
    return decoded.hex().upper()


def parent_block_hash_hex(payload: dict[str, Any]) -> str:
    """Return header.last_block_id.hash for both TM2 field spellings."""
    try:
        header = payload["result"]["block"]["header"]
        block_id = header.get("last_block_id") or header.get("last_block_id_hash") or header.get("lastBlockID")
        value = block_id.get("hash") or block_id.get("Hash")
    except (KeyError, TypeError, AttributeError) as exc:
        raise RpcContinuityError("missing_parent_hash") from exc
    if not isinstance(value, str) or not value:
        raise RpcContinuityError("missing_parent_hash")
    try:
        decoded = decode_base64(value, "Header.LastBlockID.Hash")
    except RpcError as exc:
        raise RpcContinuityError("malformed_parent_hash") from exc
    if not decoded:
        raise RpcContinuityError("missing_parent_hash")
    return decoded.hex().upper()


def verify_parent_continuity(payload: dict[str, Any], expected_hash_hex: str) -> str:
    actual = parent_block_hash_hex(payload)
    if actual != expected_hash_hex.upper():
        raise RpcContinuityError("parent_hash_mismatch")
    return canonical_block_hash_hex(payload)


def verify_checkpoint_anchor(client: GnoRpcClient, height: int, expected_hash_hex: str) -> None:
    try:
        actual = canonical_block_hash_hex(client.get("block", height=height))
    except RpcContinuityError:
        raise
    except RpcError as exc:
        raise RpcContinuityError("checkpoint_unavailable") from exc
    if actual != expected_hash_hex.upper():
        raise RpcContinuityError("checkpoint_hash_mismatch")


def fetch_height(client: GnoRpcClient, height: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    started_at = time.perf_counter()

    def timed_get(method: str) -> tuple[dict[str, Any], float]:
        request_started_at = time.perf_counter()
        payload = client.get(method, height=height)
        return payload, time.perf_counter() - request_started_at

    methods = ("block", "commit", "validators")
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix=f"rpc-height-{height}") as executor:
        futures = [executor.submit(timed_get, method) for method in methods]
        results = [future.result() for future in futures]

    total_duration = time.perf_counter() - started_at
    LOGGER.info(
        "rpc_fetch height=%s total_seconds=%.6f block_seconds=%.6f commit_seconds=%.6f validators_seconds=%.6f",
        height,
        total_duration,
        results[0][1],
        results[1][1],
        results[2][1],
    )
    return results[0][0], results[1][0], results[2][0]
