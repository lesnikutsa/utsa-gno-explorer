#!/usr/bin/env python3
"""One-shot Cosmos RPC/REST capability probe with sanitized output.

The probe never mutates endpoints. It validates basic chain freshness separately
from transaction-search / transaction-lookup capabilities so a provider can be
healthy for blocks while unsuitable for transaction history.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

# Match CosmosNetworkConfig.request_timeout so a probe timeout means the same
# thing as an explorer transport timeout unless the operator overrides it.
TIMEOUT = 10.0
MAX_BYTES = 2_000_000


def host(url: str) -> str:
    return urlsplit(url).hostname or "invalid"


def get_json(base: str, path: str, timeout: float | None = None):
    timeout = TIMEOUT if timeout is None else timeout
    started = time.monotonic()
    request = Request(base.rstrip("/") + path, headers={"Accept": "application/json", "User-Agent": "utsa-cosmos-endpoint-probe/1"})
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(MAX_BYTES + 1)
            status = response.status
    except HTTPError as exc:
        body = exc.read(MAX_BYTES + 1)
        status = exc.code
    if len(body) > MAX_BYTES:
        raise ValueError("response_too_large")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_json_object")
    return payload, status, round((time.monotonic() - started) * 1000)


def error_text(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        error = " ".join(str(error.get(key, "")) for key in ("message", "data"))
    return " ".join(str(value) for value in (payload.get("message", ""), payload.get("details", ""), error or ""))


def query_unsupported(payload) -> bool:
    text = error_text(payload).lower()
    return "query" in text and any(marker in text for marker in ("unknown", "unsupported", "unrecognized", "cannot find", "no such"))


def indexing_unavailable(payload) -> bool:
    text = error_text(payload).lower()
    return (("tx" in text or "transaction" in text) and ("index" in text or "search" in text)
            and any(marker in text for marker in ("disabled", "unavailable", "not enabled", "not configured", "no indexer")))


def rest_head(endpoint: str):
    payload, status, latency = get_json(endpoint, "/cosmos/base/tendermint/v1beta1/blocks/latest")
    block = payload.get("block") if isinstance(payload.get("block"), dict) else {}
    header = block.get("header") if isinstance(block.get("header"), dict) else {}
    chain_id = header.get("chain_id")
    height = header.get("height")
    if not isinstance(chain_id, str) or not str(height).isdigit():
        raise ValueError("invalid_rest_head")
    return chain_id, int(height), status, latency


def rest_tx_search(endpoint: str):
    expression = quote("tx.height>0", safe="")
    modern = f"/cosmos/tx/v1beta1/txs?query={expression}&order_by=ORDER_BY_DESC&page=1&limit=1"
    legacy = f"/cosmos/tx/v1beta1/txs?events={expression}&order_by=ORDER_BY_DESC&page=1&limit=1"
    payload, status, latency = get_json(endpoint, modern)
    mode = "modern"
    if query_unsupported(payload):
        payload, status, latency = get_json(endpoint, legacy)
        mode = "legacy"
    if indexing_unavailable(payload):
        return "indexing_disabled", mode, None, None, status, latency
    txs, responses = payload.get("txs"), payload.get("tx_responses")
    if not isinstance(txs, list) or not isinstance(responses, list) or len(txs) != len(responses) or len(txs) > 1:
        return "malformed", mode, None, None, status, latency
    if not responses:
        return "empty", mode, None, None, status, latency
    response = responses[0] if isinstance(responses[0], dict) else {}
    tx_hash, height = response.get("txhash"), response.get("height")
    if not isinstance(tx_hash, str) or len(tx_hash) != 64 or not str(height).isdigit():
        return "malformed", mode, None, None, status, latency
    return "ok", mode, tx_hash.upper(), int(height), status, latency


def rpc_status(endpoint: str):
    payload, status, latency = get_json(endpoint, "/status")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    node_info = result.get("node_info") if isinstance(result.get("node_info"), dict) else {}
    sync = result.get("sync_info") if isinstance(result.get("sync_info"), dict) else {}
    chain_id, height = node_info.get("network"), sync.get("latest_block_height")
    catching_up = sync.get("catching_up")
    if not isinstance(chain_id, str) or not str(height).isdigit() or not isinstance(catching_up, bool):
        raise ValueError("invalid_rpc_status")
    return chain_id, int(height), catching_up, status, latency


def rpc_block_results(endpoint: str, height: int):
    payload, status, latency = get_json(endpoint, f"/block_results?height={height}")
    if isinstance(payload.get("error"), dict):
        return "error", status, latency
    result = payload.get("result")
    return ("ok" if isinstance(result, dict) else "malformed"), status, latency


def rpc_tx_lookup(endpoint: str, tx_hash: str):
    payload, status, latency = get_json(endpoint, f"/tx?hash=0x{tx_hash}&prove=false")
    error = payload.get("error")
    if isinstance(error, dict):
        text = error_text(payload).lower()
        if "not found" in text:
            return "not_found", status, latency
        if indexing_unavailable({"message": text}):
            return "indexing_disabled", status, latency
        return "error", status, latency
    result = payload.get("result") if isinstance(payload.get("result"), dict) else None
    if result and str(result.get("hash", "")).upper() == tx_hash.upper():
        return "ok", status, latency
    return "malformed", status, latency


def load_config(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid network config")
    return payload


def print_row(columns):
    print("\t".join(str(value) for value in columns))


def main(argv=None):
    global TIMEOUT
    parser = argparse.ArgumentParser(description="Probe Cosmos endpoint capabilities without changing explorer state")
    parser.add_argument("--config", default="networks/atomone-mainnet/network.json")
    parser.add_argument("--rpc", action="append", default=[], help="additional RPC URL (repeatable)")
    parser.add_argument("--rest", action="append", default=[], help="additional REST/API URL (repeatable)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT,
                        help="per-request timeout; defaults to explorer Cosmos transport timeout (10s)")
    args = parser.parse_args(argv)
    if not 0.5 <= args.timeout <= 30:
        parser.error("--timeout must be between 0.5 and 30 seconds")
    TIMEOUT = args.timeout

    try:
        config = load_config(Path(args.config))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"CONFIG_ERROR\t{type(exc).__name__}", file=sys.stderr)
        return 2

    expected_chain = config.get("chain_id")
    rpc_endpoints = list(dict.fromkeys([*(config.get("rpc_endpoints") or []), *args.rpc]))
    rest_endpoints = list(dict.fromkeys([*(config.get("rest_endpoints") or []), *args.rest]))

    print(f"TIMEOUT_S\t{TIMEOUT:g}")
    print("REST ENDPOINTS")
    print_row(("HOST", "CHAIN", "HEIGHT", "HEAD", "TX_SEARCH", "MODE", "TX_HEIGHT", "LATENCY_MS"))
    discovered = []
    for endpoint in rest_endpoints:
        h = host(endpoint)
        try:
            chain, height, head_status, head_ms = rest_head(endpoint)
            head_state = "ok" if head_status < 400 and chain == expected_chain else "bad"
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            print_row((h, "-", "-", type(exc).__name__, "not_tested", "-", "-", "-"))
            continue
        try:
            state, mode, tx_hash, tx_height, _status, tx_ms = rest_tx_search(endpoint)
            if tx_hash:
                discovered.append((tx_hash, tx_height, h))
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            state, mode, tx_hash, tx_height, tx_ms = type(exc).__name__, "-", None, None, "-"
        print_row((h, chain, height, head_state, state, mode, tx_height or "-", f"{head_ms}/{tx_ms}"))

    probe_hash = discovered[0][0] if discovered else None
    print()
    print("RPC ENDPOINTS")
    print_row(("HOST", "CHAIN", "HEIGHT", "SYNC", "BLOCK_RESULTS", "TX_LOOKUP", "LATENCY_MS"))
    for endpoint in rpc_endpoints:
        h = host(endpoint)
        try:
            chain, height, catching_up, _status, status_ms = rpc_status(endpoint)
            sync_state = "catching_up" if catching_up else ("ok" if chain == expected_chain else "wrong_chain")
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            print_row((h, "-", "-", type(exc).__name__, "not_tested", "not_tested", "-"))
            continue
        target = max(1, height - 1)
        try:
            block_state, _status, block_ms = rpc_block_results(endpoint, target)
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            block_state, block_ms = type(exc).__name__, "-"
        if probe_hash:
            try:
                tx_state, _status, tx_ms = rpc_tx_lookup(endpoint, probe_hash)
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                tx_state, tx_ms = type(exc).__name__, "-"
        else:
            tx_state, tx_ms = "not_tested_no_tx", "-"
        print_row((h, chain, height, sync_state, block_state, tx_state,
                   f"{status_ms}/{block_ms}/{tx_ms}"))

    if discovered:
        print()
        print(f"TX_PROBE_HASH\t{probe_hash}\tfrom={discovered[0][2]}\theight={discovered[0][1]}")
    else:
        print()
        print("TX_PROBE_HASH\tnone\tREST search returned no usable transaction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
