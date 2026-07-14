"""RPC selection and finalized-height fetching for bounded runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.inspect_rpc import GnoRpcClient, RpcError, parse_status, validate_status_for_health


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


@dataclass(frozen=True)
class SelectedRpc:
    client: GnoRpcClient
    status_payload: dict[str, Any]
    latest_height: int
    finalized_tip: int
    probes: list[RpcProbeResult]


def select_rpc(urls: list[str], chain_id: str, max_height_lag: int, timeout: int = 10) -> SelectedRpc:
    if not urls:
        raise RpcError("Set GNO_RPC_URLS to a comma-separated RPC list, or temporarily set legacy GNO_RPC_URL")

    raw_probes = [_probe_endpoint(url, chain_id, timeout) for url in urls]
    healthy_heights = [probe.latest_height for probe in raw_probes if probe.healthy and probe.latest_height is not None]
    if not healthy_heights:
        raise RpcError("All RPC endpoints are rejected or unavailable")

    highest_height = max(healthy_heights)
    probes_with_lag = [_with_lag(probe, highest_height, max_height_lag) for probe in raw_probes]
    selected_index = _selected_probe_index(probes_with_lag, max_height_lag)
    if selected_index is None:
        raise RpcError(
            f"No suitable RPC endpoint is within RPC_MAX_HEIGHT_LAG={max_height_lag} "
            f"of highest healthy height {highest_height}"
        )

    selected_probe = probes_with_lag[selected_index]
    selected_probes = [
        RpcProbeResult(**{**probe.__dict__, "selected": index == selected_index})
        for index, probe in enumerate(probes_with_lag)
    ]
    if selected_probe.client is None or selected_probe.status_payload is None or selected_probe.latest_height is None:
        raise RpcError("Selected RPC probe is missing successful payload data")
    return SelectedRpc(
        client=selected_probe.client,
        status_payload=selected_probe.status_payload,
        latest_height=selected_probe.latest_height,
        finalized_tip=selected_probe.latest_height - 1,
        probes=selected_probes,
    )


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


def fetch_height(client: GnoRpcClient, height: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        client.get("block", height=height),
        client.get("commit", height=height),
        client.get("validators", height=height),
    )
