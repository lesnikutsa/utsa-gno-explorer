import signal
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from indexer.database import ChainIdentityError, FinalizedDataConflict
from indexer.runner import (
    AdvisoryLockHeld,
    ContinuousConfig,
    FatalIndexerError,
    StopController,
    advisory_lock_key,
    run_continuous,
    run_cycle,
    validate_continuous_config,
)
from indexer.rpc import RpcProbeResult, SelectedRpc
from scripts.inspect_rpc import RpcError
from tests.test_indexer import SqlLikeDb, payloads


class FakeClient:
    base_url = "https://user@example.test/rpc?x=y"

    def __init__(self, heights, fail_height=None):
        self.heights = heights
        self.fail_height = fail_height

    def get(self, method, **params):
        height = params["height"]
        if height == self.fail_height:
            raise RpcError("timeout")
        block, commit, validators = payloads(height)
        return {"block": block, "commit": commit, "validators": validators}[method]


def selected(latest=105, fail_height=None):
    probe = RpcProbeResult("https://example.test", True, True, "test-13", latest, 0, False, client=FakeClient(latest, fail_height))
    return SelectedRpc(probe.client, {}, latest, latest - 1, [probe])


@dataclass
class FakeLock:
    db: object
    chain_id: str
    held = False
    acquired: bool = False
    closed: bool = False

    def acquire(self):
        if FakeLock.held:
            raise AdvisoryLockHeld("held")
        FakeLock.held = True
        self.acquired = True

    def close(self):
        FakeLock.held = False
        self.closed = True


class ContinuousIndexerTests(unittest.TestCase):
    def setUp(self):
        FakeLock.held = False
        self.config = ContinuousConfig(10, 3, 1, 1, 4)

    def patch_select(self, latest=105, fail_height=None):
        return patch("indexer.runner.select_rpc", return_value=selected(latest, fail_height))

    def test_empty_database_requires_start_height(self):
        with self.patch_select(), self.assertRaisesRegex(FatalIndexerError, "start-height"):
            run_cycle(SqlLikeDb(None), "test-13", ["x"], 10, ContinuousConfig(None, 3, 1, 1, 4), StopController())

    def test_next_height_is_checkpoint_plus_one(self):
        db = SqlLikeDb(10)
        with self.patch_select(20):
            result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(result.processed, [11, 12, 13])

    def test_bounded_catch_up_batch(self):
        db = SqlLikeDb(None)
        with self.patch_select(50):
            result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(result.processed, [10, 11, 12])

    def test_caught_up_cycle_writes_no_heights(self):
        db = SqlLikeDb(104)
        with self.patch_select(105):
            result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(result.processed, [])
        self.assertEqual(db.checkpoint, 104)

    def test_multiple_cycles_reach_tip_without_gaps(self):
        db = SqlLikeDb(None)
        with self.patch_select(16):
            run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
            run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(sorted(db.blocks), [10, 11, 12, 13, 14, 15])

    def test_new_heights_appear_between_cycles(self):
        db = SqlLikeDb(None)
        with self.patch_select(13):
            run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        with self.patch_select(15):
            result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(result.processed, [13, 14])

    def test_transient_rpc_failure_retries_same_height(self):
        db = SqlLikeDb(None)
        sleeps = []
        with self.patch_select(20, fail_height=10):
            code = run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 3, 1, 1, 2, max_cycles=1), sleep=sleeps.append, lock_factory=FakeLock)
        self.assertEqual(code, 0)
        self.assertIsNone(db.checkpoint)
        self.assertEqual(sleeps, [1])

    def test_successful_progress_resets_backoff(self):
        db = SqlLikeDb(None)
        sleeps = []
        with patch("indexer.runner.select_rpc", side_effect=[RpcError("down"), selected(12), RpcError("down")]):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 1, 8, max_cycles=3), sleep=sleeps.append, lock_factory=FakeLock)
        self.assertEqual(sleeps, [1, 1])

    def test_backoff_stops_at_maximum(self):
        db = SqlLikeDb(None)
        sleeps = []
        with patch("indexer.runner.select_rpc", side_effect=RpcError("down")):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 2, 3, max_cycles=4), sleep=sleeps.append, lock_factory=FakeLock)
        self.assertEqual(sleeps, [2, 3, 3, 3])

    def test_finalized_data_conflict_is_fatal(self):
        db = SqlLikeDb(None)
        db.fail_height = 10
        db.write_height = lambda *args, **kwargs: (_ for _ in ()).throw(FinalizedDataConflict("conflict"))
        with self.patch_select(20):
            self.assertEqual(run_continuous(db, "test-13", ["x"], 10, self.config, lock_factory=FakeLock), 1)

    def test_chain_mismatch_is_fatal(self):
        with self.patch_select(20):
            self.assertEqual(run_continuous(SqlLikeDb(1, chain_id="wrong"), "test-13", ["x"], 10, self.config, lock_factory=FakeLock), 1)

    def test_second_advisory_lock_holder_is_rejected(self):
        FakeLock.held = True
        with self.patch_select(20):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config, lock_factory=FakeLock), 1)

    def test_advisory_lock_is_released_on_normal_exit(self):
        with self.patch_select(11):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 1, 2, once=True), lock_factory=FakeLock), 0)
        self.assertFalse(FakeLock.held)

    def test_once_runs_one_cycle(self):
        db = SqlLikeDb(None)
        with self.patch_select(20):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 1, 2, once=True), lock_factory=FakeLock)
        self.assertEqual(db.checkpoint, 10)

    def test_max_cycles_stops_deterministically(self):
        db = SqlLikeDb(None)
        with self.patch_select(20):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 1, 2, max_cycles=2), lock_factory=FakeLock)
        self.assertEqual(db.checkpoint, 11)

    def test_sigint_stops_before_next_height(self):
        db = SqlLikeDb(None)
        stop = StopController()
        original = db.write_height
        def write(parsed, chain, tip):
            original(parsed, chain, tip); stop.request_stop("SIGINT")
        db.write_height = write
        with self.patch_select(20):
            run_cycle(db, "test-13", ["x"], 10, self.config, stop)
        self.assertEqual(db.checkpoint, 10)

    def test_sigterm_stops_before_next_height(self):
        db = SqlLikeDb(None)
        stop = StopController()
        original = db.write_height
        def write(parsed, chain, tip):
            original(parsed, chain, tip); stop.request_stop("SIGTERM")
        db.write_height = write
        with self.patch_select(20):
            run_cycle(db, "test-13", ["x"], 10, self.config, stop)
        self.assertEqual(db.checkpoint, 10)

    def test_injected_failure_leaves_checkpoint_unchanged(self):
        db = SqlLikeDb(9, fail_height=10)
        with self.patch_select(20), self.assertRaises(RuntimeError):
            run_cycle(db, "test-13", ["x"], 10, self.config, StopController())
        self.assertEqual(db.checkpoint, 9)

    def test_config_validation_and_lock_key_are_deterministic(self):
        with self.assertRaises(FatalIndexerError):
            validate_continuous_config(ContinuousConfig(0, 1, 1, 1, 1))
        self.assertEqual(advisory_lock_key("test-13"), advisory_lock_key("test-13"))


if __name__ == "__main__":
    unittest.main()
