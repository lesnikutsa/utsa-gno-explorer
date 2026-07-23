import base64
import unittest
from unittest.mock import patch

from indexer.database import CheckpointAnchor
from indexer.rpc import RpcContinuityError, canonical_block_hash_hex, verify_checkpoint_anchor, verify_parent_continuity
from indexer.runner import ContinuousConfig, StopController, run_cycle
from tests.test_indexer import COMMIT_HASH, SqlLikeDb, payloads


class Client:
    def __init__(self, blocks, fail=None, url="https://rpc.test"):
        self.blocks = blocks
        self.fail = fail
        self.base_url = url

    def get(self, method, **params):
        height = params["height"]
        if self.fail == (method, height):
            from scripts.inspect_rpc import RpcError
            raise RpcError("timeout")
        block, commit, validators = self.blocks[height]
        return {"block": block, "commit": commit, "validators": validators}[method]


class ContinuityTests(unittest.TestCase):
    def test_checkpoint_anchor_match_and_mismatch(self):
        client = Client({10: payloads(10)})
        verify_checkpoint_anchor(client, 10, "01020304")
        with self.assertRaisesRegex(RpcContinuityError, "checkpoint_hash_mismatch"):
            verify_checkpoint_anchor(client, 10, "FFFFFFFF")

    def test_checkpoint_anchor_missing_and_malformed(self):
        client = Client({10: payloads(10)})
        block = client.blocks[10][0]
        del block["result"]["block_meta"]["block_id"]["hash"]
        with self.assertRaisesRegex(RpcContinuityError, "malformed_block_hash"):
            verify_checkpoint_anchor(client, 10, "01020304")
        block["result"]["block_meta"]["block_id"]["hash"] = "%%%"
        with self.assertRaisesRegex(RpcContinuityError, "malformed_block_hash"):
            canonical_block_hash_hex(block)

    def test_parent_match_wrong_missing_and_malformed(self):
        block = payloads(11)[0]
        self.assertEqual(verify_parent_continuity(block, "01020304"), "01020304")
        with self.assertRaisesRegex(RpcContinuityError, "parent_hash_mismatch"):
            verify_parent_continuity(block, "FFFFFFFF")
        del block["result"]["block"]["header"]["last_block_id"]
        with self.assertRaisesRegex(RpcContinuityError, "missing_parent_hash"):
            verify_parent_continuity(block, "01020304")
        block["result"]["block"]["header"]["last_block_id"] = {"hash": "%%%"}
        with self.assertRaisesRegex(RpcContinuityError, "malformed_parent_hash"):
            verify_parent_continuity(block, "01020304")

    def test_empty_database_does_not_require_anchor(self):
        db = SqlLikeDb(None)
        from indexer.rpc import RpcProbeResult
        client = Client({10: payloads(10), 11: payloads(11)})
        probe = RpcProbeResult(client.base_url, True, True, "test-13", 12, 0, False, client=client, status_payload={})
        with patch("indexer.runner.probe_rpc_endpoints", return_value=[probe]):
            result = run_cycle(db, "test-13", [client.base_url], 10, ContinuousConfig(10, 1, 1, 1, 2), StopController())
        self.assertEqual(result.processed, [10])

    def test_same_height_failover_preserves_sequence(self):
        from indexer.rpc import RpcProbeResult
        db = SqlLikeDb(9)
        primary = Client({9: payloads(9), 10: payloads(10)}, fail=("commit", 10), url="https://primary.test")
        secondary = Client({9: payloads(9), 10: payloads(10)}, url="https://secondary.test")
        probes = [
            RpcProbeResult(primary.base_url, True, True, "test-13", 12, 0, False, client=primary, status_payload={}),
            RpcProbeResult(secondary.base_url, True, False, "test-13", 12, 0, False, client=secondary, status_payload={}),
        ]
        with patch("indexer.runner.probe_rpc_endpoints", return_value=probes):
            result = run_cycle(db, "test-13", [p.url for p in probes], 10, ContinuousConfig(10, 1, 1, 1, 2), StopController())
        self.assertEqual(result.processed, [10])
        self.assertEqual(db.checkpoint, 10)
        self.assertEqual(db.selected_url, secondary.base_url)
