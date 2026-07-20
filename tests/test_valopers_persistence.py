import contextlib
import io
import os
import unittest
from unittest.mock import patch

from indexer.database import PostgresDatabase
from indexer.valopers_parser import ValoperProfile
from indexer.valopers_persistence import (
    StaleValopersSnapshot, ValopersChainIdentityError, ValopersSnapshotConflict,
    ValopersPersistenceError,
    ValopersStoredStateError,
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
    def __init__(self, responses, fail_on=None, events=None):
        self.responses = iter(responses)
        self.current = None
        self.operations = []
        self.fail_on = fail_on
        self.events = events if events is not None else []

    def execute(self, sql, params=None):
        self.operations.append((" ".join(sql.split()), params))
        self.events.append(("execute", " ".join(sql.split())))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("injected database failure")
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
        cursor = ScriptedCursor([None, None, [], ("default", "chain", 10, 1, 2), expected_rows])
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
        cursor = ScriptedCursor([None, ("default", "chain", 10, 1, 1), [row]])
        self.assertEqual(replace_valopers_snapshot_cursor(cursor, item, "chain").action, "unchanged")
        self.assertFalse(any(sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql, _ in cursor.operations))

    def test_stale_snapshot_has_no_destructive_write(self):
        item = snapshot(height=9)
        stored = (*validate_valopers_snapshot(snapshot(), "chain")[0], 10, 0)
        cursor = ScriptedCursor([None, ("default", "chain", 10, 1, 1), [stored]])
        with self.assertRaises(StaleValopersSnapshot):
            replace_valopers_snapshot_cursor(cursor, item, "chain")
        self.assertFalse(any(sql.startswith("DELETE") for sql, _ in cursor.operations))

    def test_matching_and_absent_indexer_chain_allow_first_write(self):
        item = ValopersSnapshot(1, 0, ())
        for indexed_state in (("chain",), None):
            with self.subTest(indexed_state=indexed_state):
                cursor = ScriptedCursor([indexed_state, None, [], ("default", "chain", 1, 0, 0), []])
                self.assertEqual(replace_valopers_snapshot_cursor(cursor, item, "chain").action, "applied")
                self.assertIn("indexer_state", cursor.operations[1][0])

    def test_wrong_indexer_chain_fails_before_valopers_inspection_or_writes(self):
        cursor = ScriptedCursor([("other",)])
        with self.assertRaises(ValopersChainIdentityError):
            replace_valopers_snapshot_cursor(cursor, ValopersSnapshot(1, 0, ()), "chain")
        sql = [operation[0] for operation in cursor.operations]
        self.assertEqual(len(sql), 2)
        self.assertIn("pg_advisory_xact_lock", sql[0])
        self.assertIn("indexer_state", sql[1])
        self.assertFalse(any(statement.startswith(("DELETE", "INSERT", "UPDATE")) for statement in sql))

    def test_indexer_and_valopers_chain_disagreement_fails_closed(self):
        cursor = ScriptedCursor([("chain",), ("default", "other", 1, 0, 0), []])
        with self.assertRaises(ValopersChainIdentityError):
            replace_valopers_snapshot_cursor(cursor, ValopersSnapshot(2, 0, ()), "chain")
        self.assertFalse(any(sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql, _ in cursor.operations))

    def test_inconsistent_stored_states_fail_before_delete(self):
        good = (*validate_valopers_snapshot(snapshot(), "chain")[0], 10, 0)
        cases = (
            (None, [good]),
            (("default", "chain", 10, 1, 2), [good]),
            (("default", "chain", 10, 1, 1), [good[:6] + (9, 0)]),
            (("default", "chain", 10, 1, 1), [good[:7] + (1,)]),
        )
        for state, rows in cases:
            with self.subTest(state=state, rows=rows):
                cursor = ScriptedCursor([("chain",), state, rows])
                with self.assertRaises(ValopersStoredStateError):
                    replace_valopers_snapshot_cursor(cursor, snapshot(height=11), "chain")
                self.assertFalse(any(sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql, _ in cursor.operations))

    def test_valid_empty_and_nonempty_stored_states_pass_preconditions(self):
        empty_cursor = ScriptedCursor([
            ("chain",), ("default", "chain", 10, 0, 0), [],
            ("default", "chain", 11, 0, 0), [],
        ])
        self.assertEqual(replace_valopers_snapshot_cursor(empty_cursor, ValopersSnapshot(11, 0, ()), "chain").action, "applied")
        item = snapshot(height=11)
        incoming = validate_valopers_snapshot(item, "chain")
        old = (*incoming[0], 10, 0)
        new = (*incoming[0], 11, 0)
        cursor = ScriptedCursor([
            ("chain",), ("default", "chain", 10, 1, 1), [old],
            ("default", "chain", 11, 1, 1), [new],
        ])
        self.assertEqual(replace_valopers_snapshot_cursor(cursor, item, "chain").action, "applied")

    def test_same_height_field_and_order_conflicts_are_non_destructive(self):
        first, second = profile(1), profile(2, "Second")
        base = snapshot(profiles=[first, second])
        base_rows = [(*row, 10, index) for index, row in enumerate(validate_valopers_snapshot(base, "chain"))]
        variants = (
            snapshot(profiles=[profile(1, "Changed"), second]),
            snapshot(profiles=[profile(1, description="Changed"), second]),
            snapshot(profiles=[second, first]),
            snapshot(profiles=[ValoperProfile(first.moniker, first.description, first.operator_address,
                "changed-signing", first.signing_pubkey, first.server_type, first.profile_path), second]),
            snapshot(profiles=[ValoperProfile(first.moniker, first.description, first.operator_address,
                first.signing_address, "changed-pubkey", first.server_type, first.profile_path), second]),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                cursor = ScriptedCursor([("chain",), ("default", "chain", 10, 1, 2), base_rows])
                with self.assertRaises(ValopersSnapshotConflict):
                    replace_valopers_snapshot_cursor(cursor, variant, "chain")
                self.assertFalse(any(sql.startswith(("DELETE", "INSERT", "UPDATE")) for sql, _ in cursor.operations))

    def test_empty_replacement_writes_zero_counts(self):
        old = (*validate_valopers_snapshot(snapshot(), "chain")[0], 10, 0)
        cursor = ScriptedCursor([
            ("chain",), ("default", "chain", 10, 1, 1), [old],
            ("default", "chain", 11, 0, 0), [],
        ])
        replace_valopers_snapshot_cursor(cursor, ValopersSnapshot(11, 0, ()), "chain")
        state_params = next(params for sql, params in cursor.operations if sql.startswith("INSERT INTO valopers_snapshot_state"))
        self.assertEqual(state_params, ("chain", 11, 0, 0))


class FakeConnection:
    def __init__(self, cursor, events=None):
        self._cursor = cursor
        self.committed = False
        self.events = events if events is not None else []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self._cursor
    def commit(self):
        self.events.append(("commit", None))
        self.committed = True


class FakeManagedCursor(ScriptedCursor):
    def __enter__(self): return self
    def __exit__(self, *args): return False


class DatabaseAndCliTests(unittest.TestCase):
    def test_database_commits_after_verification(self):
        item = ValopersSnapshot(1, 0, ())
        cursor = FakeManagedCursor([None, None, [], ("default", "chain", 1, 0, 0), []])
        connection = FakeConnection(cursor)
        database = PostgresDatabase("secret")
        database.connect = lambda: connection
        self.assertEqual(database.replace_valopers_snapshot(item, "chain").action, "applied")
        self.assertTrue(connection.committed)

    def test_wrong_chain_and_sql_failures_do_not_commit(self):
        cases = (
            ScriptedCursor([("other",)]),
            ScriptedCursor([None, None, []], fail_on="INSERT INTO valoper_profiles"),
            ScriptedCursor([None, None, []], fail_on="INSERT INTO valopers_snapshot_state"),
            ScriptedCursor([None, None, [], None], fail_on=None),
            ScriptedCursor([None, None, [], ("default", "chain", 1, 1, 1), []]),
        )
        items = (ValopersSnapshot(1, 0, ()), snapshot(height=1), ValopersSnapshot(1, 0, ()),
                 ValopersSnapshot(1, 0, ()), snapshot(height=1))
        for cursor, item in zip(cases, items):
            connection = FakeConnection(FakeManagedCursor(cursor.responses, cursor.fail_on))
            database = PostgresDatabase("secret")
            database.connect = lambda connection=connection: connection
            with self.assertRaises(Exception):
                database.replace_valopers_snapshot(item, "chain")
            self.assertFalse(connection.committed)

    def test_commit_is_after_final_profile_verification(self):
        events = []
        cursor = FakeManagedCursor([None, None, [], ("default", "chain", 1, 0, 0), []], events=events)
        connection = FakeConnection(cursor, events)
        database = PostgresDatabase("secret")
        database.connect = lambda: connection
        database.replace_valopers_snapshot(ValopersSnapshot(1, 0, ()), "chain")
        self.assertEqual(events[-1][0], "commit")
        self.assertIn("FROM valoper_profiles ORDER BY list_position", events[-2][1])

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

    def test_help_runs_directly(self):
        with self.assertRaises(SystemExit) as raised:
            cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_dotenv_precedes_configuration_and_chain_is_reused_once(self):
        calls = []
        result = type("Result", (), {"action": "applied", "source_height": 12,
                                     "page_count": 0, "profile_count": 0})()
        def load():
            calls.append("dotenv")
            os.environ.setdefault("DATABASE_URL", "postgres://from-dotenv")
        with patch.dict(os.environ, {}, clear=True), patch.object(cli, "load_dotenv", side_effect=load), \
             patch.object(cli, "configured_chain_id", side_effect=lambda: calls.append("chain") or "captured-chain") as chain, \
             patch.object(cli, "configured_rpc_urls", side_effect=lambda: calls.append("rpc") or ["rpc"]), \
             patch.object(cli, "select_healthy_rpc", return_value=(object(), {})) as select, \
             patch.object(cli, "parse_status", return_value={"latest_height": 12}), \
             patch.object(cli, "collect_valopers_snapshot", return_value=ValopersSnapshot(12, 0, ())), \
             patch.object(cli.PostgresDatabase, "replace_valopers_snapshot", return_value=result) as persist:
            self.assertEqual(cli.main([]), 0)
        self.assertEqual(calls[:3], ["dotenv", "chain", "rpc"])
        self.assertEqual(chain.call_count, 1)
        self.assertEqual(select.call_args.kwargs["expected_chain_id"], "captured-chain")
        self.assertEqual(persist.call_args.args[1], "captured-chain")

    def test_process_environment_wins_over_dotenv(self):
        observed = []
        def load():
            observed.append(os.environ.get("DATABASE_URL"))
            os.environ.setdefault("DATABASE_URL", "postgres://dotenv")
        with patch.object(cli, "load_dotenv", side_effect=load), \
             patch.object(cli, "configured_chain_id", return_value="chain"), \
             patch.object(cli, "configured_rpc_urls", return_value=[]), \
             patch.object(cli, "select_healthy_rpc", side_effect=RuntimeError("stop")):
            code, _, _ = self.run_cli({"DATABASE_URL": "postgres://process"})
        self.assertEqual(code, 1)
        self.assertEqual(observed, ["postgres://process"])

    def test_each_cli_failure_is_bounded_and_redacted(self):
        stages = (
            ("select_healthy_rpc", RuntimeError("rpc://user:password@host")),
            ("parse_status", {"latest_height": 0}),
            ("collect_valopers_snapshot", RuntimeError("secret description pubkey operator signing")),
            ("replace_valopers_snapshot", RuntimeError("postgres://user:password@host/db")),
        )
        for stage, outcome in stages:
            with self.subTest(stage=stage), patch.object(cli, "load_dotenv"), \
                 patch.object(cli, "configured_chain_id", return_value="chain"), \
                 patch.object(cli, "configured_rpc_urls", return_value=["rpc"]), \
                 patch.object(cli, "select_healthy_rpc", return_value=(object(), {})), \
                 patch.object(cli, "parse_status", return_value={"latest_height": 1}), \
                 patch.object(cli, "collect_valopers_snapshot", return_value=ValopersSnapshot(1, 0, ())), \
                 patch.object(cli.PostgresDatabase, "replace_valopers_snapshot", return_value=type("R", (), {
                     "action": "applied", "source_height": 1, "page_count": 0, "profile_count": 0})()) as persist:
                target = persist if stage == "replace_valopers_snapshot" else getattr(cli, stage)
                if isinstance(outcome, Exception): target.side_effect = outcome
                else: target.return_value = outcome
                code, stdout, stderr = self.run_cli({"DATABASE_URL": "postgres://user:password@host/db"})
            self.assertEqual((code, stdout, stderr), (1, "", "Valopers snapshot persistence failed\n"))


if __name__ == "__main__":
    unittest.main()
