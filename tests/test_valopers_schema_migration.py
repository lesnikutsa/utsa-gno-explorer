import contextlib
import copy
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import init_database, migrate_valopers_schema

ROOT = Path(__file__).resolve().parents[1]


def expected_snapshot():
    return {
        "tables": set(init_database.EXPECTED_TABLES),
        "columns": copy.deepcopy(init_database.EXPECTED_COLUMNS),
        "primary_keys": dict(init_database.EXPECTED_PRIMARY_KEYS),
        "unique_constraints": set(init_database.EXPECTED_UNIQUES),
        "foreign_keys": set(init_database.EXPECTED_FOREIGN_KEYS),
        "check_constraints": dict(init_database.EXPECTED_CHECKS),
        "indexes": dict(init_database.EXPECTED_INDEXES),
    }


class FakeCursor:
    def __init__(self, tables, events, ddl_error=None):
        self.tables = tables
        self.events = events
        self.ddl_error = ddl_error
        self.last_sql = ""

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql):
        self.last_sql = sql
        if "CREATE TABLE valoper_profiles" in sql:
            self.events.append("ddl")
            if self.ddl_error: raise self.ddl_error
        else:
            self.events.append("inspect")
    def fetchall(self): return [(name,) for name in self.tables]


class FakeConnection:
    def __init__(self, tables, events, ddl_error=None):
        self.cursor_instance = FakeCursor(tables, events, ddl_error)
        self.events = events
        self.commits = 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return self.cursor_instance
    def commit(self):
        self.commits += 1
        self.events.append("commit")


class CanonicalSchemaTests(unittest.TestCase):
    def test_schema_and_migration_have_identical_valopers_ddl(self):
        schema = (ROOT / "database/schema.sql").read_text()
        migration = (ROOT / "database/migrations/0001_add_valopers_persistence.sql").read_text()
        self.assertEqual(schema[schema.index("CREATE TABLE valoper_profiles"):], migration)

    def test_required_schema_contract_is_present(self):
        sql = (ROOT / "database/schema.sql").read_text()
        for fragment in [
            "CREATE TABLE valoper_profiles", "operator_address TEXT PRIMARY KEY",
            "signing_address TEXT NOT NULL", "signing_pubkey TEXT NOT NULL",
            "UNIQUE (signing_address)", "UNIQUE (signing_pubkey)",
            "server_type IN ('cloud', 'on-prem', 'data-center')",
            "source_height >= 1", "char_length(moniker) BETWEEN 1 AND 32",
            "octet_length(description) BETWEEN 1 AND 2048",
            "CREATE INDEX valoper_profiles_list_position_idx",
            "CREATE INDEX valoper_profiles_moniker_idx",
            "CREATE TABLE valopers_snapshot_state", "page_count BETWEEN 0 AND 20",
            "profile_count BETWEEN 0 AND 1000",
        ]:
            self.assertIn(fragment, sql)
        valopers_sql = sql[sql.index("CREATE TABLE valoper_profiles"):]
        self.assertNotIn("REFERENCES validators", valopers_sql)
        self.assertNotIn("INSERT INTO valopers_snapshot_state", valopers_sql)
        for forbidden in ["DROP ", "TRUNCATE ", "DELETE FROM ", "ALTER TABLE", "CASCADE"]:
            self.assertNotIn(forbidden, valopers_sql.upper())


class CompatibilityTests(unittest.TestCase):
    def test_expected_snapshot_passes(self):
        init_database.validate_schema_snapshot(expected_snapshot())

    def test_legacy_and_missing_new_tables_fail(self):
        for table in migrate_valopers_schema.NEW_TABLES:
            snapshot = expected_snapshot()
            snapshot["tables"].remove(table)
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.validate_schema_snapshot(snapshot)

    def test_incompatible_valopers_catalog_objects_fail(self):
        mutations = []
        wrong_type = expected_snapshot()
        wrong_type["columns"]["valoper_profiles"]["source_height"] = ("integer", "NO", "", None)
        mutations.append(wrong_type)
        missing_unique = expected_snapshot()
        missing_unique["unique_constraints"].remove(("valoper_profiles", ("signing_address",)))
        mutations.append(missing_unique)
        missing_check = expected_snapshot()
        del missing_check["check_constraints"]["valoper_profiles_source_height_check"]
        mutations.append(missing_check)
        missing_index = expected_snapshot()
        del missing_index["indexes"]["valoper_profiles_moniker_idx"]
        mutations.append(missing_index)
        for snapshot in mutations:
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.validate_schema_snapshot(snapshot)

    def test_postgresql_expanded_between_catalog_forms_pass(self):
        snapshot = expected_snapshot()
        catalog_forms = {
            "valoper_profiles_moniker_length_check": "((char_length(moniker) >= 1) AND (char_length(moniker) <= 32))",
            "valoper_profiles_description_length_check": "((octet_length(description) >= 1) AND (octet_length(description) <= 2048))",
            "valoper_profiles_signing_pubkey_check": "((signing_pubkey ~ '^gpub1[023456789acdefghjklmnpqrstuvwxyz]+$'::text) AND (octet_length(signing_pubkey) >= 91) AND (octet_length(signing_pubkey) <= 256))",
            "valopers_snapshot_state_page_count_check": "((page_count >= 0) AND (page_count <= 20))",
            "valopers_snapshot_state_profile_count_check": "((profile_count >= 0) AND (profile_count <= 1000))",
        }
        snapshot["check_constraints"].update(catalog_forms)
        init_database.validate_schema_snapshot(snapshot)

    def test_changed_missing_or_additional_bound_conjunct_fails(self):
        mutations = [
            ("valoper_profiles_moniker_length_check", "char_length(moniker) >= 2 AND char_length(moniker) <= 32"),
            ("valoper_profiles_description_length_check", "octet_length(description) >= 1 AND octet_length(description) <= 2047"),
            ("valoper_profiles_signing_pubkey_check", "signing_pubkey ~ '^gpub1[023456789acdefghjklmnpqrstuvwxyz]+$' AND octet_length(signing_pubkey) >= 91"),
            ("valopers_snapshot_state_page_count_check", "page_count >= 0 AND page_count <= 20 AND page_count <> 10"),
            ("valopers_snapshot_state_profile_count_check", "profile_count <= 1000"),
        ]
        for name, expression in mutations:
            with self.subTest(name=name):
                snapshot = expected_snapshot()
                snapshot["check_constraints"][name] = expression
                with self.assertRaises(init_database.SchemaCompatibilityError):
                    init_database.validate_schema_snapshot(snapshot)


