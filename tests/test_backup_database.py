import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import backup_database


class BackupScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.compose_file = self.directory / "compose.yml"
        self.compose_file.write_text("services: {}")
        self.env_file = self.directory / "postgres.env"
        self.env_file.write_text("POSTGRES_DB=x")

    def run_backup(self, filename, validation_returncode=0, dump_returncode=0):
        def fake_run(command, stdout=None, stdin=None, stderr=None, check=False):
            if "pg_dump" in " ".join(command):
                stdout.write(b"archive")
                return subprocess.CompletedProcess(command, dump_returncode)
            return subprocess.CompletedProcess(command, validation_returncode)

        with patch("scripts.backup_database.backup_filename", return_value=filename), patch("subprocess.run", side_effect=fake_run):
            return backup_database.create_backup(self.directory, self.compose_file, self.env_file)

    def test_parser_has_no_configurable_retention(self):
        args = backup_database.build_parser().parse_args([])
        self.assertFalse(hasattr(args, "retention"))
        with self.assertRaises(SystemExit):
            backup_database.build_parser().parse_args(["--retention", "3"])

    def test_backup_filename_uses_utc_timestamp(self):
        name = backup_database.backup_filename(datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(name, "utsa-gno-explorer-20260715T010203Z.dump")
        self.assertRegex(name, backup_database.BACKUP_RE)

    def test_successful_backup_leaves_exactly_one_dump(self):
        final = self.run_backup("utsa-gno-explorer-20260715T010203Z.dump")
        self.assertEqual(backup_database.successful_backups(self.directory), [final])
        self.assertFalse(final.with_suffix(".dump.part").exists())

    def test_second_successful_backup_replaces_previous_dump(self):
        old = self.run_backup("utsa-gno-explorer-20260715T010203Z.dump")
        new = self.run_backup("utsa-gno-explorer-20260716T010203Z.dump")
        self.assertFalse(old.exists())
        self.assertEqual(backup_database.successful_backups(self.directory), [new])

    def test_dump_failure_preserves_previous_valid_backup(self):
        old = self.run_backup("utsa-gno-explorer-20260715T010203Z.dump")
        with self.assertRaises(RuntimeError):
            self.run_backup("utsa-gno-explorer-20260716T010203Z.dump", dump_returncode=1)
        self.assertEqual(backup_database.successful_backups(self.directory), [old])
        self.assertFalse((self.directory / "utsa-gno-explorer-20260716T010203Z.dump.part").exists())

    def test_validation_failure_preserves_previous_valid_backup(self):
        old = self.run_backup("utsa-gno-explorer-20260715T010203Z.dump")
        with self.assertRaises(RuntimeError):
            self.run_backup("utsa-gno-explorer-20260716T010203Z.dump", validation_returncode=1)
        self.assertEqual(backup_database.successful_backups(self.directory), [old])
        self.assertFalse((self.directory / "utsa-gno-explorer-20260716T010203Z.dump.part").exists())

    def test_temporary_and_incomplete_files_are_not_current_backups(self):
        part = self.directory / "utsa-gno-explorer-20260715T010203Z.dump.part"
        part.write_bytes(b"incomplete")
        unrelated = self.directory / "manual.dump"
        unrelated.write_bytes(b"unverified")
        self.assertEqual(backup_database.successful_backups(self.directory), [])
        final = self.run_backup("utsa-gno-explorer-20260716T010203Z.dump")
        self.assertEqual(backup_database.successful_backups(self.directory), [final])
        self.assertTrue(part.exists())
        self.assertTrue(unrelated.exists())

    def test_commands_do_not_put_credentials_in_arguments(self):
        dump = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "sh", "-c", 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges')
        restore = backup_database.compose_command(Path("compose.yml"), Path("env"), "exec", "-T", "postgres", "pg_restore", "--list")
        self.assertNotIn("POSTGRES_PASSWORD", " ".join(dump + restore))
        self.assertEqual(restore[-2:], ["pg_restore", "--list"])


if __name__ == "__main__":
    unittest.main()
