import unittest
from unittest.mock import patch

from indexer.database import PostgresDatabase
from indexer.rpc import RpcProbeResult


class FakeCursor:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("cursor enter")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("cursor exit")


class FakeConnection:
    def __init__(self, events, commit_error=None):
        self.events = events
        self.commit_error = commit_error
        self.closed = False

    def __enter__(self):
        self.events.append("connection enter")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        self.events.append("connection exit")

    def cursor(self):
        return FakeCursor(self.events)

    def commit(self):
        if self.closed:
            raise RuntimeError("commit called on closed connection")
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error


class RpcPersistenceTransactionLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.probe = RpcProbeResult("https://rpc.example.test", True, True, "test-chain", 100, 0, False)

    def database_with_connection(self, connection):
        database = PostgresDatabase("postgresql://unused")
        database.connect = lambda: connection
        return database

    def test_select_commits_before_connection_exit_and_then_updates_memory(self):
        events = []
        database = self.database_with_connection(FakeConnection(events))

        def select_helper(cursor, chain_id, probe, reason):
            events.append("SQL helper")
            return 42

        with patch("indexer.database.select_rpc_endpoint_cursor", side_effect=select_helper):
            database.select_rpc_endpoint("test-chain", self.probe, "continuity verified")

        self.assertEqual(events, [
            "connection enter", "cursor enter", "SQL helper", "cursor exit",
            "commit", "connection exit",
        ])
        self.assertEqual(database.selected_rpc_endpoint_id, 42)

    def test_runtime_failure_commits_before_connection_exit_and_then_clears_memory(self):
        events = []
        database = self.database_with_connection(FakeConnection(events))
        database.selected_rpc_endpoint_id = 42

        def failure_helper(cursor, chain_id, probe, reason):
            events.append("SQL helper")
            return 42, True

        with patch("indexer.database.record_rpc_runtime_failure_cursor", side_effect=failure_helper):
            database.record_rpc_runtime_failure("test-chain", self.probe, "runtime failure")

        self.assertEqual(events, [
            "connection enter", "cursor enter", "SQL helper", "cursor exit",
            "commit", "connection exit",
        ])
        self.assertIsNone(database.selected_rpc_endpoint_id)

    def test_select_commit_failure_preserves_memory_and_propagates(self):
        events = []
        error = RuntimeError("commit failed")
        database = self.database_with_connection(FakeConnection(events, error))
        database.selected_rpc_endpoint_id = 7

        with patch("indexer.database.select_rpc_endpoint_cursor", return_value=42):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                database.select_rpc_endpoint("test-chain", self.probe, "continuity verified")

        self.assertEqual(database.selected_rpc_endpoint_id, 7)
        self.assertEqual(events[-2:], ["commit", "connection exit"])

    def test_runtime_failure_commit_failure_preserves_memory_and_propagates(self):
        events = []
        error = RuntimeError("commit failed")
        database = self.database_with_connection(FakeConnection(events, error))
        database.selected_rpc_endpoint_id = 42

        with patch("indexer.database.record_rpc_runtime_failure_cursor", return_value=(42, True)):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                database.record_rpc_runtime_failure("test-chain", self.probe, "runtime failure")

        self.assertEqual(database.selected_rpc_endpoint_id, 42)
        self.assertEqual(events[-2:], ["commit", "connection exit"])


if __name__ == "__main__":
    unittest.main()
