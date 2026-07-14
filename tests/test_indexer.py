import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from indexer.database import ChainIdentityError, DatabaseError, FinalizedDataConflict
from indexer.parsers import parse_height
from indexer.rpc import RpcProbeResult, select_rpc
from indexer.service import IndexerService, plan_range
from scripts.inspect_rpc import RpcError

FIXTURES = Path(__file__).parent / "fixtures"
COMMIT_HASH = "AQIDBA=="
PARTS_HASH = "BQYHCA=="
VALID_SIGNATURE = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4vMDEyMzQ1Njc4OTo7PD0+Pw=="


def load(name):
    return json.loads((FIXTURES / name).read_text())


def payloads(height=122):
    block = load("block.json")
    commit = load("commit.json")
    validators = load("validators.json")
    block_id = {"hash": COMMIT_HASH, "parts": {"total": "1", "hash": PARTS_HASH}}
    block["result"]["block"]["header"]["height"] = str(height)
    block["result"]["block_meta"]["block_id"]["hash"] = COMMIT_HASH
    commit["result"]["signed_header"]["header"]["height"] = str(height)
    commit["result"]["signed_header"]["commit"]["block_id"] = copy.deepcopy(block_id)
    commit["result"]["signed_header"]["commit"]["precommits"] = [
        {"validator_address": "VAL1", "signature": VALID_SIGNATURE, "block_id": copy.deepcopy(block_id)},
        None,
        {"validator_address": "VAL3", "signature": "c2lnMw==", "block_id": {"hash": "", "parts": {"total": "0"}}},
    ]
    validators["result"]["block_height"] = str(height)
    return block, commit, validators


class FakeRpc:
    base_url = "http://rpc/"

    def __init__(self, by_height):
        self.by_height = by_height
        self.calls = []

    def get(self, method, **params):
        self.calls.append((method, params))
        return self.by_height[params["height"]][method]


class SqlLikeDb:
    def __init__(self, checkpoint=None, chain_id="test-13", fail_height=None):
        self.checkpoint = checkpoint
        self.chain_id = chain_id
        self.fail_height = fail_height
        self.blocks = {}
        self.transactions = {}
        self.validators = {}
        self.members = {}
        self.signatures = {}
        self.probe_cycles = []

    def get_checkpoint(self, chain_id):
        if self.checkpoint is None:
            return None
        if self.chain_id != chain_id:
            raise ChainIdentityError("wrong chain")
        return self.checkpoint

    def record_rpc_probe_cycle(self, chain_id, probes):
        if self.chain_id != chain_id:
            raise ChainIdentityError("wrong chain")
        self.probe_cycles.append(list(probes))

    def write_height(self, parsed, chain_id, finalized_tip):
        if self.fail_height == parsed.height:
            raise RuntimeError("injected db failure")
        if self.chain_id != chain_id:
            raise ChainIdentityError("wrong chain")
        if self.checkpoint is not None and parsed.height > self.checkpoint + 1:
            raise DatabaseError("skip")
        self._check_conflicts(parsed)
        self.blocks[parsed.height] = (parsed.block["hash_base64"], parsed.block["hash_hex"])
        for tx in parsed.transactions:
            self.transactions[(parsed.height, tx["index"])] = (tx["raw_base64"], tx["decode_status"])
        for validator in parsed.validators:
            self.validators[validator["address"]] = (validator.get("pub_key_type") or "unknown", validator.get("pub_key_value") or "")
            self.members[(parsed.height, validator["address"])] = (validator.get("voting_power") or 0, validator.get("proposer_priority"), parsed.validators.index(validator))
        for signature in parsed.signatures:
            self.signatures[(parsed.height, signature["signing_address"])] = (
                signature["vote_status"],
                signature["signed"],
                signature["vote_block_id_hash_base64"],
                signature["vote_block_id_hash_hex"],
                signature["vote_block_id_parts_total"],
                signature["vote_block_id_parts_hash_base64"],
                signature["vote_block_id_parts_hash_hex"],
                signature["vote_block_id_is_zero"],
                signature["block_id_matches_commit"],
                signature["signature_base64"],
            )
        if self.checkpoint is None or parsed.height == self.checkpoint + 1:
            self.checkpoint = parsed.height

    def _check_conflicts(self, parsed):
        if parsed.height in self.blocks and self.blocks[parsed.height] != (parsed.block["hash_base64"], parsed.block["hash_hex"]):
            raise FinalizedDataConflict("block")
        if parsed.height in self.blocks:
            incoming_tx_keys = {(parsed.height, tx["index"]) for tx in parsed.transactions}
            existing_tx_keys = {key for key in self.transactions if key[0] == parsed.height}
            if incoming_tx_keys != existing_tx_keys:
                raise FinalizedDataConflict("transaction set")
            incoming_member_keys = {(parsed.height, validator["address"]) for validator in parsed.validators}
            existing_member_keys = {key for key in self.members if key[0] == parsed.height}
            if incoming_member_keys != existing_member_keys:
                raise FinalizedDataConflict("member set")
            incoming_signature_keys = {(parsed.height, signature["signing_address"]) for signature in parsed.signatures}
            existing_signature_keys = {key for key in self.signatures if key[0] == parsed.height}
            if incoming_signature_keys != existing_signature_keys:
                raise FinalizedDataConflict("signature set")
        for tx in parsed.transactions:
            key = (parsed.height, tx["index"])
            if key in self.transactions and self.transactions[key] != (tx["raw_base64"], tx["decode_status"]):
                raise FinalizedDataConflict("transaction")
        for validator in parsed.validators:
            key = validator["address"]
            expected = (validator.get("pub_key_type") or "unknown", validator.get("pub_key_value") or "")
            if key in self.validators and self.validators[key] != expected:
                raise FinalizedDataConflict("validator")
            member_key = (parsed.height, validator["address"])
            member_expected = (validator.get("voting_power") or 0, validator.get("proposer_priority"), parsed.validators.index(validator))
            if member_key in self.members and self.members[member_key] != member_expected:
                raise FinalizedDataConflict("member")
        for signature in parsed.signatures:
            key = (parsed.height, signature["signing_address"])
            expected = (
                signature["vote_status"],
                signature["signed"],
                signature["vote_block_id_hash_base64"],
                signature["vote_block_id_hash_hex"],
                signature["vote_block_id_parts_total"],
                signature["vote_block_id_parts_hash_base64"],
                signature["vote_block_id_parts_hash_hex"],
                signature["vote_block_id_is_zero"],
                signature["block_id_matches_commit"],
                signature["signature_base64"],
            )
            if key in self.signatures and self.signatures[key] != expected:
                raise FinalizedDataConflict("signature")


