import base64
import unittest
from unittest.mock import patch

from indexer.database import CheckpointAnchor
from indexer.rpc import RpcContinuityError, canonical_block_hash_hex, verify_checkpoint_anchor, verify_parent_continuity
from indexer.runner import ContinuousConfig, StopController, run_cycle
from tests.test_indexer import COMMIT_HASH, COMMIT_HASH_HEX, SqlLikeDb, payloads


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
        verify_checkpoint_anchor(client, 10, COMMIT_HASH_HEX)
        with self.assertRaisesRegex(RpcContinuityError, "checkpoint_hash_mismatch"):
            verify_checkpoint_anchor(client, 10, "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")

    def test_checkpoint_anchor_missing_and_malformed(self):
        client = Client({10: payloads(10)})
        block = client.blocks[10][0]
        del block["result"]["block_meta"]["block_id"]["hash"]
        with self.assertRaisesRegex(RpcContinuityError, "malformed_block_hash"):
            verify_checkpoint_anchor(client, 10, COMMIT_HASH_HEX)
        block["result"]["block_meta"]["block_id"]["hash"] = "%%%"
        with self.assertRaisesRegex(RpcContinuityError, "malformed_block_hash"):
            canonical_block_hash_hex(block)

    def test_parent_match_wrong_missing_and_malformed(self):
        block = payloads(11)[0]
        self.assertEqual(verify_parent_continuity(block, COMMIT_HASH_HEX), COMMIT_HASH_HEX)
        with self.assertRaisesRegex(RpcContinuityError, "parent_hash_mismatch"):
            verify_parent_continuity(block, "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")
        del block["result"]["block"]["header"]["last_block_id"]
        with self.assertRaisesRegex(RpcContinuityError, "missing_parent_hash"):
            verify_parent_continuity(block, COMMIT_HASH_HEX)
        block["result"]["block"]["header"]["last_block_id"] = {"hash": "%%%"}
        with self.assertRaisesRegex(RpcContinuityError, "malformed_parent_hash"):
            verify_parent_continuity(block, COMMIT_HASH_HEX)

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

