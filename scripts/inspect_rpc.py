#!/usr/bin/env python3
"""Inspect a Gno.land Tendermint-style RPC endpoint.

Network access is intentionally isolated in ``GnoRpcClient``. The parsing
functions accept plain dictionaries so tests can exercise them with fixtures.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


DEFAULT_TIMEOUT = 10


class RpcError(RuntimeError):
    """Raised when the RPC endpoint cannot be queried safely."""


@dataclass(frozen=True)
class RpcSummary:
    chain_id: str | None
    latest_height: int | None
    node_version: str | None
    catching_up: bool | None
    block_hash: str | None
    block_time: str | None
    proposer_address: str | None
    tx_count: int
    validators: list[dict[str, Any]]
    commit_signatures: list[dict[str, Any]]
    signed_validators: list[dict[str, Any]]
    missed_validators: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


class GnoRpcClient:
    """Small JSON-over-HTTP client for Tendermint/Gno RPC endpoints."""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        if not base_url:
            raise RpcError("GNO_RPC_URL is required")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def get(self, method: str, **params: Any) -> dict[str, Any]:
        url = urljoin(self.base_url, method.lstrip("/"))
        try:
            import requests
        except ImportError:
            return self._get_with_urllib(url, method, params)

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise RpcError(f"RPC request timed out for {method}") from exc
        except requests.RequestException as exc:
            raise RpcError(f"RPC request failed for {method}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RpcError(f"RPC response for {method} was not valid JSON") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise RpcError(f"RPC returned an error for {method}: {payload['error']}")
        if not isinstance(payload, dict):
            raise RpcError(f"RPC response for {method} was not a JSON object")
        return payload

    def _get_with_urllib(self, url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        request_url = f"{url}?{query}" if query else url
        try:
            with urlopen(request_url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise RpcError(f"RPC request timed out for {method}") from exc
        except HTTPError as exc:
            raise RpcError(f"RPC request failed for {method}: HTTP {exc.code}") from exc
        except URLError as exc:
            raise RpcError(f"RPC request failed for {method}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RpcError(f"RPC response for {method} was not valid JSON") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise RpcError(f"RPC returned an error for {method}: {payload['error']}")
        if not isinstance(payload, dict):
            raise RpcError(f"RPC response for {method} was not a JSON object")
        return payload


def result(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("result", payload)
    return value if isinstance(value, dict) else {}


def to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_status(status_payload: dict[str, Any]) -> dict[str, Any]:
    data = result(status_payload)
    node_info = data.get("node_info") or {}
    sync_info = data.get("sync_info") or {}
    return {
        "chain_id": node_info.get("network"),
        "latest_height": to_int(sync_info.get("latest_block_height")),
        "node_version": node_info.get("version"),
        "catching_up": sync_info.get("catching_up"),
    }


def parse_block(block_payload: dict[str, Any]) -> dict[str, Any]:
    data = result(block_payload)
    block = data.get("block") or {}
    header = block.get("header") or {}
    last_commit = block.get("last_commit") or {}
    txs = block.get("data", {}).get("txs") or []
    return {
        "hash": data.get("block_id", {}).get("hash"),
        "height": to_int(header.get("height")),
        "time": header.get("time"),
        "proposer_address": header.get("proposer_address"),
        "tx_count": len(txs),
        "transactions": parse_transactions(txs),
        "commit_signatures": last_commit.get("precommits") or last_commit.get("signatures") or [],
    }


def parse_transactions(txs: list[Any]) -> list[dict[str, Any]]:
    parsed = []
    for index, tx in enumerate(txs):
        text = tx if isinstance(tx, str) else json.dumps(tx, sort_keys=True)
        parsed.append({"index": index, "type": type(tx).__name__, "size_bytes": len(text.encode()), "raw_preview": text[:120]})
    return parsed


def parse_validators(validators_payload: dict[str, Any]) -> list[dict[str, Any]]:
    vals = result(validators_payload).get("validators") or []
    parsed = []
    for val in vals:
        pub_key = val.get("pub_key") or {}
        parsed.append({
            "address": val.get("address"),
            "voting_power": to_int(val.get("voting_power")),
            "proposer_priority": to_int(val.get("proposer_priority")),
            "pub_key_type": pub_key.get("type"),
            "pub_key_value": pub_key.get("value"),
        })
    return parsed


def signer_address(signature: dict[str, Any]) -> str | None:
    return signature.get("validator_address") or signature.get("address")


def signature_signed(signature: dict[str, Any]) -> bool:
    if signature.get("absent") is True:
        return False
    if signature.get("signature"):
        return True
    flag = signature.get("block_id_flag")
    return flag in (2, "2", "BLOCK_ID_FLAG_COMMIT", "BlockIDFlagCommit")


def build_summary(status_payload: dict[str, Any], block_payload: dict[str, Any], validators_payload: dict[str, Any]) -> RpcSummary:
    status = parse_status(status_payload)
    block = parse_block(block_payload)
    validators = parse_validators(validators_payload)
    commit_signatures = block["commit_signatures"]
    signed_addresses = {addr for sig in commit_signatures if (addr := signer_address(sig)) and signature_signed(sig)}
    all_addresses = {v["address"] for v in validators if v.get("address")}
    return RpcSummary(
        chain_id=status["chain_id"], latest_height=status["latest_height"] or block["height"], node_version=status["node_version"],
        catching_up=status["catching_up"], block_hash=block["hash"], block_time=block["time"], proposer_address=block["proposer_address"],
        tx_count=block["tx_count"], validators=validators, commit_signatures=commit_signatures,
        signed_validators=[v for v in validators if v.get("address") in signed_addresses],
        missed_validators=[v for v in validators if v.get("address") in all_addresses - signed_addresses],
        transactions=block["transactions"],
    )


def fetch_summary(client: GnoRpcClient) -> RpcSummary:
    status = client.get("status")
    height = parse_status(status)["latest_height"]
    block = client.get("block", height=height) if height else client.get("block")
    validators = client.get("validators", height=height) if height else client.get("validators")
    return build_summary(status, block, validators)


def print_summary(summary: RpcSummary) -> None:
    print("Gno.land RPC discovery summary")
    print("=" * 32)
    print(f"Chain ID: {summary.chain_id}")
    print(f"Latest block height: {summary.latest_height}")
    print(f"Node/software version: {summary.node_version}")
    print(f"Catching up: {summary.catching_up}")
    print(f"Latest block hash: {summary.block_hash}")
    print(f"Latest block timestamp: {summary.block_time}")
    print(f"Latest block proposer address: {summary.proposer_address}")
    print(f"Latest block transaction count: {summary.tx_count}")
    print(f"\nValidators at latest height ({len(summary.validators)}):")
    for val in summary.validators:
        print(f"- {val['address']} power={val['voting_power']} pub_key={val['pub_key_type']}")
    print(f"\nCommit signatures ({len(summary.commit_signatures)}):")
    for sig in summary.commit_signatures:
        print(f"- validator={signer_address(sig)} signed={signature_signed(sig)} timestamp={sig.get('timestamp')}")
    print(f"\nValidators that signed ({len(summary.signed_validators)}):")
    for val in summary.signed_validators:
        print(f"- {val['address']}")
    print(f"\nValidators that missed ({len(summary.missed_validators)}):")
    for val in summary.missed_validators:
        print(f"- {val['address']}")
    print(f"\nBasic transaction information ({len(summary.transactions)}):")
    for tx in summary.transactions:
        print(f"- #{tx['index']} type={tx['type']} size_bytes={tx['size_bytes']} preview={tx['raw_preview']!r}")


def main() -> int:
    rpc_url = os.environ.get("GNO_RPC_URL", "").strip()
    try:
        summary = fetch_summary(GnoRpcClient(rpc_url))
    except RpcError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
