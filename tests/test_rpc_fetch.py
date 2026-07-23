import logging
import threading
import time
import unittest

from indexer.rpc import fetch_height
from scripts.inspect_rpc import RpcError


class ControlledRpcClient:
    def __init__(self, failing_method=None):
        self.barrier = threading.Barrier(3, timeout=2)
        self.release = {method: threading.Event() for method in ("block", "commit", "validators")}
        self.started = {method: threading.Event() for method in self.release}
        self.finished = {method: threading.Event() for method in self.release}
        self.failing_method = failing_method

    def get(self, method, **params):
        self.started[method].set()
        self.barrier.wait()
        if not self.release[method].wait(2):
            raise AssertionError(f"test did not release {method}")
        self.finished[method].set()
        if method == self.failing_method:
            raise RpcError(f"{method} failed")
        return {"method": method, "height": params["height"]}


class FetchHeightTests(unittest.TestCase):
    def run_fetch(self, client):
        result = []
        error = []

        def target():
            try:
                result.append(fetch_height(client, 42))
            except BaseException as exc:
                error.append(exc)

        thread = threading.Thread(target=target)
        thread.start()
        return thread, result, error

    def test_requests_overlap_and_results_keep_method_order(self):
        client = ControlledRpcClient()
        thread, result, error = self.run_fetch(client)

        for started in client.started.values():
            self.assertTrue(started.wait(1), "all methods must start before any is released")
        self.assertFalse(any(event.is_set() for event in client.finished.values()))
        for method in ("validators", "block", "commit"):
            client.release[method].set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(error, [])
        self.assertEqual([payload["method"] for payload in result[0]], ["block", "commit", "validators"])

    def test_one_request_error_fails_whole_fetch_after_workers_close(self):
        client = ControlledRpcClient(failing_method="commit")
        thread, result, error = self.run_fetch(client)
        for started in client.started.values():
            self.assertTrue(started.wait(1))
        for event in client.release.values():
            event.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [])
        self.assertEqual(len(error), 1)
        self.assertIsInstance(error[0], RpcError)
        self.assertTrue(all(event.is_set() for event in client.finished.values()))

    def test_fake_delay_comparison_tracks_maximum_not_sum(self):
        delays = {"block": 0.08, "commit": 0.12, "validators": 0.16}

        class DelayedClient:
            def get(self, method, **params):
                time.sleep(delays[method])
                return {"method": method}

        client = DelayedClient()
        sequential_started = time.perf_counter()
        for method in delays:
            client.get(method, height=42)
        sequential_duration = time.perf_counter() - sequential_started
        concurrent_started = time.perf_counter()
        fetch_height(client, 42)
        concurrent_duration = time.perf_counter() - concurrent_started

        self.assertGreater(sequential_duration, 0.30)
        self.assertLess(concurrent_duration, sequential_duration * 0.75)

    def test_success_log_contains_stable_per_method_metrics(self):
        client = ControlledRpcClient()
        thread, _, error = self.run_fetch(client)
        for started in client.started.values():
            self.assertTrue(started.wait(1))
        with self.assertLogs("indexer.rpc", logging.INFO) as captured:
            for event in client.release.values():
                event.set()
            thread.join(2)
        self.assertEqual(error, [])
        message = " ".join(captured.output)
        for field in ("rpc_fetch height=42", "total_seconds=", "block_seconds=", "commit_seconds=", "validators_seconds="):
            self.assertIn(field, message)


if __name__ == "__main__":
    unittest.main()
