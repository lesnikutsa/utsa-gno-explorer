"""Strict, bounded normalization for an on-demand CometBFT block detail."""

import base64
import hashlib

from .errors import MalformedUpstreamResponse
from .parsing import _height, _hex, _identity, _mapping, _timestamp

MAX_SIGNATURES = 200
MAX_TXS = 10_000
MAX_EVIDENCE = 20


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isdigit():
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if result > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def _optional_hash(header, name):
    value = header.get(name)
    return _hex(value, name, 128) if value else None


def normalize_detail(block_payload, commit_payload, results_payload, *, network_id,
                     expected_chain_id, requested_height, local_height, identities):
    result = _mapping(_mapping(block_payload).get("result"))
    block_id = _mapping(result.get("block_id"))
    block = _mapping(result.get("block"))
    header = _mapping(block.get("header"))
    _identity(header.get("chain_id"), expected_chain_id)
    height = _height(header.get("height"))
    if height != requested_height:
        raise MalformedUpstreamResponse("wrong block height")

    commit_result = _mapping(_mapping(commit_payload).get("result"))
    signed_header = _mapping(commit_result.get("signed_header"))
    commit_header = _mapping(signed_header.get("header"))
    _identity(commit_header.get("chain_id"), expected_chain_id)
    if _height(commit_header.get("height")) != height:
        raise MalformedUpstreamResponse("wrong commit height")
    commit = _mapping(signed_header.get("commit"))
    if _height(commit.get("height")) != height:
        raise MalformedUpstreamResponse("wrong commit height")
    block_hash = _hex(block_id.get("hash"), "block hash", 128)
    commit_block_hash = _hex(_mapping(commit.get("block_id")).get("hash"), "commit block hash", 128)
    if commit_block_hash != block_hash:
        raise MalformedUpstreamResponse("commit block hash does not match block")
    raw_signatures = commit.get("signatures", [])
    if not isinstance(raw_signatures, list) or len(raw_signatures) > MAX_SIGNATURES:
        raise MalformedUpstreamResponse("invalid commit signatures")
    signatures = []
    counts = {"signed": 0, "nil": 0, "absent": 0, "unknown": 0}
    statuses = {1: "absent", 2: "signed", 3: "nil"}
    for raw in raw_signatures:
        item = _mapping(raw)
        flag = _integer(item.get("block_id_flag"), "block id flag")
        if not 1 <= flag <= 255:
            raise MalformedUpstreamResponse("invalid block id flag")
        status = statuses.get(flag, "unknown")
        counts[status] += 1
        address = _hex(item.get("validator_address"), "validator address", 128) if item.get("validator_address") else None
        timestamp = _timestamp(item.get("timestamp")) if item.get("timestamp") else None
        signature = item.get("signature") or None
        if signature is not None:
            if not isinstance(signature, str) or len(signature) > 256:
                raise MalformedUpstreamResponse("invalid signature")
            try:
                if len(base64.b64decode(signature, validate=True)) > 96:
                    raise ValueError
            except (ValueError, TypeError):
                raise MalformedUpstreamResponse("invalid signature") from None
        identity = identities.get(address.upper(), {}) if address else {}
        signatures.append({"validator_address": address, "status": status, "block_id_flag": flag,
                           "timestamp": timestamp, "signature": signature, **identity})

    data = _mapping(block.get("data", {}))
    raw_txs = data.get("txs") or []
    if not isinstance(raw_txs, list) or len(raw_txs) > MAX_TXS:
        raise MalformedUpstreamResponse("invalid transactions")
    results = _mapping(_mapping(results_payload).get("result"))
    if _height(results.get("height")) != height:
        raise MalformedUpstreamResponse("wrong block results height")
    tx_results = results.get("txs_results") or []
    if not isinstance(tx_results, list) or len(tx_results) != len(raw_txs):
        raise MalformedUpstreamResponse("transaction results do not match transactions")
    transactions = []
    for index, (encoded, raw_result) in enumerate(zip(raw_txs, tx_results)):
        if not isinstance(encoded, str) or len(encoded) > 2_000_000:
            raise MalformedUpstreamResponse("invalid transaction bytes")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise MalformedUpstreamResponse("invalid transaction base64") from None
        tx_result = _mapping(raw_result)
        code = _integer(tx_result.get("code", 0), "transaction code")
        transactions.append({"index": index, "hash": hashlib.sha256(decoded).hexdigest().upper(),
                             "status": "success" if code == 0 else "failed",
                             "gas_used": _integer(tx_result.get("gas_used"), "gas used") if tx_result.get("gas_used") is not None else None,
                             "gas_wanted": _integer(tx_result.get("gas_wanted"), "gas wanted") if tx_result.get("gas_wanted") is not None else None})

    evidence_list = _mapping(block.get("evidence", {})).get("evidence") or []
    if not isinstance(evidence_list, list) or len(evidence_list) > MAX_EVIDENCE:
        raise MalformedUpstreamResponse("invalid evidence")
    evidence = []
    for raw in evidence_list:
        item = _mapping(raw)
        kind = item.get("type") or item.get("@type")
        if not isinstance(kind, str) or not 1 <= len(kind) <= 128:
            raise MalformedUpstreamResponse("invalid evidence type")
        evidence.append({"type": kind, "height": _height(item.get("height")) if item.get("height") else None,
                         "time": _timestamp(item.get("time")) if item.get("time") else None})

    proposer = _hex(header.get("proposer_address"), "proposer address", 128)
    proposer_match = identities.get(proposer.upper(), {})
    proposer_identity = {"proposer_moniker": proposer_match.get("moniker"),
                         "proposer_operator_address": proposer_match.get("operator_address"),
                         "proposer_identity": proposer_match.get("identity")} if proposer_match else {}
    version = _mapping(header.get("version"))
    return {"network_id": network_id, "chain_id": expected_chain_id, "local_height": local_height,
            "height": height, "timestamp": _timestamp(header.get("time")),
            "transaction_count": len(transactions), "block_version": _integer(version.get("block"), "block version"),
            "app_version": _integer(version.get("app", 0), "app version"), "proposer": proposer,
            **proposer_identity, "hashes": {"block": block_hash,
                "last_block": _optional_hash(_mapping(header.get("last_block_id", {})), "hash"),
                "last_commit": _optional_hash(header, "last_commit_hash"), "data": _optional_hash(header, "data_hash"),
                "validators": _hex(header.get("validators_hash"), "validators hash", 128),
                "next_validators": _hex(header.get("next_validators_hash"), "next validators hash", 128),
                "consensus": _hex(header.get("consensus_hash"), "consensus hash", 128),
                "app": _optional_hash(header, "app_hash"), "last_results": _optional_hash(header, "last_results_hash"),
                "evidence": _optional_hash(header, "evidence_hash")},
            "commit": {"validators": len(signatures), **counts, "missed": counts["nil"] + counts["absent"]},
            "signatures": signatures, "transactions": transactions, "evidence": evidence}
