import signal
import unittest
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import psycopg
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
    probe = RpcProbeResult("https://example.test", True, True, "test-13", latest, 0, False, client=FakeClient(latest, fail_height), status_payload={})
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

    def ensure_alive(self):
        if not FakeLock.held:
            raise AdvisoryLockHeld("lost")

    def close(self):
        FakeLock.held = False
        self.closed = True


class ContinuousIndexerTests(unittest.TestCase):
    def setUp(self):
        FakeLock.held = False
        self.config = ContinuousConfig(10, 3, 1, 1, 4)

    def patch_select(self, latest=105, fail_height=None):
        return patch("indexer.runner.probe_rpc_endpoints", return_value=selected(latest, fail_height).probes)

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
            code = run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 3, 1, 1, 2, max_cycles=1), wait=lambda seconds, stop: sleeps.append(seconds) or False, lock_factory=FakeLock)
        self.assertEqual(code, 1)
        self.assertIsNone(db.checkpoint)
        self.assertEqual(sleeps, [])

    def test_successful_progress_resets_backoff(self):
        db = SqlLikeDb(None)
        sleeps = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=[RpcError("down"), selected(12).probes, RpcError("down")]):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 1, 8, max_cycles=3), wait=lambda seconds, stop: sleeps.append(seconds) or False, lock_factory=FakeLock)
        self.assertEqual(sleeps, [1])

    def test_backoff_stops_at_maximum(self):
        db = SqlLikeDb(None)
        sleeps = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")):
            run_continuous(db, "test-13", ["x"], 10, ContinuousConfig(10, 1, 1, 2, 3, max_cycles=4), wait=lambda seconds, stop: sleeps.append(seconds) or False, lock_factory=FakeLock)
        self.assertEqual(sleeps, [2, 3, 3])

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

    def test_cycle_performance_log_preserves_fields(self):
        with self.patch_select(12), self.assertLogs("indexer.runner", level="INFO") as captured:
            code = run_continuous(
                SqlLikeDb(None), "test-13", ["x"], 10,
                ContinuousConfig(10, 2, 1, 1, 2, once=True), lock_factory=FakeLock,
            )
        self.assertEqual(code, 0)
        cycle_log = next(message for message in captured.output if "processed_heights=" in message)
        for field in ("cycle=1", "processed_heights=", "checkpoint_after=", "duration_seconds=", "blocks_per_second="):
            self.assertIn(field, cycle_log)

    def test_caught_up_cycle_log_omits_throughput(self):
        with self.patch_select(11), self.assertLogs("indexer.runner", level="INFO") as captured:
            code = run_continuous(
                SqlLikeDb(10), "test-13", ["x"], 10,
                ContinuousConfig(10, 1, 1, 1, 2, once=True), lock_factory=FakeLock,
            )
        self.assertEqual(code, 0)
        cycle_log = next(message for message in captured.output if "processed_heights=" in message)
        for field in ("cycle=1", "processed_heights=[]", "checkpoint_after=10", "duration_seconds="):
            self.assertIn(field, cycle_log)
        self.assertNotIn("blocks_per_second=", cycle_log)

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

    def test_single_rpc_method_failure_prevents_parse_write_and_next_height(self):
        calls = []

        class PartialFailureClient(FakeClient):
            def get(self, method, **params):
                height = params["height"]
                calls.append(("fetch", height, method))
                if method == "commit":
                    raise RpcError("commit failed")
                return super().get(method, **params)

        class RecordingDb(SqlLikeDb):
            def write_height(self, parsed, chain_id, finalized_tip):
                calls.append(("write", parsed.height))
                return super().write_height(parsed, chain_id, finalized_tip)

        client = PartialFailureClient(20)
        probe = RpcProbeResult(
            "https://example.test", True, True, "test-13", 20, 0, False,
            client=client, status_payload={},
        )
        db = RecordingDb(9)
        parsed_heights = []
        cycle_result = None
        with (
            patch("indexer.runner.probe_rpc_endpoints", return_value=[probe]),
            patch("indexer.runner.parse_height", side_effect=lambda *args: parsed_heights.append(args[0])),
            self.assertRaisesRegex(RpcError, "commit failed"),
        ):
            cycle_result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())

        self.assertEqual(
            {call for call in calls if call[0] == "fetch"},
            {("fetch", 10, "block"), ("fetch", 10, "commit"), ("fetch", 10, "validators")},
        )
        self.assertEqual(parsed_heights, [])
        self.assertFalse(any(call[0] == "write" for call in calls))
        self.assertEqual(db.checkpoint, 9)
        self.assertFalse(any(call[:2] == ("fetch", 11) for call in calls))
        self.assertIsNone(cycle_result)

    def test_next_height_fetch_starts_only_after_previous_write(self):
        events = []

        class OrderedClient(FakeClient):
            def get(self, method, **params):
                events.append(("fetch", params["height"], method))
                return super().get(method, **params)

        class OrderedDb(SqlLikeDb):
            def write_height(self, parsed, chain_id, finalized_tip):
                events.append(("write", parsed.height))
                return super().write_height(parsed, chain_id, finalized_tip)

        db = OrderedDb(9)
        choice = selected(13)
        choice = SelectedRpc(OrderedClient(13), {}, 13, 12, choice.probes)
        choice.probes[0] = RpcProbeResult(
            "https://example.test", True, True, "test-13", 13, 0, False,
            client=choice.client, status_payload={},
        )
        with patch("indexer.runner.probe_rpc_endpoints", return_value=choice.probes):
            result = run_cycle(db, "test-13", ["x"], 10, self.config, StopController())

        self.assertEqual(result.processed, [10, 11, 12])
        self.assertEqual([event[1] for event in events if event[0] == "write"], [10, 11, 12])
        for height in (11, 12):
            previous_write = events.index(("write", height - 1))
            next_fetches = [index for index, event in enumerate(events) if event[:2] == ("fetch", height)]
            self.assertTrue(next_fetches)
            self.assertGreater(min(next_fetches), previous_write)

    def test_config_validation_and_lock_key_are_deterministic(self):
        with self.assertRaises(FatalIndexerError):
            validate_continuous_config(ContinuousConfig(0, 1, 1, 1, 1))
        self.assertEqual(advisory_lock_key("test-13"), advisory_lock_key("test-13"))





