"""Parsers for normalized bounded-indexer records."""
from __future__ import annotations

import base64
import binascii
import json
import hashlib
from dataclasses import dataclass
from typing import Any

from .transaction_summary import generic_summary, normalize_summary
from .transaction_decoder import TransactionDecoder

from scripts.inspect_rpc import RpcError, decode_base64, parse_block as legacy_parse_block, parse_commit, parse_validators, signer_address, to_int

ZERO_HASHES = {"", "AA==", "AAA=", "AAAA", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}


@dataclass(frozen=True)
class NormalizedBlockID:
    hash_base64: str | None
    hash_hex: str | None
    parts_total: int | None
    parts_hash_base64: str | None
    parts_hash_hex: str | None
    is_zero: bool


@dataclass(frozen=True)
class ParsedHeight:
    height: int
    block: dict[str, Any]
    transactions: list[dict[str, Any]]
    execution_results: list[dict[str, Any]]
    validators: list[dict[str, Any]]
    signatures: list[dict[str, Any]]
    raw_block: dict[str, Any]


def parse_tx(index: int, tx: Any, transaction_decoder: TransactionDecoder | None = None) -> dict[str, Any]:
    raw_base64 = tx if isinstance(tx, str) else json.dumps(tx, sort_keys=True)
    try:
        decoded = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError):
        return {
            "index": index,
            "raw_base64": raw_base64,
            "raw_base64_length": len(raw_base64),
            "decoded_bytes": None,
            "decoded_byte_length": None,
            "decode_status": "invalid_base64",
            "tx_hash_hex": None,
            "payload_summary": generic_summary("invalid"),
        }
    payload_summary = generic_summary()
    if transaction_decoder is not None:
        try:
            candidate = transaction_decoder.decode(raw_base64, len(decoded))
            if candidate is not None:
                normalized = normalize_summary(candidate)
                if normalized["parse_status"] in {"parsed", "unsupported"}:
                    payload_summary = normalized
        except Exception:
            pass
    return {
        "index": index,
        "raw_base64": raw_base64,
        "raw_base64_length": len(raw_base64),
        "decoded_bytes": decoded,
        "decoded_byte_length": len(decoded),
        "decode_status": "decoded",
        "tx_hash_hex": hashlib.sha256(decoded).hexdigest().upper(),
        "payload_summary": payload_summary,
    }


def parse_block(payload: dict[str, Any], transaction_decoder: TransactionDecoder | None = None) -> dict[str, Any]:
    parsed = legacy_parse_block(payload)
    txs = (((payload.get("result") or {}).get("block") or {}).get("data") or {}).get("txs") or []
    parsed["transactions"] = [parse_tx(index, tx, transaction_decoder) for index, tx in enumerate(txs)]
    return parsed


def normalize_block_id(block_id: Any, field_name: str) -> NormalizedBlockID:
    if not isinstance(block_id, dict):
        raise RpcError(f"Malformed {field_name}: expected object")
    block_hash = block_id.get("hash") or block_id.get("Hash")
    parts = block_id.get("parts") or block_id.get("parts_header") or block_id.get("PartsHeader") or {}
    if parts is None:
        parts = {}
    if not isinstance(parts, dict):
        raise RpcError(f"Malformed {field_name}.parts: expected object")
    parts_total = to_int(parts.get("total") or parts.get("Total"))
    parts_hash = parts.get("hash") or parts.get("Hash")
    is_zero = (
        (block_hash is None or block_hash in ZERO_HASHES)
        and (parts_total in (None, 0))
        and (parts_hash is None or parts_hash in ZERO_HASHES)
    )
    if is_zero:
        return NormalizedBlockID(
            block_hash if isinstance(block_hash, str) else None,
            None,
            parts_total,
            parts_hash if isinstance(parts_hash, str) else None,
            None,
            True,
        )
    if not isinstance(block_hash, str) or not block_hash:
        raise RpcError(f"Malformed {field_name}: missing hash")
    if parts_total is None or parts_total < 0:
        raise RpcError(f"Malformed {field_name}: missing non-negative parts total")
    if not isinstance(parts_hash, str) or not parts_hash:
        raise RpcError(f"Malformed {field_name}: missing parts hash")
    return NormalizedBlockID(
        hash_base64=block_hash,
        hash_hex=decode_base64(block_hash, f"{field_name}.hash").hex().upper(),
        parts_total=parts_total,
        parts_hash_base64=parts_hash,
        parts_hash_hex=decode_base64(parts_hash, f"{field_name}.parts.hash").hex().upper(),
        is_zero=False,
    )


