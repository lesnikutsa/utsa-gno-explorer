import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import backup_database, wait_for_postgres

ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def text(self, relative):
        return (ROOT / relative).read_text()

    def test_compose_postgres_runtime_is_pinned_local_and_persistent(self):
        compose = self.text("deploy/postgres/compose.yml")
        self.assertIn("image: postgres:16.4-bookworm", compose)
        self.assertNotIn(":latest", compose)
        self.assertIn('"127.0.0.1:${POSTGRES_PORT}:5432"', compose)
        self.assertIn("source: ${POSTGRES_DATA_DIR}", compose)
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

    def test_documentation_links_exist(self):
        for relative in ["README.md", "database/README.md", "docs/operator-runbook.md"]:
            self.assertIn("production-deployment.md", self.text(relative))
        self.assertTrue((ROOT / "docs/production-deployment.md").is_file())


class BackupScriptTests(unittest.TestCase):
    def test_backup_filename_uses_utc_timestamp(self):
        name = backup_database.backup_filename(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(name, "utsa-gno-explorer-20260715T010203Z.dump")
        self.assertRegex(name, backup_database.BACKUP_RE)

    def test_successful_backup_renames_part_and_applies_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old = directory / "utsa-gno-explorer-20260101T000000Z.dump"
            old.write_bytes(b"old")
            unrelated = directory / "notes.txt"
            unrelated.write_text("keep")

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                if "pg_dump" in " ".join(command):
                    stdout.write(b"archive")
                return type("Result", (), {"returncode": 0})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                final = backup_database.create_backup(directory, Path("compose.yml"), Path("env"), retention=1)

            self.assertTrue(final.exists())
            self.assertFalse(final.with_suffix(final.suffix + ".part").exists())
            self.assertFalse(old.exists())
            self.assertTrue(unrelated.exists())

    def test_failed_dump_removes_part_without_final_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
                return type("Result", (), {"returncode": 1})()

            with patch("scripts.backup_database.backup_filename", return_value="utsa-gno-explorer-20260715T010203Z.dump"), patch("subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    backup_database.create_backup(directory, Path("compose.yml"), Path("env"), retention=1)
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump").exists())
            self.assertFalse((directory / "utsa-gno-explorer-20260715T010203Z.dump.part").exists())

    def test_retention_never_removes_newest_or_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
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
