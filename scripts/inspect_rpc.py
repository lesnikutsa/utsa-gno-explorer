#!/usr/bin/env python3
"""Inspect Gno.land Tendermint/TM2 RPC endpoints."""
from __future__ import annotations

import base64
import binascii
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
    block_hash_base64: str
    block_hash_hex: str
    block_time: str | None
    proposer_address: str | None
    tx_count: int
    validators_height: int
    commit_height: int
    canonical: bool
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


def configured_chain_id() -> str:
    load_dotenv()
    return os.environ.get("GNO_CHAIN_ID", "test-13").strip() or "test-13"


def configured_max_height_lag() -> int:
    load_dotenv()
    value = os.environ.get("RPC_MAX_HEIGHT_LAG", "10").strip()
    try:
        lag = int(value)
    except ValueError as exc:
        raise RpcError("RPC_MAX_HEIGHT_LAG must be an integer") from exc
    if lag < 0:
        raise RpcError("RPC_MAX_HEIGHT_LAG must not be negative")
    return lag


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
        "node_version": data.get("build_version") or node_info.get("version"),
        "catching_up": sync_info.get("catching_up"),
    }


def decode_base64(value: Any, field_name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise RpcError(f"Malformed RPC response: missing {field_name}")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RpcError(f"Malformed RPC response: invalid base64 in {field_name}") from exc


def parse_block(block_payload: dict[str, Any]) -> dict[str, Any]:
    data = result(block_payload)
    block = data.get("block") or {}
    header = block.get("header") or {}
    txs = block.get("data", {}).get("txs") or []
    block_hash_base64 = data.get("block_meta", {}).get("block_id", {}).get("hash")
    block_hash_bytes = decode_base64(block_hash_base64, "result.block_meta.block_id.hash")
    header_num_txs = to_int(header.get("num_txs"))
    if header_num_txs is None:
        raise RpcError("Malformed block response: missing result.block.header.num_txs")
    if header_num_txs != len(txs):
        raise RpcError(f"Block transaction count mismatch: header num_txs={header_num_txs}, data txs={len(txs)}")
    return {
        "hash_base64": block_hash_base64,
        "hash_hex": block_hash_bytes.hex().upper(),
        "height": to_int(header.get("height")),
        "time": header.get("time"),
        "proposer_address": header.get("proposer_address"),
        "tx_count": header_num_txs,
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
    if header_height is None:
        raise RpcError("Malformed commit response: missing signed_header.header.height")
    canonical = data.get("canonical")
    if not isinstance(canonical, bool):
        raise RpcError("Malformed commit response: result.canonical must be a boolean")
    return {
        "height": header_height,
        "header_height": header_height,
        "precommits": precommits,
        "canonical": canonical,
    }


def parse_transactions(txs: list[Any]) -> list[dict[str, Any]]:
    parsed = []
    for index, tx in enumerate(txs):
        raw_base64 = tx if isinstance(tx, str) else json.dumps(tx, sort_keys=True)
        decoded_size_bytes = 0
        base64_decoded = False
        try:
            decoded_size_bytes = len(base64.b64decode(raw_base64, validate=True))
            base64_decoded = True
        except (binascii.Error, ValueError):
            pass
        parsed.append({
            "index": index,
            "raw_base64": raw_base64,
            "encoded_size_chars": len(raw_base64),
            "decoded_size_bytes": decoded_size_bytes,
            "raw_preview": raw_base64[:120],
            "base64_decoded": base64_decoded,
        })
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
            "pub_key_type": pub_key.get("@type") or pub_key.get("type"),
            "pub_key_display_type": normalize_pub_key_type(pub_key.get("@type") or pub_key.get("type")),
            "pub_key_value": pub_key.get("value"),
        })
    block_height = to_int(data.get("block_height"))
    if block_height is None:
        raise RpcError("Malformed validators response: missing result.block_height")
    return {"block_height": block_height, "total": to_int(data.get("total")), "validators": parsed}