class CliSmokeTests(unittest.TestCase):
    def test_write_mode_rejects_empty_database_url(self):
        from indexer.database import PostgresDatabase

        with self.assertRaisesRegex(DatabaseError, "DATABASE_URL is required"):
            PostgresDatabase("").connect()

    def test_documented_script_command_help_runs_from_repo_root(self):
        env = {"PATH": os.environ["PATH"], "PYTHONPATH": ""}
        result = subprocess.run(
            [sys.executable, "scripts/index_range.py", "--help"],
            cwd=Path(__file__).parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--start-height", result.stdout)


class RangeTests(unittest.TestCase):
    def test_bounded_range_validation_and_finalized_tip(self):
        with self.assertRaisesRegex(ValueError, "hard limit"):
            plan_range(None, 1, 101, None, 200, 100, False)
        with self.assertRaisesRegex(ValueError, "above finalized_tip"):
            plan_range(None, 1, 11, None, 10, 100, False)

    def test_empty_database_initialization_requires_start_height(self):
        with self.assertRaisesRegex(ValueError, "start-height"):
            plan_range(None, None, None, 10, 20, 100, False)
        self.assertEqual(plan_range(None, 5, None, 2, 20, 100, False).end_height, 6)

    def test_explicit_gap_is_rejected_but_reprocessing_is_allowed(self):
        with self.assertRaisesRegex(ValueError, "skip checkpoint"):
            plan_range(100, 110, 110, None, 200, 100, False)
        self.assertEqual(plan_range(100, 90, 90, None, 200, 100, False).start_height, 90)


class ParserTests(unittest.TestCase):
    def statuses(self, commit_payload=None):
        block, base_commit, validators = payloads()
        commit = commit_payload or base_commit
        return {row["signing_address"]: row for row in parse_height(122, block, commit, validators).signatures}

    def test_commit_nil_absent_and_signed_rules(self):
        signatures = self.statuses()
        self.assertEqual(signatures["VAL1"]["vote_status"], "commit")
        self.assertTrue(signatures["VAL1"]["signed"])
        self.assertEqual(signatures["VAL2"]["vote_status"], "absent")
        self.assertEqual(signatures["VAL3"]["vote_status"], "nil")

    def test_full_block_id_mismatch_is_invalid(self):
        _, commit, _ = payloads()
        commit["result"]["signed_header"]["commit"]["precommits"][0]["block_id"]["parts"]["hash"] = "CQkJCQ=="
        self.assertEqual(self.statuses(commit)["VAL1"]["vote_status"], "invalid")

    def test_complete_block_id_validation(self):
        self.assertEqual(self.statuses()["VAL1"]["vote_status"], "commit")
        for field in ("total", "hash"):
            _, commit, _ = payloads()
            commit["result"]["signed_header"]["commit"]["precommits"][0]["block_id"]["parts"].pop(field)
            self.assertEqual(self.statuses(commit)["VAL1"]["vote_status"], "invalid")
        _, commit, _ = payloads()
        commit["result"]["signed_header"]["commit"]["precommits"][0]["block_id"]["parts"]["hash"] = "not base64!!!"
        self.assertEqual(self.statuses(commit)["VAL1"]["vote_status"], "invalid")
        block, commit, validators = payloads()
        commit["result"]["signed_header"]["commit"]["block_id"]["parts"].pop("hash")
        with self.assertRaisesRegex(RpcError, "Commit.BlockID"):
            parse_height(122, block, commit, validators)

    def test_signature_correctness(self):
        for value in (None, "", "not base64!!!", "c2hvcnQ=", "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4vMDEyMzQ1Njc4OTo7PD0+P0A="):
            _, commit, _ = payloads()
            if value is None:
                commit["result"]["signed_header"]["commit"]["precommits"][0].pop("signature")
            else:
                commit["result"]["signed_header"]["commit"]["precommits"][0]["signature"] = value
            self.assertEqual(self.statuses(commit)["VAL1"]["vote_status"], "invalid")
        block, commit, validators = payloads()
        validators["result"]["validators"][0]["pub_key"]["@type"] = "/tm.PubKeyUnknown"
        self.assertEqual(parse_height(122, block, commit, validators).signatures[0]["vote_status"], "invalid")
        self.assertEqual(self.statuses()["VAL1"]["vote_status"], "commit")

    def test_duplicate_signer_and_signer_outside_set(self):
        _, commit, _ = payloads()
        commit["result"]["signed_header"]["commit"]["precommits"].append(copy.deepcopy(commit["result"]["signed_header"]["commit"]["precommits"][0]))
        self.assertEqual(self.statuses(commit)["VAL1"]["vote_status"], "invalid")
        _, commit, validators = payloads()
        commit["result"]["signed_header"]["commit"]["precommits"].append({"validator_address": "NOPE", "block_id": {"hash": COMMIT_HASH, "parts": {"total": "1", "hash": PARTS_HASH}}})
        block, _, _ = payloads()
        with self.assertRaisesRegex(RpcError, "outside active"):
            parse_height(122, block, commit, validators)

    def test_malformed_precommits_fail_clearly(self):
        for bad in ("bad", {"signature": VALID_SIGNATURE}):
            block, commit, validators = payloads()
            commit["result"]["signed_header"]["commit"]["precommits"].append(bad)
            with self.assertRaisesRegex(RpcError, "Malformed non-null precommit"):
                parse_height(122, block, commit, validators)

    def test_transaction_count_mismatch_and_base64_status(self):
        block, commit, validators = payloads()
        block["result"]["block"]["data"]["txs"] = ["b2s=", "not base64!!!"]
        block["result"]["block"]["header"]["num_txs"] = "2"
        transactions = parse_height(122, block, commit, validators).transactions
        self.assertEqual([tx["decode_status"] for tx in transactions], ["decoded", "invalid_base64"])
        block["result"]["block"]["header"]["num_txs"] = "3"
        with self.assertRaisesRegex(RpcError, "transaction count mismatch"):
            parse_height(122, block, commit, validators)


class ServiceAndDatabaseSemanticsTests(unittest.TestCase):
    def service(self, db, heights):
        by_height = {height: dict(zip(["block", "commit", "validators"], payloads(height))) for height in heights}
        probes = [RpcProbeResult(url="http://rpc", healthy=True, selected=True, chain_id="test-13", latest_height=130, observed_lag=0)]
        return IndexerService(FakeRpc(by_height), db, "test-13", 130, probes)

    def test_checkpoint_advances_sequentially_and_probe_cycle_once(self):
        db = SqlLikeDb(checkpoint=121)
        self.service(db, [122, 123]).run(plan_range(121, None, 123, None, 130, 100, False))
        self.assertEqual(db.checkpoint, 123)
        self.assertEqual(len(db.probe_cycles), 1)

    def test_old_height_reprocessing_does_not_move_checkpoint_backwards(self):
        db = SqlLikeDb(checkpoint=130)
        self.service(db, [122]).run(plan_range(130, 122, 122, None, 130, 100, False))
        self.assertEqual(db.checkpoint, 130)

    def test_failed_height_leaves_checkpoint_unchanged(self):
        db = SqlLikeDb(checkpoint=121, fail_height=122)
        with self.assertRaises(RuntimeError):
            self.service(db, [122]).run(plan_range(121, None, 122, None, 130, 100, False))
        self.assertEqual(db.checkpoint, 121)

    def test_finalized_conflicts_block_transaction_member_signature(self):
        db = SqlLikeDb(checkpoint=121)
        service = self.service(db, [122])
        service.run(plan_range(121, None, 122, None, 130, 100, False))
        for mutate in (
            "block",
            "transaction",
            "missing_transaction",
            "extra_transaction",
            "member",
            "missing_member",
            "extra_member",
            "changed_validator_index",
            "signature",
            "missing_signature",
            "extra_signature",
        ):
            block, commit, validators = payloads(122)
            if mutate == "block":
                block["result"]["block_meta"]["block_id"]["hash"] = "AgMEBQ=="
            if mutate == "transaction":
                block["result"]["block"]["data"]["txs"][0] = "bmV3"
            if mutate == "missing_transaction":
                block["result"]["block"]["data"]["txs"].pop()
                block["result"]["block"]["header"]["num_txs"] = "1"
            if mutate == "extra_transaction":
                block["result"]["block"]["data"]["txs"].append("ZXh0cmE=")
                block["result"]["block"]["header"]["num_txs"] = "3"
            if mutate == "member":
                validators["result"]["validators"][0]["voting_power"] = "999"
            if mutate == "missing_member":
                validators["result"]["validators"].pop()
                commit["result"]["signed_header"]["commit"]["precommits"].pop()
            if mutate == "extra_member":
                extra = copy.deepcopy(validators["result"]["validators"][0])
                extra["address"] = "VAL4"
                extra["pub_key"]["value"] = "pk4"
                validators["result"]["validators"].append(extra)
            if mutate == "changed_validator_index":
                validators["result"]["validators"].reverse()
            if mutate == "signature":
                commit["result"]["signed_header"]["commit"]["precommits"][0]["block_id"]["parts"]["hash"] = "CQkJCQ=="
            if mutate == "missing_signature":
                commit["result"]["signed_header"]["commit"]["precommits"].pop()
            if mutate == "extra_signature":
                extra = copy.deepcopy(commit["result"]["signed_header"]["commit"]["precommits"][0])
                extra["validator_address"] = "VAL3"
                commit["result"]["signed_header"]["commit"]["precommits"][2] = extra
            retry = IndexerService(FakeRpc({122: {"block": block, "commit": commit, "validators": validators}}), db, "test-13", 130, [])
            with self.assertRaises(FinalizedDataConflict, msg=mutate):
                retry.run(plan_range(130, 122, 122, None, 130, 100, False))


    def test_existing_child_set_missing_and_extra_rows_conflict(self):
        db = SqlLikeDb(checkpoint=121)
        service = self.service(db, [122])
        service.run(plan_range(121, None, 122, None, 130, 100, False))
        original_rpc = self.service(db, [122])

        removed_tx = db.transactions.pop((122, 1))
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))
        db.transactions[(122, 1)] = removed_tx
        db.transactions[(122, 99)] = ("ZXh0cmE=", "decoded")
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))
        del db.transactions[(122, 99)]

        removed_member = db.members.pop((122, "VAL3"))
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))
        db.members[(122, "VAL3")] = removed_member
        db.members[(122, "VALX")] = (1, 0, 99)
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))
        del db.members[(122, "VALX")]

        removed_signature = db.signatures.pop((122, "VAL3"))
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))
        db.signatures[(122, "VAL3")] = removed_signature
        db.signatures[(122, "VALX")] = removed_signature
        with self.assertRaises(FinalizedDataConflict):
            original_rpc.run(plan_range(130, 122, 122, None, 130, 100, False))


