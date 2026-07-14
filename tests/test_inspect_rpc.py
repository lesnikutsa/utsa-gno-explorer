import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.inspect_rpc import (
    GnoRpcClient,
    RpcError,
    build_summary,
    configured_max_height_lag,
    configured_rpc_urls,
    fetch_summary,
    parse_block,
    parse_commit,
    parse_status,
    parse_validators,
    select_healthy_rpc,
    signature_signed,
    signer_address,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    def __init__(self, base_url, responses=None, error=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.responses = responses or {}
        self.error = error
        self.calls = []

    def get(self, method, **params):
        self.calls.append((method, params))
        if self.error:
            raise self.error
        return self.responses[method]


class InspectRpcParsingTests(unittest.TestCase):
    def test_parse_status_extracts_chain_height_version_and_sync(self):
        parsed = parse_status(load("status.json"))
        self.assertEqual(parsed["chain_id"], "test-13")
        self.assertEqual(parsed["latest_height"], 123)
        self.assertEqual(parsed["node_version"], "tm2-build-version")
        self.assertFalse(parsed["catching_up"])

    def test_status_prefers_build_version_but_falls_back_to_node_info_version(self):
        status = load("status.json")
        status["result"].pop("build_version")
        self.assertEqual(parse_status(status)["node_version"], "node-fallback-version")

    def test_validators_response_requires_block_height(self):
        validators = load("validators.json")
        validators["result"].pop("block_height")
        with self.assertRaisesRegex(RpcError, "missing result.block_height"):
            parse_validators(validators)

    def test_commit_height_is_derived_from_signed_header_header_height(self):
        commit = load("commit.json")
        commit["result"]["signed_header"]["commit"]["height"] = "999"
        self.assertEqual(parse_commit(commit)["height"], 122)

    def test_commit_canonical_must_be_boolean(self):
        commit = load("commit.json")
        commit["result"]["canonical"] = {"height": "122"}
        with self.assertRaisesRegex(RpcError, "canonical must be a boolean"):
            parse_commit(commit)

    def test_parse_block_does_not_treat_last_commit_as_commit_for_block_height(self):
        parsed = parse_block(load("block.json"))
        self.assertNotIn("commit_signatures", parsed)
        self.assertEqual(parsed["height"], 123)
        self.assertEqual(parsed["tx_count"], 2)
        self.assertEqual(parsed["hash_base64"], "AQIDBA==")
        self.assertEqual(parsed["hash_hex"], "01020304")
        self.assertTrue(parsed["transactions"][0]["base64_decoded"])
        self.assertEqual(parsed["transactions"][0]["decoded_size_bytes"], 5)

    def test_block_hash_requires_valid_base64(self):
        block = load("block.json")
        block["result"]["block_meta"]["block_id"]["hash"] = "not base64!!!"
        with self.assertRaisesRegex(RpcError, "invalid base64"):
            parse_block(block)

    def test_block_hash_is_required(self):
        block = load("block.json")
        del block["result"]["block_meta"]["block_id"]["hash"]
        with self.assertRaisesRegex(RpcError, "missing result.block_meta.block_id.hash"):
            parse_block(block)

    def test_malformed_transaction_base64_is_marked_not_decoded(self):
        block = load("block.json")
        block["result"]["block"]["data"]["txs"] = ["not base64!!!"]
        block["result"]["block"]["header"]["num_txs"] = "1"
        tx = parse_block(block)["transactions"][0]
        self.assertEqual(tx["raw_base64"], "not base64!!!")
        self.assertEqual(tx["encoded_size_chars"], 13)
        self.assertFalse(tx["base64_decoded"])
        self.assertEqual(tx["decoded_size_bytes"], 0)

    def test_block_num_txs_must_match_data_txs_length(self):
        block = load("block.json")
        block["result"]["block"]["header"]["num_txs"] = "3"
        with self.assertRaisesRegex(RpcError, "transaction count mismatch"):
            parse_block(block)

    def test_parse_commit_reads_real_tm2_shape_and_canonical(self):
        parsed = parse_commit(load("commit.json"))
        self.assertEqual(parsed["height"], 122)
        self.assertEqual(parsed["header_height"], 122)
        self.assertIs(parsed["canonical"], True)
        self.assertEqual(len(parsed["precommits"]), 3)

    def test_parse_validators_extracts_block_height_addresses_and_power(self):
        validators = parse_validators(load("validators.json"))
        self.assertEqual(validators["block_height"], 122)
        self.assertEqual(validators["validators"][0]["address"], "VAL1")
        self.assertEqual(validators["validators"][0]["pub_key_type"], "/tm.PubKeyEd25519")
        self.assertEqual(validators["validators"][0]["pub_key_display_type"], "Ed25519")
        self.assertEqual(validators["validators"][1]["voting_power"], 20)

    def test_null_precommit_helpers_are_safe(self):
        self.assertIsNone(signer_address(None))
        self.assertIsNone(signer_address("bad"))
        self.assertFalse(signature_signed(None))
        self.assertFalse(signature_signed("bad"))

    def test_build_summary_uses_h_minus_one_and_handles_signed_and_missed(self):
        summary = build_summary("http://rpc", load("status.json"), load("block.json"), load("commit.json"), load("validators.json"))
        self.assertEqual(summary.latest_height, 123)
        self.assertEqual(summary.signing_height, 122)
        self.assertEqual(summary.commit_height, 122)
        self.assertEqual(summary.validators_height, 122)
        self.assertEqual([v["address"] for v in summary.signed_validators], ["VAL1"])
        self.assertEqual([v["address"] for v in summary.missed_validators], ["VAL2", "VAL3"])

    def test_height_mismatch_between_commit_and_validators_fails(self):
        validators = load("validators.json")
        validators["result"]["block_height"] = "121"
        with self.assertRaisesRegex(RpcError, "Validator-set height mismatch"):
            build_summary("http://rpc", load("status.json"), load("block.json"), load("commit.json"), validators)

    def test_malformed_commit_response_fails_clearly(self):
        with self.assertRaisesRegex(RpcError, "Malformed commit response"):
            parse_commit({"result": {"signed_header": {"header": {"height": "122"}}}})

    def test_fetch_summary_requests_block_h_commit_h_minus_one_and_validators_h_minus_one(self):
        client = FakeClient("http://rpc", {"block": load("block.json"), "commit": load("commit.json"), "validators": load("validators.json")})
        summary = fetch_summary(client, load("status.json"))
        self.assertEqual(summary.signing_height, 122)
        self.assertEqual(client.calls[0], ("block", {"height": 123}))
        self.assertEqual(client.calls[1], ("commit", {"height": 122}))
        self.assertEqual(client.calls[2], ("validators", {"height": 122}))


class RpcSelectionTests(unittest.TestCase):
    def test_one_failed_rpc_followed_by_working_fallback(self):
        clients = [FakeClient("http://bad", error=RpcError("down")), FakeClient("http://good", {"status": load("status.json")})]
        with patch("scripts.inspect_rpc.GnoRpcClient", side_effect=clients):
            selected, status = select_healthy_rpc(["http://bad", "http://good"], expected_chain_id="test-13", max_height_lag=10)
        self.assertIs(selected, clients[1])
        self.assertEqual(parse_status(status)["latest_height"], 123)

    def test_all_rpc_endpoints_unavailable(self):
        with patch("scripts.inspect_rpc.GnoRpcClient", return_value=FakeClient("http://bad", error=RpcError("down"))):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://bad"], expected_chain_id="test-13", max_height_lag=10)

    def test_catching_up_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["sync_info"]["catching_up"] = True
        with patch("scripts.inspect_rpc.GnoRpcClient", return_value=FakeClient("http://syncing", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://syncing"], expected_chain_id="test-13", max_height_lag=10)

    def test_wrong_chain_id_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["node_info"]["network"] = "wrong-chain"
        with patch("scripts.inspect_rpc.GnoRpcClient", return_value=FakeClient("http://wrong", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected"):
                select_healthy_rpc(["http://wrong"], expected_chain_id="test-13", max_height_lag=10)

    def test_malformed_status_endpoint_rejected(self):
        status = load("status.json")
        status["result"]["sync_info"].pop("latest_block_height")
        with patch("scripts.inspect_rpc.GnoRpcClient", return_value=FakeClient("http://bad-status", {"status": status})):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected"):
                select_healthy_rpc(["http://bad-status"], expected_chain_id="test-13", max_height_lag=10)

    def test_first_endpoint_stale_second_endpoint_current_selected(self):
        stale = load("status.json")
        stale["result"]["sync_info"]["latest_block_height"] = "100"
        current = load("status.json")
        current["result"]["sync_info"]["latest_block_height"] = "120"
        clients = [FakeClient("http://stale", {"status": stale}), FakeClient("http://current", {"status": current})]
        with patch("scripts.inspect_rpc.GnoRpcClient", side_effect=clients):
            selected, status = select_healthy_rpc(["http://stale", "http://current"], expected_chain_id="test-13", max_height_lag=10)
        self.assertIs(selected, clients[1])
        self.assertEqual(parse_status(status)["latest_height"], 120)

    def test_all_endpoints_rejected_when_none_are_healthy(self):
        wrong_chain = load("status.json")
        wrong_chain["result"]["node_info"]["network"] = "wrong-chain"
        malformed = load("status.json")
        malformed["result"]["sync_info"].pop("latest_block_height")
        clients = [FakeClient("http://wrong", {"status": wrong_chain}), FakeClient("http://malformed", {"status": malformed})]
        with patch("scripts.inspect_rpc.GnoRpcClient", side_effect=clients):
            with self.assertRaisesRegex(RpcError, "All RPC endpoints are rejected or unavailable"):
                select_healthy_rpc(["http://wrong", "http://malformed"], expected_chain_id="test-13", max_height_lag=10)

    def test_configured_max_height_lag_from_env(self):
        with patch.dict(os.environ, {"RPC_MAX_HEIGHT_LAG": "7"}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                self.assertEqual(configured_max_height_lag(), 7)

    def test_legacy_gno_rpc_url_support(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"GNO_RPC_URL": "http://legacy"}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                self.assertEqual(configured_rpc_urls(), ["http://legacy"])

    def test_env_file_and_ordered_gno_rpc_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {}, clear=True):
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("GNO_RPC_URLS=http://one,http://two\n")
            with patch("scripts.inspect_rpc.Path", return_value=env_path):
                self.assertEqual(configured_rpc_urls(), ["http://one", "http://two"])


if __name__ == "__main__":
    unittest.main()