def normalize_pub_key_type(pub_key_type: Any) -> str | None:
    if pub_key_type == "/tm.PubKeyEd25519":
        return "Ed25519"
    if isinstance(pub_key_type, str):
        return pub_key_type.rsplit(".", 1)[-1].lstrip("/")
    return None


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
    validators_height = validators_data["block_height"]
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
        block_hash_base64=block["hash_base64"],
        block_hash_hex=block["hash_hex"],
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


def validate_status_for_health(status: dict[str, Any], expected_chain_id: str) -> None:
    if not status["chain_id"]:
        raise RpcError("malformed status: missing chain ID")
    if status["latest_height"] is None:
        raise RpcError("malformed status: missing latest height")
    if not isinstance(status["catching_up"], bool):
        raise RpcError("malformed status: missing catching_up boolean")
    if status["chain_id"] != expected_chain_id:
        raise RpcError(f"wrong chain ID: expected {expected_chain_id}, got {status['chain_id']}")
    if status["catching_up"] is True:
        raise RpcError("endpoint is catching up")


def select_healthy_rpc(urls: list[str], timeout: int = DEFAULT_TIMEOUT, expected_chain_id: str | None = None, max_height_lag: int | None = None) -> tuple[GnoRpcClient, dict[str, Any]]:
    if not urls:
        raise RpcError("Set GNO_RPC_URLS to a comma-separated RPC list, or temporarily set legacy GNO_RPC_URL")
    expected_chain_id = expected_chain_id or configured_chain_id()
    max_height_lag = configured_max_height_lag() if max_height_lag is None else max_height_lag
    probes = []
    for order, url in enumerate(urls):
        client = GnoRpcClient(url, timeout=timeout)
        try:
            status_payload = client.get("status")
            status = parse_status(status_payload)
            validate_status_for_health(status, expected_chain_id)
            probes.append({"order": order, "url": url, "client": client, "payload": status_payload, "status": status})
        except RpcError as exc:
            print(f"RPC health failed: {url} ({exc})")
            continue
    if not probes:
        raise RpcError("All RPC endpoints are rejected or unavailable")
    highest_height = max(probe["status"]["latest_height"] for probe in probes)
    for probe in probes:
        height = probe["status"]["latest_height"]
        lag = highest_height - height
        probe["lag"] = lag
        print(f"RPC health succeeded: {probe['url']} chain_id={probe['status']['chain_id']} height={height} lag={lag} catching_up={probe['status']['catching_up']}")
    for probe in probes:
        if probe["lag"] <= max_height_lag:
            print(f"Selected RPC: {probe['url']} height={probe['status']['latest_height']} lag={probe['lag']}")
            return probe["client"], probe["payload"]
    raise RpcError(f"No suitable RPC endpoint is within RPC_MAX_HEIGHT_LAG={max_height_lag} of highest healthy height {highest_height}")


def fetch_validators(client: GnoRpcClient, height: int) -> dict[str, Any]:
    return client.get("validators", height=height)


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
    print(f"Latest block hash (base64): {summary.block_hash_base64}")
    print(f"Latest block hash (hex): {summary.block_hash_hex}")
    print(f"Latest block timestamp: {summary.block_time}")
    print(f"Latest block proposer address: {summary.proposer_address}")
    print(f"Latest block transaction count: {summary.tx_count}")
    print(f"Commit height: {summary.commit_height}")
    print(f"Validator-set height: {summary.validators_height}")
    print(f"Canonical commit: {summary.canonical}")
    print(f"\nValidators at signing height ({len(summary.validators)}):")
    for val in summary.validators:
        print(f"- {val['address']} power={val['voting_power']} pub_key={val['pub_key_type']} display={val['pub_key_display_type']}")
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
        print(f"- #{tx['index']} encoded_size_chars={tx['encoded_size_chars']} decoded={tx['base64_decoded']} decoded_size_bytes={tx['decoded_size_bytes']} preview={tx['raw_preview']!r}")


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
