import base64
import hashlib

import pytest

from api.cosmos.block_detail import normalize_detail
from api.cosmos.errors import MalformedUpstreamResponse, RejectedEndpoint
from api.cosmos.schemas import BlockDetailResponse

HEX = "AB" * 32
TIME = "2026-08-31T11:12:28Z"


def payloads(txs=None, tx_results=None, signatures=None, evidence=None):
    txs = [] if txs is None else txs
    tx_results = [] if tx_results is None else tx_results
    signatures = [] if signatures is None else signatures
    header = {"version": {"block": "11", "app": "3"}, "chain_id": "atomone-1", "height": "10",
              "time": TIME, "last_block_id": {"hash": HEX}, "last_commit_hash": HEX,
              "data_hash": HEX, "validators_hash": HEX, "next_validators_hash": HEX,
              "consensus_hash": HEX, "app_hash": HEX, "last_results_hash": HEX,
              "evidence_hash": HEX, "proposer_address": "CD" * 20}
    block = {"result": {"block_id": {"hash": HEX}, "block": {"header": header,
             "data": {"txs": txs}, "evidence": {"evidence": evidence or []},
             "last_commit": {"signatures": [{"block_id_flag": 2}]}}}}
    current_commit = {"result": {"signed_header": {"header": header,
                      "commit": {"height": "10", "signatures": signatures}}}}
    results = {"result": {"height": "10", "txs_results": tx_results}}
    return block, current_commit, results


def normalize(*payload):
    return normalize_detail(*payload, network_id="atomone-mainnet", expected_chain_id="atomone-1",
                            requested_height=10, local_height=12,
                            identities={"CD" * 20: {"moniker": "KalpaTech", "operator_address": "atonevaloper1abc"},
                                        "EF" * 20: {"moniker": "Signer"}})


def test_current_commit_flags_summary_and_identity_are_normalized():
    signatures = [
        {"block_id_flag": 2, "validator_address": "EF" * 20, "timestamp": TIME,
         "signature": base64.b64encode(b"x" * 64).decode()},
        {"block_id_flag": 3, "validator_address": "01" * 20, "timestamp": TIME},
        {"block_id_flag": 1}, {"block_id_flag": 9, "validator_address": "02" * 20},
    ]
    detail = normalize(*payloads(signatures=signatures))
    assert detail["commit"] == {"validators": 4, "signed": 1, "nil": 1, "absent": 1,
                                "unknown": 1, "missed": 2}
    assert detail["signatures"][0]["moniker"] == "Signer"
    assert detail["signatures"][1].get("moniker") is None
    assert detail["proposer_moniker"] == "KalpaTech"
    BlockDetailResponse.model_validate(detail)
    # The sentinel previous-block last_commit is deliberately never read.
    assert len(detail["signatures"]) == len(signatures)


def test_tx_hash_and_result_index_correlation():
    raw = b"strict cosmos transaction"
    detail = normalize(*payloads(
        txs=[base64.b64encode(raw).decode()],
        tx_results=[{"code": 0, "gas_used": "84321", "gas_wanted": "90000"}]))
    assert detail["transactions"] == [{"index": 0, "hash": hashlib.sha256(raw).hexdigest().upper(),
                                       "status": "success", "gas_used": 84321, "gas_wanted": 90000}]


@pytest.mark.parametrize("txs,results", [(["not base64!"], [{"code": 0}]),
                                           ([base64.b64encode(b"x").decode()], [])])
def test_invalid_base64_or_mismatched_results_are_rejected(txs, results):
    with pytest.raises(MalformedUpstreamResponse):
        normalize(*payloads(txs=txs, tx_results=results))


def test_zero_transactions_and_absent_evidence_are_compact():
    detail = normalize(*payloads())
    assert detail["transactions"] == []
    assert detail["evidence"] == []


def test_evidence_is_bounded_and_wrong_chain_or_height_is_rejected():
    evidence = [{"type": "duplicate_vote", "height": "9", "time": TIME}]
    assert normalize(*payloads(evidence=evidence))["evidence"][0] == {"type": "duplicate_vote", "height": 9, "time": "2026-08-31T11:12:28.000000Z"}
    block, commit, results = payloads(evidence=evidence * 21)
    with pytest.raises(MalformedUpstreamResponse):
        normalize(block, commit, results)
    block, commit, results = payloads()
    commit["result"]["signed_header"]["header"]["chain_id"] = "wrong-1"
    with pytest.raises((MalformedUpstreamResponse, RejectedEndpoint)):
        normalize(block, commit, results)
