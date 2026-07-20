import contextlib
import io
import os
import unittest
from unittest.mock import patch

from indexer.database import PostgresDatabase
from indexer.valopers_parser import ValoperProfile
from indexer.valopers_persistence import (
    StaleValopersSnapshot,
    ValopersPersistenceError,
    replace_valopers_snapshot_cursor,
    validate_valopers_snapshot,
)
from indexer.valopers_snapshot import ValopersSnapshot
from scripts import persist_valopers_snapshot as cli


def profile(number=1, moniker="Validator", description="Description"):
    suffix = str(number)
    return ValoperProfile(moniker, description, "operator" + suffix, "signing" + suffix,
                          "pubkey" + suffix, "cloud", "/profile/" + suffix)


def snapshot(height=10, pages=1, profiles=None):
    return ValopersSnapshot(height, pages, tuple(profiles if profiles is not None else [profile()]))


class ScriptedCursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.current = None
        self.operations = []

    def execute(self, sql, params=None):
        self.operations.append((" ".join(sql.split()), params))
        if sql.lstrip().startswith("SELECT") and "pg_advisory" not in sql:
            self.current = next(self.responses)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current


class IncomingValidationTests(unittest.TestCase):
    def test_valid_empty_and_nonempty_snapshots(self):
        self.assertEqual(validate_valopers_snapshot(ValopersSnapshot(1, 0, ()), "chain"), ())
        self.assertEqual(len(validate_valopers_snapshot(snapshot(), "chain")), 1)

    def test_invalid_metadata(self):
        for value in (0, True, "1"):
            with self.subTest(height=value), self.assertRaises(ValopersPersistenceError):
                validate_valopers_snapshot(ValopersSnapshot(value, 0, ()), "chain")
        with self.assertRaises(ValopersPersistenceError):
            validate_valopers_snapshot(ValopersSnapshot(1, 21, ()), "chain")
        with self.assertRaises(ValopersPersistenceError):
            validate_valopers_snapshot(ValopersSnapshot(1, 1, ()), "chain")
        with self.assertRaises(ValopersPersistenceError):
            validate_valopers_snapshot(snapshot(), "")

    def test_duplicate_identities_are_rejected(self):
        first = profile(1)
        variants = [
            profile(1, "Other"),
            ValoperProfile("Other", "Description", "operator2", first.signing_address,
                           "pubkey2", "cloud", "/profile/2"),
            ValoperProfile("Other", "Description", "operator2", "signing2",
                           first.signing_pubkey, "cloud", "/profile/2"),
        ]
        for duplicate in variants:
            with self.assertRaises(ValopersPersistenceError):
                validate_valopers_snapshot(snapshot(profiles=[first, duplicate]), "chain")


class CursorPersistenceTests(unittest.TestCase):
    def test_first_write_locks_first_and_generates_positions(self):
        item = snapshot(profiles=[profile(2), profile(1)])
        expected_rows = [
            (*validate_valopers_snapshot(item, "chain")[0], 10, 0),
            (*validate_valopers_snapshot(item, "chain")[1], 10, 1),
        ]
        cursor = ScriptedCursor([None, [], ("default", "chain", 10, 1, 2), expected_rows])
        result = replace_valopers_snapshot_cursor(cursor, item, "chain")
        self.assertEqual(result.action, "applied")
        self.assertIn("pg_advisory_xact_lock", cursor.operations[0][0])
        inserts = [params for sql, params in cursor.operations if sql.startswith("INSERT INTO valoper_profiles")]
        self.assertEqual([params[-1] for params in inserts], [0, 1])
        delete_index = next(i for i, (sql, _) in enumerate(cursor.operations) if sql == "DELETE FROM valoper_profiles")
        state_index = next(i for i, (sql, _) in enumerate(cursor.operations) if sql.startswith("INSERT INTO valopers_snapshot_state"))
        self.assertLess(delete_index, state_index)

    def test_same_height_is_unchanged_without_writes(self):
        item = snapshot()
        row = (*validate_valopers_snapshot(item, "chain")[0], 10, 0)
        cursor = ScriptedCursor([("default", "chain", 10, 1, 1), [row]])
        self.assertEqual(replace_valopers_snapshot_cursor(cursor, item, "chain").action, "unchanged")
        self.assertFalse(any(sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql, _ in cursor.operations))

    def test_stale_snapshot_has_no_destructive_write(self):
        item = snapshot(height=9)
        stored = (*validate_valopers_snapshot(snapshot(), "chain")[0], 10, 0)
        cursor = ScriptedCursor([("default", "chain", 10, 1, 1), [stored]])
        with self.assertRaises(StaleValopersSnapshot):
            replace_valopers_snapshot_cursor(cursor, item, "chain")
        self.assertFalse(any(sql.startswith("DELETE") for sql, _ in cursor.operations))


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self._cursor
    def commit(self): self.committed = True


class FakeManagedCursor(ScriptedCursor):
    def __enter__(self): return self
    def __exit__(self, *args): return False


class DatabaseAndCliTests(unittest.TestCase):
    def test_database_commits_after_verification(self):
        item = ValopersSnapshot(1, 0, ())
        cursor = FakeManagedCursor([None, [], ("default", "chain", 1, 0, 0), []])
        connection = FakeConnection(cursor)
        database = PostgresDatabase("secret")
        database.connect = lambda: connection
        self.assertEqual(database.replace_valopers_snapshot(item, "chain").action, "applied")
        self.assertTrue(connection.committed)

    def run_cli(self, environment):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main([])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_missing_database_url_fails_safely(self):
        code, stdout, stderr = self.run_cli({})
        self.assertEqual((code, stdout, stderr), (1, "", "Valopers snapshot persistence failed\n"))

    def test_success_summary_is_bounded(self):
        result = type("Result", (), {"action": "unchanged", "source_height": 12,
                                     "page_count": 1, "profile_count": 1})()
        with patch.object(cli, "select_healthy_rpc", return_value=(object(), {"status": True})), \
             patch.object(cli, "parse_status", return_value={"latest_height": 12}), \
             patch.object(cli, "collect_valopers_snapshot", return_value=snapshot(height=12)), \
             patch.object(cli.PostgresDatabase, "replace_valopers_snapshot", return_value=result):
            code, stdout, stderr = self.run_cli({"DATABASE_URL": "postgres://user:password@host/db"})
        self.assertEqual(code, 0)
        self.assertIn("action=unchanged", stdout)
        self.assertNotIn("password", stdout + stderr)


if __name__ == "__main__":
    unittest.main()