def block_ids_match(left: NormalizedBlockID, right: NormalizedBlockID) -> bool:
    return (
        not left.is_zero
        and not right.is_zero
        and left.hash_base64 == right.hash_base64
        and left.parts_total == right.parts_total
        and left.parts_hash_base64 == right.parts_hash_base64
    )


def classify_votes(height: int, commit: dict[str, Any], validators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_addresses = {validator["address"] for validator in validators if validator.get("address")}
    commit_block_id = _commit_block_id(commit)
    validator_key_types = {validator["address"]: validator.get("pub_key_type") for validator in validators if validator.get("address")}
    malformed_precommits = []
    outside_signers = []
    seen: dict[str, dict[str, Any]] = {}
    duplicate_signers: set[str] = set()

    for index, precommit in enumerate(commit["precommits"]):
        if precommit is None:
            continue
        if not isinstance(precommit, dict):
            malformed_precommits.append(f"precommit[{index}] is not an object")
            continue
        address = signer_address(precommit)
        if not address:
            malformed_precommits.append(f"precommit[{index}] is missing signer address")
            continue
        if address not in active_addresses:
            outside_signers.append(address)
            continue
        if address in seen:
            duplicate_signers.add(address)
            continue
        seen[address] = precommit

    if malformed_precommits:
        raise RpcError("Malformed non-null precommit: " + "; ".join(malformed_precommits))
    if outside_signers:
        raise RpcError(f"Signer outside active validator set: {', '.join(sorted(outside_signers))}")

    rows = []
    for address in sorted(active_addresses):
        precommit = seen.get(address)
        if precommit is None:
            rows.append(_signature_row(height, address, "absent", False, None, False, False, None, None))
            continue
        if address in duplicate_signers:
            rows.append(_signature_row(height, address, "invalid", False, None, False, False, None, precommit))
            continue
        rows.append(_classify_precommit(height, address, precommit, commit_block_id, validator_key_types.get(address)))
    return rows


def _commit_block_id(commit: dict[str, Any]) -> NormalizedBlockID:
    raw_commit = ((commit.get("raw") or {}).get("result") or {}).get("signed_header", {}).get("commit", {})
    return normalize_block_id(raw_commit.get("block_id"), "Commit.BlockID")


def _classify_precommit(
    height: int,
    address: str,
    precommit: dict[str, Any],
    commit_block_id: NormalizedBlockID,
    public_key_type: str | None,
) -> dict[str, Any]:
    try:
        vote_block_id = normalize_block_id(_precommit_block_id(precommit), "Vote.BlockID")
    except RpcError:
        return _signature_row(height, address, "invalid", False, None, False, False, _signature(precommit), precommit)

    signature = _signature(precommit)
    signature_ok = _usable_signature(signature, public_key_type)
    matches_commit = block_ids_match(vote_block_id, commit_block_id)
    if matches_commit and signature_ok:
        return _signature_row(height, address, "commit", True, vote_block_id, False, True, signature, None)
    if vote_block_id.is_zero:
        return _signature_row(height, address, "nil", False, vote_block_id, True, False, signature, precommit)
    return _signature_row(height, address, "invalid", False, vote_block_id, False, matches_commit, signature, precommit)


def _precommit_block_id(precommit: dict[str, Any]) -> Any:
    return precommit.get("block_id") or precommit.get("blockID") or precommit.get("BlockID")


def _signature(precommit: dict[str, Any]) -> str | None:
    value = precommit.get("signature")
    return value if isinstance(value, str) else None


SUPPORTED_SIGNATURE_KEY_TYPES = {"/tm.PubKeyEd25519", "/tm.PubKeySecp256k1"}


def _usable_signature(signature: str | None, public_key_type: str | None) -> bool:
    if public_key_type not in SUPPORTED_SIGNATURE_KEY_TYPES:
        return False
    if not signature:
        return False
    try:
        decoded = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(decoded) == 64


def _signature_row(
    height: int,
    address: str,
    status: str,
    signed: bool,
    block_id: NormalizedBlockID | None,
    is_zero: bool,
    matches_commit: bool,
    signature: str | None,
    raw_precommit: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "height": height,
        "signing_address": address,
        "vote_status": status,
        "signed": signed,
        "vote_block_id_hash_base64": block_id.hash_base64 if block_id else None,
        "vote_block_id_hash_hex": block_id.hash_hex if block_id else None,
        "vote_block_id_parts_total": block_id.parts_total if block_id else None,
        "vote_block_id_parts_hash_base64": block_id.parts_hash_base64 if block_id else None,
        "vote_block_id_parts_hash_hex": block_id.parts_hash_hex if block_id else None,
        "vote_block_id_is_zero": is_zero,
        "block_id_matches_commit": matches_commit,
        "signature_base64": signature,
        "raw_precommit": raw_precommit,
    }


MAX_RESULT_TEXT_BYTES = 64 * 1024
MAX_RESULT_JSON_BYTES = 256 * 1024
_MISSING = object()


def _bounded(value: Any, name: str, limit: int = MAX_RESULT_TEXT_BYTES) -> Any:
    if value is None:
        return None
    if not isinstance(value, (str, dict, list)):
        raise RpcError(f"Malformed block_results {name}")
    encoded = json.dumps(value, separators=(",", ":")).encode() if not isinstance(value, str) else value.encode()
    if len(encoded) > limit:
        raise RpcError(f"block_results {name} exceeds {limit} bytes")
    return value


def _gas(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RpcError(f"Malformed block_results {name}")
    if isinstance(value, str) and (not value or not value.isdigit()):
        raise RpcError(f"Malformed block_results {name}")
    parsed = int(value)
    if parsed < 0 or len(str(parsed)) > 78:
        raise RpcError(f"Malformed block_results {name}")
    return parsed


def parse_execution_results(height: int, payload: dict[str, Any], tx_count: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RpcError("Malformed block_results: expected object")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RpcError("Malformed block_results result")
    result_height = result.get("height") or result.get("Height")
    if _gas(result_height, "height") != height:
        raise RpcError(f"block_results height mismatch while parsing {height}")
    results = result.get("results")
    if results is None:
        deliver = None
    elif not isinstance(results, dict):
        raise RpcError("Malformed block_results results")
    else:
        deliver = results.get("deliver_tx", results.get("deliverTx"))
    if deliver is None:
        deliver = []
    if not isinstance(deliver, list) or len(deliver) != tx_count:
        raise RpcError(f"Transaction/result count mismatch at height {height}")
    normalized = []
    for index, item in enumerate(deliver):
        if not isinstance(item, dict):
            raise RpcError(f"Malformed deliver_tx[{index}]")
        base = item.get("ResponseBase", item.get("response_base"))
        if not isinstance(base, dict):
            raise RpcError(f"Malformed deliver_tx[{index}].ResponseBase")
        error = base.get("Error", base.get("error"))
        error_text = None if error is None else (_bounded(error, "Error") if isinstance(error, str) else json.dumps(_bounded(error, "Error"), separators=(",", ":"), sort_keys=True))
        if error_text is not None and not error_text.strip():
            raise RpcError(f"Ambiguous deliver_tx[{index}] error")
        raw = _bounded(item, "raw_result", MAX_RESULT_JSON_BYTES)
        normalized.append({
            "block_height": height, "tx_index": index,
            "execution_status": "success" if error is None else "failed",
            "gas_wanted": _gas(item.get("GasWanted", item.get("gas_wanted")), "GasWanted"),
            "gas_used": _gas(item.get("GasUsed", item.get("gas_used")), "GasUsed"),
            "error_text": error_text,
            "log_text": _bounded(base.get("Log", base.get("log")), "Log"),
            "info_text": _bounded(base.get("Info", base.get("info")), "Info"),
            "data_base64": _bounded(base.get("Data", base.get("data")), "Data"),
            "events": _bounded(base.get("Events", base.get("events")), "Events", MAX_RESULT_JSON_BYTES),
            "raw_result": raw,
        })
    return normalized


def parse_height(height: int, block_payload: dict[str, Any], commit_payload: dict[str, Any], validators_payload: dict[str, Any], transaction_decoder: TransactionDecoder | None = None, block_results_payload: Any = _MISSING) -> ParsedHeight:
    block = parse_block(block_payload, transaction_decoder)
    commit = parse_commit(commit_payload)
    commit["raw"] = commit_payload
    validators_data = parse_validators(validators_payload)
    if block["height"] != height or commit["height"] != height or validators_data["block_height"] != height:
        raise RpcError(f"Height mismatch while parsing {height}")
    signatures = classify_votes(height, commit, validators_data["validators"])
    # The sentinel preserves the parser's historical unit-test API. Runtime callers
    # always provide block_results and therefore cannot omit canonical results.
    execution_results = [] if block_results_payload is _MISSING else parse_execution_results(height, block_results_payload, len(block["transactions"]))
    return ParsedHeight(height, block, block["transactions"], execution_results, validators_data["validators"], signatures, block_payload)