class ReviewSemanticsTests(unittest.TestCase):
    def config(self, **kwargs):
        values = dict(start_height=10, batch_size=2, poll_interval_seconds=1, error_backoff_seconds=1, max_backoff_seconds=4, hard_max_heights=3)
        values.update(kwargs)
        return ContinuousConfig(**values)

    def test_all_unhealthy_cycle_persists_every_probe(self):
        db = SqlLikeDb(None)
        probes = [
            RpcProbeResult("http://bad1", False, False, error_message="down"),
            RpcProbeResult("http://bad2", False, False, chain_id="wrong", error_message="wrong chain"),
        ]
        with patch("indexer.runner.probe_rpc_endpoints", return_value=probes), self.assertRaisesRegex(RpcError, "All RPC"):
            run_cycle(db, "test-13", ["x", "y"], 10, self.config(), StopController())
        self.assertEqual(db.probe_cycles, [probes])

    def test_once_success_caught_up_and_transient_exit_codes(self):
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(once=True), lock_factory=FakeLock), 0)
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(11).probes):
            self.assertEqual(run_continuous(SqlLikeDb(10), "test-13", ["x"], 10, self.config(once=True), lock_factory=FakeLock), 0)
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(once=True), lock_factory=FakeLock), 1)

    def test_max_cycles_failure_success_and_no_final_sleep(self):
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(max_cycles=2), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock), 1)
        self.assertEqual(waits, [1])
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=[RpcError("down"), selected(12).probes]):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(max_cycles=2), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock), 0)
        self.assertEqual(waits, [1])
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(11).probes):
            self.assertEqual(run_continuous(SqlLikeDb(10), "test-13", ["x"], 10, self.config(max_cycles=1), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock), 0)
        self.assertEqual(waits, [])

    def test_temporary_database_failure_retries_same_height_then_advances(self):
        class FlakyDb(SqlLikeDb):
            def __init__(self):
                super().__init__(9)
                self.calls = []
            def write_height(self, parsed, chain_id, finalized_tip):
                self.calls.append(parsed.height)
                if len(self.calls) == 1:
                    raise psycopg.OperationalError("temporary connection failure")
                return super().write_height(parsed, chain_id, finalized_tip)
        db = FlakyDb()
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            code = run_continuous(db, "test-13", ["x"], 10, self.config(max_cycles=2, batch_size=1), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock)
        self.assertEqual(code, 0)
        self.assertEqual(db.calls, [10, 10])
        self.assertEqual(db.checkpoint, 10)

    def test_advisory_lock_liveness_and_loss(self):
        class LostLock(FakeLock):
            def ensure_alive(self):
                raise AdvisoryLockHeld("lost")
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(max_cycles=1), lock_factory=FakeLock), 0)
        db = SqlLikeDb(None)
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            self.assertEqual(run_continuous(db, "test-13", ["x"], 10, self.config(max_cycles=1), lock_factory=LostLock), 1)
        self.assertIsNone(db.checkpoint)

    def test_close_on_broken_advisory_connection_is_best_effort(self):
        from indexer.runner import AdvisoryLock
        class BrokenConnection:
            closed = False
            def cursor(self):
                raise RuntimeError("broken")
            def close(self):
                raise RuntimeError("close broken")
        lock = AdvisoryLock(SqlLikeDb(None), "test-13")
        lock.connection = BrokenConnection()
        lock.close()
        self.assertIsNone(lock.connection)

    def test_stop_aware_poll_and_backoff_waits(self):
        stop = StopController()
        def stopping_wait(seconds, controller):
            controller.request_stop("SIGTERM")
            return True
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(11).probes):
            self.assertEqual(run_continuous(SqlLikeDb(10), "test-13", ["x"], 10, self.config(), stop=stop, wait=stopping_wait, lock_factory=FakeLock), 0)
        stop = StopController()
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")):
            self.assertEqual(run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(), stop=stop, wait=stopping_wait, lock_factory=FakeLock), 1)


    def test_empty_database_without_start_height_fails_before_rpc_and_backoff(self):
        db = SqlLikeDb(None)
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")) as probe:
            code = run_continuous(db, "test-13", ["x"], 10, self.config(start_height=None, max_cycles=2), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock)
        self.assertEqual(code, 1)
        self.assertEqual(waits, [])
        probe.assert_not_called()

    def test_advisory_lock_connection_is_autocommit(self):
        from indexer.runner import AdvisoryLock
        class Cursor:
            def __init__(self, connection):
                self.connection = connection
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params=None):
                self.connection.statements.append((sql, self.connection.autocommit))
            def fetchone(self):
                return (True,)
        class Connection:
            def __init__(self):
                self.autocommit = False
                self.closed = False
                self.statements = []
            def cursor(self):
                return Cursor(self)
            def commit(self):
                self.statements.append(("COMMIT", self.autocommit))
            def close(self):
                self.closed = True
        class Db:
            def __init__(self):
                self.connection = Connection()
            def connect(self):
                return self.connection
        db = Db()
        lock = AdvisoryLock(db, "test-13")
        lock.acquire()
        lock.ensure_alive()
        self.assertTrue(db.connection.autocommit)
        self.assertTrue(all(autocommit for _sql, autocommit in db.connection.statements if _sql != "COMMIT"))
        lock.close()

    def test_lock_connection_failure_then_success_before_processing(self):
        class FlakyLock(FakeLock):
            attempts = 0
            def acquire(self):
                FlakyLock.attempts += 1
                if FlakyLock.attempts == 1:
                    raise psycopg.OperationalError("temporary lock connection failure")
                super().acquire()
        db = SqlLikeDb(None)
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            code = run_continuous(db, "test-13", ["x"], 10, self.config(max_cycles=2, batch_size=1), wait=lambda s, stop: waits.append(s) or False, lock_factory=FlakyLock)
        self.assertEqual(code, 0)
        self.assertEqual(waits, [1])
        self.assertEqual(db.checkpoint, 11)

    def test_repeated_lock_connection_failure_exits_without_processing(self):
        class FailingLock(FakeLock):
            def acquire(self):
                raise psycopg.InterfaceError("temporary lock connection failure")
        db = SqlLikeDb(None)
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes) as probe:
            code = run_continuous(db, "test-13", ["x"], 10, self.config(max_cycles=2), wait=lambda s, stop: waits.append(s) or False, lock_factory=FailingLock)
        self.assertEqual(code, 1)
        self.assertEqual(waits, [1])
        self.assertIsNone(db.checkpoint)
        probe.assert_not_called()

    def test_stop_during_lock_acquisition_backoff_exits_promptly(self):
        class FailingLock(FakeLock):
            def acquire(self):
                raise psycopg.OperationalError("temporary lock connection failure")
        db = SqlLikeDb(None)
        stop = StopController()
        def stopping_wait(seconds, controller):
            controller.request_stop("SIGTERM")
            return True
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes) as probe:
            code = run_continuous(db, "test-13", ["x"], 10, self.config(), stop=stop, wait=stopping_wait, lock_factory=FailingLock)
        self.assertEqual(code, 1)
        self.assertIsNone(db.checkpoint)
        probe.assert_not_called()

    def test_non_transient_psycopg_error_is_clean_fatal(self):
        class BadDb(SqlLikeDb):
            def get_checkpoint(self, chain_id):
                raise psycopg.ProgrammingError("undefined table")
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            self.assertEqual(run_continuous(BadDb(None), "test-13", ["x"], 10, self.config(max_cycles=1), lock_factory=FakeLock), 1)


    def test_acquire_partial_failure_cleanup_and_later_retry_in_run(self):
        class PartialConnection:
            def __init__(self, fail_fetch):
                self.fail_fetch = fail_fetch
                self.autocommit = False
                self.closed = False
            def cursor(self):
                connection = self
                class Cursor:
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                    def execute(self, sql, params=None): pass
                    def fetchone(self):
                        if connection.fail_fetch:
                            raise psycopg.OperationalError("fetch failed")
                        return (True,)
                return Cursor()
            def close(self):
                self.closed = True
        class Db:
            def __init__(self):
                self.created = []
            def connect(self):
                connection = PartialConnection(fail_fetch=len(self.created) == 0)
                self.created.append(connection)
                return connection
        from indexer.runner import AdvisoryLock
        lock_db = Db()
        lock = AdvisoryLock(lock_db, "test-13")
        with self.assertRaises(psycopg.OperationalError):
            lock.acquire()
        self.assertTrue(lock_db.created[0].closed)
        self.assertIsNone(lock.connection)
        lock.acquire()
        self.assertIs(lock.connection, lock_db.created[1])
        self.assertFalse(lock_db.created[1].closed)
        lock.close()

    def test_lock_partial_failure_retry_uses_fresh_connection_before_processing(self):
        class PartialLock(FakeLock):
            attempts = 0
            failed_closed = False
            def acquire(self):
                PartialLock.attempts += 1
                if PartialLock.attempts == 1:
                    PartialLock.failed_closed = True
                    raise psycopg.OperationalError("partial acquisition failure")
                super().acquire()
        db = SqlLikeDb(None)
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", return_value=selected(12).probes):
            code = run_continuous(db, "test-13", ["x"], 10, self.config(max_cycles=2, batch_size=1), wait=lambda s, stop: waits.append(s) or False, lock_factory=PartialLock)
        self.assertEqual(code, 0)
        self.assertTrue(PartialLock.failed_closed)
        self.assertEqual(waits, [1])
        self.assertEqual(db.checkpoint, 11)

    def test_empty_rpc_urls_are_fatal_before_lock_and_backoff(self):
        class CountingLock(FakeLock):
            attempts = 0
            def acquire(self):
                CountingLock.attempts += 1
                super().acquire()
        db = SqlLikeDb(None)
        waits = []
        code = run_continuous(db, "test-13", [], 10, self.config(), wait=lambda s, stop: waits.append(s) or False, lock_factory=CountingLock)
        self.assertEqual(code, 1)
        self.assertEqual(CountingLock.attempts, 0)
        self.assertEqual(waits, [])
        self.assertIsNone(db.checkpoint)
        self.assertEqual(db.probe_cycles, [])

    def test_non_empty_unavailable_rpc_urls_remain_transient(self):
        waits = []
        with patch("indexer.runner.probe_rpc_endpoints", side_effect=RpcError("down")):
            code = run_continuous(SqlLikeDb(None), "test-13", ["x"], 10, self.config(max_cycles=2), wait=lambda s, stop: waits.append(s) or False, lock_factory=FakeLock)
        self.assertEqual(code, 1)
        self.assertEqual(waits, [1])

    def test_hard_batch_limit_validation(self):
        validate_continuous_config(self.config(batch_size=3, hard_max_heights=3))
        with self.assertRaisesRegex(FatalIndexerError, "batch_size"):
            validate_continuous_config(self.config(batch_size=4, hard_max_heights=3))


class CliConfigurationTests(unittest.TestCase):
    def run_cli(self, *args, **env):
        import os, subprocess, sys
        from pathlib import Path
        full_env = os.environ.copy()
        full_env.update({"PYTHONPATH": "", "GNO_RPC_URLS": "http://example.test", "DATABASE_URL": "postgresql://user:change-me@localhost/db"})
        full_env.update(env)
        return subprocess.run([sys.executable, "scripts/run_indexer.py", *args], cwd=Path(__file__).parents[1], env=full_env, text=True, capture_output=True, check=False)

    def test_invalid_environment_value_is_clean(self):
        result = self.run_cli(INDEXER_BATCH_SIZE="not-int")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fatal configuration error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("postgresql://", result.stderr)

    def test_invalid_cli_value_is_clean(self):
        result = self.run_cli("--batch-size", "not-int")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fatal configuration error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_batch_size_above_hard_limit_is_clean(self):
        result = self.run_cli("--batch-size", "101", INDEXER_HARD_MAX_HEIGHTS="100")
        self.assertEqual(result.returncode, 1)
        self.assertIn("batch_size", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
