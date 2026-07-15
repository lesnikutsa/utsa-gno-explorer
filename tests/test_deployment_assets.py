import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import backup_database, init_database, wait_for_postgres

ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def text(self, relative):
        return (ROOT / relative).read_text()

    def test_compose_postgres_runtime_is_pinned_local_and_persistent(self):
        compose = self.text("deploy/postgres/compose.yml")
        self.assertIn("image: postgres:16.14-bookworm", compose)
        self.assertNotIn(":latest", compose)
        self.assertIn('"127.0.0.1:${POSTGRES_PORT:-5432}:5432"', compose)
        self.assertIn("source: ${POSTGRES_DATA_DIR:-/var/lib/utsa-gno-explorer/postgres}", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("pg_isready", compose)
        self.assertNotIn("git pull", compose)

    def test_compose_uses_external_password_file_and_no_real_secret(self):
        compose = self.text("deploy/postgres/compose.yml")
        example = self.text("deploy/postgres/postgres.env.example")
        self.assertIn("POSTGRES_PASSWORD_FILE", compose)
        self.assertIn("/etc/utsa-gno-explorer/postgres-password", compose)
        self.assertNotIn("POSTGRES_PASSWORD:", compose)
        self.assertIn("POSTGRES_DATA_DIR=/var/lib/utsa-gno-explorer/postgres", example)
        self.assertNotIn("postgres:16.4", compose)
        self.assertNotRegex(example, r"password|secret|token", msg="postgres example should not contain secret values")

    def test_systemd_unit_contains_expected_runtime_directives(self):
        unit = self.text("deploy/systemd/utsa-gno-indexer.service")
        expected = [
            "User=utsa-gno",
            "Group=utsa-gno",
            "WorkingDirectory=/opt/utsa-gno-explorer",
            "EnvironmentFile=/etc/utsa-gno-explorer/indexer.env",
            "ExecStart=/opt/utsa-gno-explorer/.venv/bin/python scripts/run_indexer.py",
            "Restart=on-failure",
            "KillSignal=SIGTERM",
            "TimeoutStopSec=180",
            "Wants=network-online.target docker.service",
            "After=network-online.target docker.service",
            "ExecStartPre=/opt/utsa-gno-explorer/.venv/bin/python /opt/utsa-gno-explorer/scripts/wait_for_postgres.py",
            "NoNewPrivileges=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ]
        for value in expected:
            self.assertIn(value, unit)
        self.assertNotIn("git pull", unit)
        self.assertNotIn("--start-height", unit)

    def test_example_indexer_env_uses_placeholders(self):
        env = self.text("deploy/systemd/indexer.env.example")
        self.assertIn("REPLACE_WITH_PASSWORD", env)
        self.assertIn("REPLACE_WITH_FIRST_EMPTY_DATABASE_HEIGHT", env)
        self.assertNotIn("change-me", env)

    def test_gitignore_protects_secret_like_files_without_examples(self):
        ignore = self.text(".gitignore")
        self.assertIn("deploy/**/.env", ignore)
        self.assertIn("deploy/**/*password*", ignore)
        self.assertIn("*.local.env", ignore)
        self.assertNotRegex(ignore, r"^\*\.example$", msg="do not ignore committed example files")

    def test_documentation_uses_safe_compose_exec_commands(self):
        doc = self.text("docs/production-deployment.md")
        self.assertNotIn('psql "$DATABASE_URL"', doc)
        self.assertIn("exec postgres sh -c 'pg_isready -U", doc)
        self.assertIn("systemd-analyze verify", doc)
        self.assertIn("systemd-analyze security", doc)

    def test_init_database_help_runs(self):
        result = subprocess.run([sys.executable, "scripts/init_database.py", "--help"], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--schema", result.stdout)

    def test_documentation_links_exist(self):
        for relative in ["README.md", "database/README.md", "docs/operator-runbook.md"]:
            self.assertIn("production-deployment.md", self.text(relative))
        self.assertTrue((ROOT / "docs/production-deployment.md").is_file())


class SchemaValidationTests(unittest.TestCase):
    def snapshot(self):
        return {
            "tables": set(init_database.EXPECTED_TABLES),
            "columns": {table: dict(columns) for table, columns in init_database.EXPECTED_COLUMNS.items()},
            "primary_keys": dict(init_database.EXPECTED_PRIMARY_KEYS),
            "unique_constraints": set(init_database.EXPECTED_UNIQUES),
            "foreign_keys": set(init_database.EXPECTED_FOREIGN_KEYS),
            "check_constraints": set(init_database.EXPECTED_CHECKS),
            "indexes": {name: "CREATE UNIQUE INDEX rpc_endpoints_one_selected_per_chain_idx ON public.rpc_endpoints USING btree (chain_id) WHERE is_selected" if name == "rpc_endpoints_one_selected_per_chain_idx" else "CREATE INDEX %s ON public.%s USING btree (%s)" % (name, spec["table"], ", ".join(spec["must_contain"])) for name, spec in init_database.EXPECTED_INDEXES.items()},
        }

    def test_compatible_schema_snapshot_passes(self):
        init_database.validate_schema_snapshot(self.snapshot())

    def test_empty_database_initialization_runs_schema_transactionally(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.snapshot = self_outer.snapshot()
            def execute(self, sql):
                self.calls.append(sql)
            def fetchall(self):
                if "information_schema.tables" in self.calls[-1]:
                    return [] if len(self.calls) == 1 else [(t,) for t in self.snapshot["tables"]]
                if "information_schema.columns" in self.calls[-1]:
                    return [(t, c, v[0], v[1]) for t, cols in self.snapshot["columns"].items() for c, v in cols.items()]
                if "table_constraints" in self.calls[-1]:
                    rows = []
                    for t, cols in self.snapshot["primary_keys"].items():
                        rows += [(t, "PRIMARY KEY", f"{t}_pkey", c, None) for c in cols]
                    for t, cols in init_database.EXPECTED_UNIQUES:
                        rows += [(t, "UNIQUE", f"{t}_{c}_unique", c, None) for c in cols]
                    for t, cols, ref in init_database.EXPECTED_FOREIGN_KEYS:
                        rows += [(t, "FOREIGN KEY", f"{t}_fk", c, ref) for c in cols]
                    rows += [("blocks", "CHECK", c, None, None) for c in init_database.EXPECTED_CHECKS]
                    return rows
                if "pg_indexes" in self.calls[-1]:
                    return list(self.snapshot["indexes"].items())
                return []
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def __init__(self): self.cursor_obj = Cursor(); self.committed = False
            def cursor(self): return self.cursor_obj
            def commit(self): self.committed = True
            def __enter__(self): return self
            def __exit__(self, *a): return False
        self_outer = self
        conn = Conn()
        with tempfile.NamedTemporaryFile("w") as schema:
            schema.write("CREATE TABLE blocks(height bigint primary key);")
            schema.flush()
            with patch("scripts.init_database.fetch_schema_snapshot", return_value=self.snapshot()):
                init_database.initialize_or_validate("postgresql://user:secret@host/db", Path(schema.name), connect=lambda url: conn)
        self.assertTrue(conn.committed)
        self.assertIn("CREATE TABLE blocks", "\n".join(conn.cursor_obj.calls))

    def test_missing_table_fails(self):
        snapshot = self.snapshot(); snapshot["tables"].remove("blocks")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_partial_schema_fails(self):
        snapshot = self.snapshot(); snapshot["tables"] = {"blocks", "transactions"}
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_column_type_fails(self):
        snapshot = self.snapshot(); snapshot["columns"]["blocks"]["height"] = ("integer", "NO")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_missing_constraint_fails(self):
        snapshot = self.snapshot(); snapshot["check_constraints"].remove("indexer_state_default_key")
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_wrong_index_definition_fails(self):
        snapshot = self.snapshot(); snapshot["indexes"]["rpc_endpoints_one_selected_per_chain_idx"] = "CREATE INDEX bad ON rpc_endpoints(chain_id)"
        with self.assertRaises(init_database.SchemaCompatibilityError): init_database.validate_schema_snapshot(snapshot)

    def test_init_database_does_not_use_subprocess_argv_for_database_url(self):
        self.assertNotIn("subprocess", Path("scripts/init_database.py").read_text())

    def test_init_database_main_sanitizes_error_output(self):
        err = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:secret@host/db"}, clear=True), patch("scripts.init_database.initialize_or_validate", side_effect=RuntimeError("failed postgresql://user:secret@host/db")), contextlib.redirect_stderr(err):
            code = init_database.main([])
        self.assertEqual(code, 1)
        self.assertNotIn("secret", err.getvalue())

    def test_missing_database_url_is_concise(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL is required"):
            init_database.initialize_or_validate("")


class BackupScriptTests(unittest.TestCase):
    def test_backup_filename_uses_utc_timestamp(self):
        name = backup_database.backup_filename(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(name, "utsa-gno-explorer-20260715T010203Z.dump")
        self.assertRegex(name, backup_database.BACKUP_RE)

    def test_backup_command_construction_uses_expected_flags(self):
        dump = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "sh", "-c", "pg_dump -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -Fc --no-owner --no-privileges")
        restore = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "pg_restore", "--list")
        self.assertIn("--no-owner", dump[-1])
        self.assertIn("--no-privileges", dump[-1])
        self.assertEqual(restore[-2:], ["pg_restore", "--list"])
        self.assertNotIn("-", restore)

    def test_negative_retention_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            with self.assertRaises(ValueError):
                backup_database.create_backup(directory, compose_file, env_file, retention=-1)

    def test_successful_backup_renames_part_and_applies_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            old.write_bytes(b"old")
            unrelated = directory / "notes.txt"
            unrelated.write_text("keep")

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                if "pg_dump" in " ".join(command):
                    stdout.write(b"archive")
                return type("Result", (), {"returncode": 0})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                final = backup_database.create_backup(directory, compose_file, env_file, retention=1)

            self.assertTrue(final.exists())
            self.assertFalse(final.with_suffix(final.suffix + ".part").exists())
            self.assertFalse(old.exists())
            self.assertTrue(unrelated.exists())

    def test_failed_dump_removes_part_without_final_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                return type("Result", (), {"returncode": 1})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    backup_database.create_backup(directory, compose_file, env_file, retention=1)
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump").exists())
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump.part").exists())


    def test_failed_archive_validation_removes_part_without_final_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            calls = []
            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                calls.append(command)
                if "pg_dump" in " ".join(command):
                    stdout.write(b"archive")
                    return type("Result", (), {"returncode": 0})()
                return type("Result", (), {"returncode": 1})()
            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    backup_database.create_backup(directory, compose_file, env_file, retention=1)
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump").exists())
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump.part").exists())

    def test_retention_never_removes_newest_or_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            compose_file = directory / "compose.yml"; compose_file.write_text("services: {}")
            env_file = directory / "postgres.env"; env_file.write_text("POSTGRES_DB=x")
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            newest = directory / "utsa-gno-explorer-20260715T010203Z.dump"
            symlink = directory / "utsa-gno-explorer-20260102T000000Z.dump"
            unrelated = directory / "utsa-gno-explorer-not-a-date.dump"
            old.write_text("old")
            newest.write_text("new")
            unrelated.write_text("keep")
            symlink.symlink_to(old)
            backup_database.apply_retention(directory, keep=1, newest=newest)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(symlink.is_symlink())


class WaitForPostgresTests(unittest.TestCase):
    def setUp(self):
        wait_for_postgres._STOP = False

    def test_success_does_not_print_database_url(self):
        calls = []

        class Conn:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def connect(url, connect_timeout):
            calls.append((url, connect_timeout))
            return Conn()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = wait_for_postgres.wait_for_postgres("postgresql://user:secret@localhost/db", 1, 1, connect=connect)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", out.getvalue())

    def test_retry_then_success_without_real_sleep(self):
        attempts = []
        times = iter([0, 0, 0.1])

        def connect(url, connect_timeout):
            attempts.append(url)
            if len(attempts) == 1:
                raise RuntimeError("not yet")
            return contextlib.nullcontext()

        ok = wait_for_postgres.wait_for_postgres("postgresql://safe", 5, 1, connect=connect, sleep=lambda _: None, monotonic=lambda: next(times, 0.2))
        self.assertTrue(ok)
        self.assertEqual(len(attempts), 2)

    def test_permanent_configuration_error_does_not_retry(self):
        attempts = []
        err = io.StringIO()
        class ProgrammingError(Exception): pass
        def connect(*args, **kwargs):
            attempts.append(1)
            raise ProgrammingError("invalid dsn contains secret")
        with contextlib.redirect_stderr(err):
            ok = wait_for_postgres.wait_for_postgres("postgresql://user:secret@localhost/db", 60, 1, connect=connect, sleep=lambda _: None)
        self.assertFalse(ok)
        self.assertEqual(len(attempts), 1)
        self.assertNotIn("secret", err.getvalue())

    def test_timeout_sanitizes_output(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ok = wait_for_postgres.wait_for_postgres(
                "postgresql://user:secret@localhost/db",
                0,
                1,
                connect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                sleep=lambda _: None,
                monotonic=lambda: 0,
            )
        self.assertFalse(ok)
        self.assertNotIn("secret", err.getvalue())
        self.assertIn("timed out", err.getvalue())

    def test_interrupted_wait_returns_false(self):
        wait_for_postgres._STOP = True
        self.assertFalse(wait_for_postgres.wait_for_postgres("postgresql://safe", 1, 1, connect=lambda *a, **k: contextlib.nullcontext(), sleep=lambda _: None))


if __name__ == "__main__":
    unittest.main()
