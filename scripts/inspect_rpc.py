#!/usr/bin/env python3
"""Inspect Gno.land Tendermint/TM2 RPC endpoints."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen

DEFAULT_TIMEOUT = 10
DEFAULT_VALIDATORS_PER_PAGE = 100


class RpcError(RuntimeError):
    """Raised when an RPC endpoint cannot be queried or parsed safely."""


@dataclass(frozen=True)
class RpcSummary:
    rpc_url: str
    chain_id: str | None
    latest_height: int
    signing_height: int
    node_version: str | None
    catching_up: bool | None
    block_hash: str | None
    block_time: str | None
    proposer_address: str | None
    tx_count: int
    validators_height: int
    commit_height: int
    canonical: Any
    validators: list[dict[str, Any]]
    commit_signatures: list[Any]
    signed_validators: list[dict[str, Any]]
    missed_validators: list[dict[str, Any]]
    transactions: list[dict[str, Any]]


class GnoRpcClient:
    """Small JSON-over-HTTP client for Tendermint/Gno RPC endpoints."""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        if not base_url:
            raise RpcError("RPC URL is required")
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
        return validate_payload(method, payload)

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
        return validate_payload(method, payload)


def validate_payload(method: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and payload.get("error"):
        raise RpcError(f"RPC returned an error for {method}: {payload['error']}")
    if not isinstance(payload, dict):
        raise RpcError(f"RPC response for {method} was not a JSON object")
    return payload


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def configured_rpc_urls() -> list[str]:
    load_dotenv()
    urls = [url.strip() for url in os.environ.get("GNO_RPC_URLS", "").split(",") if url.strip()]
    legacy = os.environ.get("GNO_RPC_URL", "").strip()
    if not urls and legacy:
        urls = [legacy]
    return urls


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
    txs = block.get("data", {}).get("txs") or []
    return {
        "hash": data.get("block_id", {}).get("hash"),
        "height": to_int(header.get("height")),
        "time": header.get("time"),
        "proposer_address": header.get("proposer_address"),
        "tx_count": len(txs),
        "transactions": parse_transactions(txs),
    }


def parse_commit(commit_payload: dict[str, Any]) -> dict[str, Any]:
    data = result(commit_payload)
    signed_header = data.get("signed_header")
    if not isinstance(signed_header, dict):
        raise RpcError("Malformed commit response: missing result.signed_header")
    header = signed_header.get("header")
    commit = signed_header.get("commit")
    if not isinstance(header, dict) or not isinstance(commit, dict):
        raise RpcError("Malformed commit response: missing signed_header.header or signed_header.commit")
    precommits = commit.get("precommits")
    if not isinstance(precommits, list):
        raise RpcError("Malformed commit response: missing signed_header.commit.precommits")
    header_height = to_int(header.get("height"))
    commit_height = to_int(commit.get("height")) or header_height
    if commit_height is None:
        raise RpcError("Malformed commit response: missing commit height")
    return {
        "height": commit_height,
        "header_height": header_height,
        "precommits": precommits,
        "canonical": data.get("canonical"),
    }


def parse_transactions(txs: list[Any]) -> list[dict[str, Any]]:
    parsed = []
    for index, tx in enumerate(txs):
        text = tx if isinstance(tx, str) else json.dumps(tx, sort_keys=True)
        parsed.append({"index": index, "type": type(tx).__name__, "size_bytes": len(text.encode()), "raw_preview": text[:120]})
    return parsed


def parse_validators(validators_payload: dict[str, Any]) -> dict[str, Any]:
    data = result(validators_payload)
    vals = data.get("validators") or []
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
    return {"height": to_int(data.get("height")), "total": to_int(data.get("total")), "validators": parsed}


def signer_address(signature: Any) -> str | None:
    if not isinstance(signature, dict):
        return None
    return signature.get("validator_address") or signature.get("address")


def signature_signed(signature: Any) -> bool:
    if not isinstance(signature, dict) or signature.get("absent") is True:
        return False
    if signature.get("signature"):
        return True
    flag = signature.get("block_id_flag")
    return flag in (2, "2", "BLOCK_ID_FLAG_COMMIT", "BlockIDFlagCommit")


def build_summary(rpc_url: str, status_payload: dict[str, Any], block_payload: dict[str, Any], commit_payload: dict[str, Any], validators_payload: dict[str, Any]) -> RpcSummary:
    status = parse_status(status_payload)
    block = parse_block(block_payload)
    commit = parse_commit(commit_payload)
    validators_data = parse_validators(validators_payload)
    latest_height = status["latest_height"] or block["height"]
    if latest_height is None:
        raise RpcError("Latest height is unavailable")
    signing_height = latest_height - 1
    if signing_height < 1:
        raise RpcError("Latest height is too low for H-1 signing analysis")
    validators_height = validators_data["height"] or signing_height
    if commit["height"] != signing_height:
        raise RpcError(f"Commit height mismatch: expected {signing_height}, got {commit['height']}")
    if validators_height != signing_height:
        raise RpcError(f"Validator-set height mismatch: expected {signing_height}, got {validators_height}")
    validators = validators_data["validators"]
    signed_addresses = {addr for sig in commit["precommits"] if (addr := signer_address(sig)) and signature_signed(sig)}
    all_addresses = {v["address"] for v in validators if v.get("address")}
    return RpcSummary(
        rpc_url=rpc_url,
        chain_id=status["chain_id"],
        latest_height=latest_height,
        signing_height=signing_height,
        node_version=status["node_version"],
        catching_up=status["catching_up"],
        block_hash=block["hash"],
        block_time=block["time"],
        proposer_address=block["proposer_address"],
        tx_count=block["tx_count"],
        validators_height=validators_height,
        commit_height=commit["height"],
        canonical=commit["canonical"],
        validators=validators,
        commit_signatures=commit["precommits"],
        signed_validators=[v for v in validators if v.get("address") in signed_addresses],
        missed_validators=[v for v in validators if v.get("address") in all_addresses - signed_addresses],
        transactions=block["transactions"],
    )


def select_healthy_rpc(urls: list[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[GnoRpcClient, dict[str, Any]]:
    if not urls:
        raise RpcError("Set GNO_RPC_URLS to a comma-separated RPC list, or temporarily set legacy GNO_RPC_URL")
    failures = []
    for url in urls:
        client = GnoRpcClient(url, timeout=timeout)
        try:
            status_payload = client.get("status")
            status = parse_status(status_payload)
            if status["catching_up"] is True:
                raise RpcError("endpoint is catching up")
        except RpcError as exc:
            print(f"RPC check failed: {url} ({exc})")
            failures.append(f"{url}: {exc}")
            continue
        print(f"RPC check succeeded: {url}")
        print(f"Selected RPC: {url}")
        return client, status_payload
    raise RpcError("All RPC endpoints are unavailable: " + "; ".join(failures))


def fetch_validators(client: GnoRpcClient, height: int, per_page: int = DEFAULT_VALIDATORS_PER_PAGE) -> dict[str, Any]:
    page = 1
    combined: dict[str, Any] | None = None
    validators: list[dict[str, Any]] = []
    while True:
        payload = client.get("validators", height=height, page=page, per_page=per_page)
        data = result(payload)
        if combined is None:
            combined = {"result": {**data, "validators": []}}
        validators.extend(data.get("validators") or [])
        total = to_int(data.get("total"))
        if total is None or len(validators) >= total or not data.get("validators"):
            break
        page += 1
    assert combined is not None
    combined["result"]["validators"] = validators
    return combined


def fetch_summary(client: GnoRpcClient, status_payload: dict[str, Any]) -> RpcSummary:
    latest_height = parse_status(status_payload)["latest_height"]
    if latest_height is None:
        raise RpcError("/status did not include latest_block_height")
    signing_height = latest_height - 1
    if signing_height < 1:
        raise RpcError("Latest height is too low for H-1 signing analysis")
    block = client.get("block", height=latest_height)
    commit = client.get("commit", height=signing_height)
    validators = fetch_validators(client, signing_height)
    return build_summary(client.base_url.rstrip("/"), status_payload, block, commit, validators)


def print_summary(summary: RpcSummary) -> None:
    print("Gno.land RPC discovery summary")
    print("=" * 32)
    print(f"Selected RPC: {summary.rpc_url}")
    print(f"Chain ID: {summary.chain_id}")
    print(f"Latest block height: {summary.latest_height}")
    print(f"Signing analysis height: {summary.signing_height}")
    print(f"Node/software version: {summary.node_version}")
    print(f"Catching up: {summary.catching_up}")
    print(f"Latest block hash: {summary.block_hash}")
    print(f"Latest block timestamp: {summary.block_time}")
    print(f"Latest block proposer address: {summary.proposer_address}")
    print(f"Latest block transaction count: {summary.tx_count}")
    print(f"Commit height: {summary.commit_height}")
    print(f"Validator-set height: {summary.validators_height}")
    print(f"Canonical commit: {json.dumps(summary.canonical, sort_keys=True)}")
    print(f"\nValidators at signing height ({len(summary.validators)}):")
    for val in summary.validators:
        print(f"- {val['address']} power={val['voting_power']} pub_key={val['pub_key_type']}")
    print(f"\nCommit precommits ({len(summary.commit_signatures)}):")
    for sig in summary.commit_signatures:
        print(f"- validator={signer_address(sig)} signed={signature_signed(sig)} timestamp={sig.get('timestamp') if isinstance(sig, dict) else None}")
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
    try:
        client, status_payload = select_healthy_rpc(configured_rpc_urls())
        summary = fetch_summary(client, status_payload)
    except RpcError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
