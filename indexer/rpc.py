"""RPC selection and finalized-height fetching."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.inspect_rpc import GnoRpcClient, RpcError, parse_status, select_healthy_rpc


@dataclass(frozen=True)
class SelectedRpc:
    client: GnoRpcClient
    status_payload: dict[str, Any]
    latest_height: int
    finalized_tip: int


def select_rpc(urls: list[str], chain_id: str, max_height_lag: int) -> SelectedRpc:
    client, status_payload = select_healthy_rpc(urls, expected_chain_id=chain_id, max_height_lag=max_height_lag)
    latest = parse_status(status_payload)["latest_height"]
    if latest is None or latest < 1:
        raise RpcError("Selected RPC did not provide a usable latest height")
    return SelectedRpc(client=client, status_payload=status_payload, latest_height=latest, finalized_tip=latest - 1)


def fetch_height(client: GnoRpcClient, height: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        client.get("block", height=height),
        client.get("commit", height=height),
        client.get("validators", height=height),
    )
