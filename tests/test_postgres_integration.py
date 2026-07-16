import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    psycopg = None

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16.14-bookworm"


def docker_available():
    return shutil.which("docker") is not None and subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_INTEGRATION") == "1", "set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests")
@unittest.skipUnless(psycopg is not None, "psycopg is required for PostgreSQL integration tests")
@unittest.skipUnless(docker_available(), "Docker is required for PostgreSQL integration tests")
class PostgresSchemaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.container = f"utsa-gno-schema-test-{os.getpid()}"
        cls.password = secrets.token_urlsafe(24)
        cls.password_file = Path(cls.temp.name) / "postgres-password"
        cls.password_file.write_text(cls.password)
        subprocess.run([
            "docker", "run", "--rm", "-d", "--name", cls.container,
            "-e", "POSTGRES_USER=utsa_test",
            "-e", "POSTGRES_DB=utsa_gno_explorer",
            "-e", "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
            "-v", f"{cls.password_file}:/run/secrets/postgres_password:ro",
            "-p", "127.0.0.1::5432",
            IMAGE,
        ], check=True, stdout=subprocess.DEVNULL)
        try:
            for attempt in range(60):
                ready = subprocess.run(["docker", "exec", cls.container, "pg_isready", "-U", "utsa_test", "-d", "utsa_gno_explorer"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("PostgreSQL integration container did not become ready")
            port_output = subprocess.check_output(["docker", "port", cls.container, "5432/tcp"], text=True).strip()
            cls.host, cls.port = port_output.rsplit(":", 1)
            cls.database_url = f"postgresql://utsa_test:{cls.password}@{cls.host}:{cls.port}/utsa_gno_explorer"
        except Exception:
            subprocess.run(["docker", "rm", "-f", cls.container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        cls.temp.cleanup()

    def run_init(self, database_url=None, schema_path=None):
        env = dict(os.environ, DATABASE_URL=database_url or self.database_url)
        command = [sys.executable, "scripts/init_database.py"]
        if schema_path is not None:
            command += ["--schema", str(schema_path)]
        return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)

    def connect(self, database="utsa_gno_explorer"):
        return psycopg.connect(f"postgresql://utsa_test:{self.password}@{self.host}:{self.port}/{database}")

    def create_database(self, name):
        with self.connect("postgres") as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE {name}")

    def test_empty_database_initializes_and_second_run_validates(self):
        first = self.run_init()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn(self.password, first.stdout + first.stderr)
        second = self.run_init()
        self.assertEqual(second.returncode, 0, second.stderr)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            self.assertEqual(cursor.fetchone()[0], 8)
            cursor.execute("SELECT conname FROM pg_constraint WHERE conname = 'validator_signatures_height_signing_address_fkey'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'rpc_endpoints_one_selected_per_chain_idx'")
            self.assertIsNotNone(cursor.fetchone())

    def test_incompatible_schema_is_rejected(self):
        bad_database = f"utsa_bad_schema_{os.getpid()}"
        self.create_database(bad_database)
        bad_url = f"postgresql://utsa_test:{self.password}@{self.host}:{self.port}/{bad_database}"
        with psycopg.connect(bad_url) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE blocks(height integer PRIMARY KEY)")
            connection.commit()
        result = self.run_init(bad_url)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SchemaCompatibilityError", result.stderr)
        self.assertNotIn(self.password, result.stderr)

    def test_failed_initialization_rolls_back_partial_tables(self):
        failed_database = f"utsa_failed_schema_{os.getpid()}"
        self.create_database(failed_database)
        failed_url = f"postgresql://utsa_test:{self.password}@{self.host}:{self.port}/{failed_database}"
        bad_schema = Path(self.temp.name) / "bad_schema.sql"
        bad_schema.write_text("CREATE TABLE should_roll_back(id integer PRIMARY KEY);\nSELECT broken syntax;\n")
        result = self.run_init(failed_url, bad_schema)
        self.assertNotEqual(result.returncode, 0)
        with psycopg.connect(failed_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.should_roll_back')")
            self.assertIsNone(cursor.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
