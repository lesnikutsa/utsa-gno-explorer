"""Parsers for normalized bounded-indexer records."""
from __future__ import annotations

import base64, binascii, json
from dataclasses import dataclass
from typing import Any

from scripts.inspect_rpc import RpcError, decode_base64, parse_block as legacy_parse_block, parse_commit, parse_validators, signer_address, to_int

ZERO_HASHES = {"", "AA==", "AAA=", "AAAA", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}

@dataclass(frozen=True)
class ParsedHeight:
    height: int
    block: dict[str, Any]
    transactions: list[dict[str, Any]]
    validators: list[dict[str, Any]]
    signatures: list[dict[str, Any]]
    raw_block: dict[str, Any]


def parse_tx(index: int, tx: Any) -> dict[str, Any]:
    raw = tx if isinstance(tx, str) else json.dumps(tx, sort_keys=True)
    try:
        decoded = base64.b64decode(raw, validate=True)
        return {"index": index, "raw_base64": raw, "raw_base64_length": len(raw), "decoded_bytes": decoded, "decoded_byte_length": len(decoded), "decode_status": "decoded"}
    except (binascii.Error, ValueError):
        return {"index": index, "raw_base64": raw, "raw_base64_length": len(raw), "decoded_bytes": None, "decoded_byte_length": None, "decode_status": "invalid_base64"}


def parse_block(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = legacy_parse_block(payload)
    txs = (((payload.get("result") or {}).get("block") or {}).get("data") or {}).get("txs") or []
    parsed["transactions"] = [parse_tx(i, tx) for i, tx in enumerate(txs)]
    return parsed


def _block_id(precommit: dict[str, Any]) -> Any:
    return precommit.get("block_id") or precommit.get("blockID") or precommit.get("BlockID")


def _hash(block_id: Any) -> Any:
    if not isinstance(block_id, dict):
        return None
    return block_id.get("hash") or block_id.get("Hash")


def _parts_total(block_id: Any) -> int | None:
    if not isinstance(block_id, dict):
        return None
    parts = block_id.get("parts") or block_id.get("PartsHeader") or block_id.get("parts_header") or {}
    if not isinstance(parts, dict):
        return None
    return to_int(parts.get("total") or parts.get("Total"))


def _is_zero_block_id(block_id: Any) -> bool:
    h = _hash(block_id)
    total = _parts_total(block_id)
    return (h is None or h in ZERO_HASHES) and (total in (None, 0))


def _hash_hex(value: str | None) -> str | None:
    if not value:
        return None
    return decode_base64(value, "Vote.BlockID.hash").hex().upper()


def classify_votes(height: int, commit: dict[str, Any], validators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = {v["address"] for v in validators if v.get("address")}
    commit_block_id = ((commit.get("raw") or {}).get("result") or {}).get("signed_header", {}).get("commit", {}).get("block_id")
    commit_hash = _hash(commit_block_id)
    seen: dict[str, dict[str, Any]] = {}
    invalid: dict[str, dict[str, Any]] = {}
    outside: list[str] = []
    for pc in commit["precommits"]:
        if pc is None:
            continue
        if not isinstance(pc, dict):
            continue
        addr = signer_address(pc)
        if not addr:
            continue
        if addr not in active:
            outside.append(addr); continue
        if addr in seen:
            invalid[addr] = {"reason":"duplicate signer address", "raw_precommit": pc}; continue
        seen[addr] = pc
    rows=[]
    for addr in sorted(active):
        pc = seen.get(addr)
        if addr in invalid:
            pc = invalid[addr]["raw_precommit"]
            rows.append(_row(height, addr, "invalid", False, None, None, None, False, False, pc)); continue
        if pc is None:
            rows.append(_row(height, addr, "absent", False, None, None, None, False, False, None)); continue
        bid = _block_id(pc)
        if not isinstance(bid, dict):
            rows.append(_row(height, addr, "invalid", False, None, None, None, False, False, pc)); continue
        zero = _is_zero_block_id(bid)
        h = _hash(bid)
        parts = _parts_total(bid)
        try:
            hx = _hash_hex(h) if h else None
        except RpcError:
            rows.append(_row(height, addr, "invalid", False, h if isinstance(h,str) else None, None, parts, zero, False, pc)); continue
        matches = bool(h and commit_hash and h == commit_hash)
        sig = pc.get("signature")
        if matches:
            rows.append(_row(height, addr, "commit", True, h, hx, parts, False, True, None, sig))
        elif zero:
            rows.append(_row(height, addr, "nil", False, h if isinstance(h,str) else None, hx, parts, True, False, pc, sig))
        else:
            rows.append(_row(height, addr, "invalid", False, h if isinstance(h,str) else None, hx, parts, False, False, pc, sig))
    if outside:
        raise RpcError(f"Signer outside active validator set: {', '.join(sorted(outside))}")
    return rows


def _row(height, addr, status, signed, h, hx, parts, zero, matches, raw, sig=None):
    return {"height":height,"signing_address":addr,"vote_status":status,"signed":signed,"vote_block_id_hash_base64":h,"vote_block_id_hash_hex":hx,"vote_block_id_parts_total":parts,"vote_block_id_is_zero":zero,"block_id_matches_commit":matches,"signature_base64":sig,"raw_precommit":raw}


def parse_height(height: int, block_payload: dict[str, Any], commit_payload: dict[str, Any], validators_payload: dict[str, Any]) -> ParsedHeight:
    block = parse_block(block_payload)
    commit = parse_commit(commit_payload); commit["raw"] = commit_payload
    vals = parse_validators(validators_payload)
    if block["height"] != height or commit["height"] != height or vals["block_height"] != height:
        raise RpcError(f"Height mismatch while parsing {height}")
    signatures = classify_votes(height, commit, vals["validators"])
    return ParsedHeight(height, block, block["transactions"], vals["validators"], signatures, block_payload)