class OperationalFailoverTests(unittest.TestCase):
    def probe(self, client, selected=False, latest=20):
        from indexer.rpc import RpcProbeResult
        return RpcProbeResult(client.base_url, True, selected, "test-13", latest, 0, False, client=client, status_payload={})

    def test_stable_rpc_checks_anchor_and_persists_selection_once(self):
        db = SqlLikeDb(9)
        client = Client({height: payloads(height) for height in range(9, 13)})
        client.calls = []
        original_get = client.get
        client.get = lambda method, **params: client.calls.append((method, params["height"])) or original_get(method, **params)
        with patch("indexer.runner.probe_rpc_endpoints", return_value=[self.probe(client, True)]):
            result = run_cycle(db, "test-13", [client.base_url], 10, ContinuousConfig(10, 3, 1, 1, 2), StopController())
        self.assertEqual(result.processed, [10, 11, 12])
        self.assertEqual(client.calls.count(("block", 9)), 1)
        for height in (10, 11, 12):
            self.assertCountEqual([method for method, called_height in client.calls if called_height == height], ["block", "commit", "validators"])
        self.assertEqual(db.selection_calls, [(client.base_url, "initial_selection")])

    def test_failover_once_then_secondary_finishes_batch(self):
        db = SqlLikeDb(9)
        blocks = {height: payloads(height) for height in range(9, 13)}
        primary = Client(blocks, fail=("commit", 10), url="https://primary.test")
        secondary = Client(blocks, url="https://secondary.test")
        secondary.calls = []
        secondary_get = secondary.get
        secondary.get = lambda method, **params: secondary.calls.append((method, params["height"])) or secondary_get(method, **params)
        probes = [self.probe(primary, True), self.probe(secondary)]
        with patch("indexer.runner.probe_rpc_endpoints", return_value=probes), self.assertLogs("indexer.runner", "INFO") as logs:
            result = run_cycle(db, "test-13", [p.url for p in probes], 10, ContinuousConfig(10, 3, 1, 1, 2), StopController())
        self.assertEqual(result.processed, [10, 11, 12])
        self.assertEqual(sum("rpc_failover" in line for line in logs.output), 1)
        self.assertEqual(secondary.calls.count(("block", 9)), 1)
        self.assertEqual(db.selection_calls, [(primary.base_url, "initial_selection"), (secondary.base_url, "rpc_error")])
        self.assertEqual(db.runtime_failures, [(primary.base_url, "rpc_error")])

    def test_wrong_parent_excludes_primary_and_uses_secondary(self):
        db = SqlLikeDb(9)
        primary_blocks = {height: payloads(height) for height in range(9, 12)}
        primary_blocks[10][0]["result"]["block"]["header"]["last_block_id"]["hash"] = base64.b64encode(b"x" * 32).decode()
        secondary_blocks = {height: payloads(height) for height in range(9, 12)}
        primary = Client(primary_blocks, url="https://primary.test")
        secondary = Client(secondary_blocks, url="https://secondary.test")
        probes = [self.probe(primary, True), self.probe(secondary)]
        with patch("indexer.runner.probe_rpc_endpoints", return_value=probes):
            result = run_cycle(db, "test-13", [p.url for p in probes], 10, ContinuousConfig(10, 2, 1, 1, 2), StopController())
        self.assertEqual(result.processed, [10, 11])
        self.assertEqual(db.runtime_failures, [(primary.base_url, "parent_hash_mismatch")])

    def test_secret_bearing_rpc_error_is_classified_not_exposed(self):
        class SecretClient(Client):
            def get(self, method, **params):
                if method == "commit":
                    from scripts.inspect_rpc import RpcError
                    raise RpcError("https://user:password@example.test/path?token=SECRET")
                return super().get(method, **params)
        db = SqlLikeDb(9)
        client = SecretClient({9: payloads(9), 10: payloads(10)})
        with patch("indexer.runner.probe_rpc_endpoints", return_value=[self.probe(client, True)]), self.assertLogs("indexer.runner", "WARNING") as logs, self.assertRaises(Exception):
            run_cycle(db, "test-13", [client.base_url], 10, ContinuousConfig(10, 1, 1, 1, 2), StopController())
        output = " ".join(logs.output)
        self.assertNotIn("password", output)
        self.assertNotIn("SECRET", output)
        self.assertEqual(db.runtime_failures, [(client.base_url, "rpc_error")])

    def test_short_and_long_hashes_are_rejected(self):
        from indexer.rpc import canonical_block_hash_hex, parent_block_hash_hex
        for length in (31, 33):
            block = payloads(10)[0]
            block["result"]["block_meta"]["block_id"]["hash"] = base64.b64encode(b"x" * length).decode()
            with self.assertRaisesRegex(RpcContinuityError, "malformed_block_hash"):
                canonical_block_hash_hex(block)
            block = payloads(10)[0]
            block["result"]["block"]["header"]["last_block_id"]["hash"] = base64.b64encode(b"x" * length).decode()
            with self.assertRaisesRegex(RpcContinuityError, "malformed_parent_hash"):
                parent_block_hash_hex(block)


class AnchorDatabaseTests(unittest.TestCase):
    class Cursor:
        def __init__(self, row): self.row = row
        def execute(self, *args): self.sql = args[0]
        def fetchone(self): return self.row

    def test_checkpoint_anchor_database_states(self):
        from indexer.database import ChainIdentityError, DatabaseError, get_checkpoint_anchor_cursor
        self.assertIsNone(get_checkpoint_anchor_cursor(self.Cursor(None), "test-13"))
        anchor = get_checkpoint_anchor_cursor(self.Cursor(("test-13", 9, COMMIT_HASH_HEX)), "test-13")
        self.assertEqual(anchor, CheckpointAnchor(9, COMMIT_HASH_HEX))
        with self.assertRaises(DatabaseError):
            get_checkpoint_anchor_cursor(self.Cursor(("test-13", 9, None)), "test-13")
        with self.assertRaises(ChainIdentityError):
            get_checkpoint_anchor_cursor(self.Cursor(("wrong", 9, COMMIT_HASH_HEX)), "test-13")
        for malformed in ("abcd", COMMIT_HASH_HEX.lower(), "Z" * 64):
            with self.assertRaises(DatabaseError):
                get_checkpoint_anchor_cursor(self.Cursor(("test-13", 9, malformed)), "test-13")