class MigrationScriptTests(unittest.TestCase):
    def run_migration(self, tables, snapshot=None, ddl_error=None):
        events = []
        connection = FakeConnection(tables, events, ddl_error)
        with patch("scripts.migrate_valopers_schema.fetch_schema_snapshot", side_effect=lambda cursor: events.append("snapshot") or (snapshot or expected_snapshot())), patch("scripts.migrate_valopers_schema.validate_schema_snapshot", side_effect=lambda value: events.append("validate") or init_database.validate_schema_snapshot(value)):
            result = migrate_valopers_schema.migrate_valopers_schema(
                "postgresql://safe", connect=lambda url: connection
            )
        return result, connection, events

    def test_help_runs_directly(self):
        result = subprocess.run([sys.executable, "scripts/migrate_valopers_schema.py", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_legacy_migrates_then_validates_before_commit(self):
        result, connection, events = self.run_migration(migrate_valopers_schema.LEGACY_TABLES)
        self.assertEqual(result, "applied")
        self.assertEqual(events.count("ddl"), 1)
        self.assertLess(events.index("ddl"), events.index("snapshot"))
        self.assertLess(events.index("validate"), events.index("commit"))
        self.assertEqual(connection.commits, 1)

    def test_compatible_rerun_executes_no_ddl(self):
        result, connection, events = self.run_migration(init_database.EXPECTED_TABLES)
        self.assertEqual(result, "already-compatible")
        self.assertNotIn("ddl", events)
        self.assertEqual(connection.commits, 0)

    def test_all_other_table_sets_fail_without_commit(self):
        states = [set(), migrate_valopers_schema.LEGACY_TABLES - {"blocks"},
                  migrate_valopers_schema.LEGACY_TABLES | {"unexpected"},
                  migrate_valopers_schema.LEGACY_TABLES | {"valoper_profiles"},
                  migrate_valopers_schema.LEGACY_TABLES | {"valopers_snapshot_state"}]
        for tables in states:
            with self.subTest(tables=tables):
                events = []
                connection = FakeConnection(tables, events)
                with self.assertRaises(migrate_valopers_schema.MigrationPreconditionError):
                    migrate_valopers_schema.migrate_valopers_schema("postgresql://safe", connect=lambda url: connection)
                self.assertEqual(connection.commits, 0)

    def test_sql_and_validation_errors_do_not_commit(self):
        events = []
        connection = FakeConnection(migrate_valopers_schema.LEGACY_TABLES, events, RuntimeError("secret DSN"))
        with self.assertRaises(RuntimeError):
            migrate_valopers_schema.migrate_valopers_schema("postgresql://safe", connect=lambda url: connection)
        self.assertEqual(connection.commits, 0)
        bad = expected_snapshot(); bad["tables"].remove("valoper_profiles")
        with self.assertRaises(init_database.SchemaCompatibilityError):
            self.run_migration(migrate_valopers_schema.LEGACY_TABLES, bad)

    def test_missing_file_opens_no_connection(self):
        called = []
        with self.assertRaises(FileNotFoundError):
            migrate_valopers_schema.migrate_valopers_schema("postgresql://safe", Path("missing.sql"), lambda url: called.append(url))
        self.assertEqual(called, [])

    def test_main_failure_is_bounded_and_redacts_credentials(self):
        err = io.StringIO()
        secret = "postgresql://user:password@host/database"
        with patch.dict(os.environ, {"DATABASE_URL": secret}, clear=True), patch("scripts.migrate_valopers_schema.migrate_valopers_schema", side_effect=RuntimeError(secret)), contextlib.redirect_stderr(err):
            self.assertEqual(migrate_valopers_schema.main([]), 1)
        self.assertEqual(err.getvalue(), "Valopers schema migration failed\n")
        self.assertNotIn("password", err.getvalue())

    def test_missing_database_url_fails_safely(self):
        err = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(err):
            self.assertEqual(migrate_valopers_schema.main([]), 1)
        self.assertEqual(err.getvalue(), "Valopers schema migration failed\n")

    def test_empty_database_prints_init_guidance(self):
        err = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://safe"}), patch("scripts.migrate_valopers_schema.migrate_valopers_schema", side_effect=migrate_valopers_schema.MigrationPreconditionError("empty public schema; use python scripts/init_database.py")), contextlib.redirect_stderr(err):
            self.assertEqual(migrate_valopers_schema.main([]), 1)
        self.assertIn("python scripts/init_database.py", err.getvalue())


if __name__ == "__main__":
    unittest.main()
