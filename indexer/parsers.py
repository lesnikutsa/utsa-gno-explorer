"""Parsers for normalized bounded-indexer records."""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

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
    validators: list[dict[str, Any]]
    signatures: list[dict[str, Any]]
    raw_block: dict[str, Any]


def parse_tx(index: int, tx: Any) -> dict[str, Any]:
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
        }
    return {
        "index": index,
        "raw_base64": raw_base64,
        "raw_base64_length": len(raw_base64),
        "decoded_bytes": decoded,
        "decoded_byte_length": len(decoded),
        "decode_status": "decoded",
    }


def parse_block(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = legacy_parse_block(payload)
    txs = (((payload.get("result") or {}).get("block") or {}).get("data") or {}).get("txs") or []
    parsed["transactions"] = [parse_tx(index, tx) for index, tx in enumerate(txs)]
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
    return _signature_row(height, address, "invalid", False, vote_block_id, False, False, signature, precommit)


def _precommit_block_id(precommit: dict[str, Any]) -> Any:
    return precommit.get("block_id") or precommit.get("blockID") or precommit.get("BlockID")


def _signature(precommit: dict[str, Any]) -> str | None:
    value = precommit.get("signature")
    return value if isinstance(value, str) else None


def _usable_signature(signature: str | None, public_key_type: str | None) -> bool:
    if public_key_type != "/tm.PubKeyEd25519":
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


def parse_height(height: int, block_payload: dict[str, Any], commit_payload: dict[str, Any], validators_payload: dict[str, Any]) -> ParsedHeight:
    block = parse_block(block_payload)
    commit = parse_commit(commit_payload)
    commit["raw"] = commit_payload
    validators_data = parse_validators(validators_payload)
    if block["height"] != height or commit["height"] != height or validators_data["block_height"] != height:
        raise RpcError(f"Height mismatch while parsing {height}")
    signatures = classify_votes(height, commit, validators_data["validators"])
    return ParsedHeight(height, block, block["transactions"], validators_data["validators"], signatures, block_payload)