class RpcHealthTests(unittest.TestCase):
    def test_structured_probe_results_include_rejections_and_stale(self):
        class Client:
            def __init__(self, url, timeout=10):
                self.base_url = url.rstrip("/") + "/"

            def get(self, method, **params):
                if "down" in self.base_url:
                    raise RpcError("down")
                status = load("status.json")
                if "wrong" in self.base_url:
                    status["result"]["node_info"]["network"] = "wrong"
                if "sync" in self.base_url:
                    status["result"]["sync_info"]["catching_up"] = True
                if "stale" in self.base_url:
                    status["result"]["sync_info"]["latest_block_height"] = "1"
                if "good" in self.base_url:
                    status["result"]["sync_info"]["latest_block_height"] = "20"
                return status

        with patch("indexer.rpc.GnoRpcClient", Client):
            selected = select_rpc(["http://wrong", "http://sync", "http://down", "http://stale", "http://good"], "test-13", 5)
        self.assertEqual(selected.client.base_url, "http://good/")
        self.assertEqual(len(selected.probes), 5)
        self.assertEqual(sum(probe.selected for probe in selected.probes), 1)
        self.assertTrue(any(probe.error_message and "wrong chain" in probe.error_message for probe in selected.probes))
        self.assertTrue(any(probe.error_message == "stale endpoint" for probe in selected.probes))


if __name__ == "__main__":
    unittest.main()
