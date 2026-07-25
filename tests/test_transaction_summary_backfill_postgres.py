"""PostgreSQL integration coverage for the manual summary backfill."""
import os
import shutil
import subprocess
import time
import unittest
import uuid

from indexer.transaction_summary import generic_summary
from indexer.transaction_summary_backfill import (
    conditional_update, release_advisory_lock, select_candidates, try_advisory_lock,
)

try:
    import psycopg
except ImportError:
    psycopg = None


def docker_available():
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_INTEGRATION") == "1", "set RUN_POSTGRES_INTEGRATION=1")
@unittest.skipUnless(psycopg is not None and docker_available(), "PostgreSQL Docker dependencies are required")
class BackfillPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = f"utsa-backfill-{os.getpid()}"
        cls.password = uuid.uuid4().hex
        subprocess.run([
            "docker", "run", "--rm", "-d", "--name", cls.container,
            "-e", f"POSTGRES_PASSWORD={cls.password}", "-p", "127.0.0.1::5432", "postgres:16.14-bookworm",
        ], check=True, stdout=subprocess.DEVNULL)
        for _ in range(60):
            if subprocess.run(["docker", "exec", cls.container, "pg_isready", "-U", "postgres"], stdout=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        port = subprocess.check_output(["docker", "port", cls.container, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
        cls.url = f"postgresql://postgres:{cls.password}@127.0.0.1:{port}/postgres"
        env = dict(os.environ, DATABASE_URL=cls.url)
        subprocess.run(["python", "scripts/init_database.py"], env=env, check=True, stdout=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], stdout=subprocess.DEVNULL)

    def setUp(self):
        self.connection = psycopg.connect(self.url, autocommit=True)
        with self.connection.cursor() as cursor:
            cursor.execute("TRUNCATE transactions, blocks CASCADE")
            cursor.executemany(
                "INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (%s,'YQ==',%s,now(),1)",
                [(10, "A" * 64), (11, "B" * 64), (12, "C" * 64)],
            )

    def tearDown(self):
        self.connection.close()

    def insert_tx(self, height, index, status="decoded", length=1, summary=None):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO transactions (block_height,tx_index,raw_base64,raw_base64_length,decoded_bytes,decoded_byte_length,decode_status,tx_hash_hex,payload_summary) VALUES (%s,%s,'YQ==',4,%s,%s,%s,%s,%s) RETURNING id",
                (height, index, b"a" if length is not None else None, length, status, uuid.uuid4().hex.upper().ljust(64, "0")[:64], psycopg.types.json.Jsonb(summary) if summary else None),
            )
            return cursor.fetchone()[0]

    def test_selection_order_limit_terminal_results_and_race(self):
        old = self.insert_tx(10, 0)
        newest = self.insert_tx(12, 0, summary=generic_summary())
        self.insert_tx(11, 0, status="invalid_base64", length=None)
        parsed = generic_summary("parsed"); parsed["chain_family"] = "gno"
        self.insert_tx(11, 1, summary=parsed)
        self.assertEqual([row.id for row in select_candidates(self.connection, 1)], [newest])
        before = self.connection.execute("SELECT raw_base64,decoded_byte_length,block_height,tx_index FROM transactions WHERE id=%s", (newest,)).fetchone()
        self.assertTrue(conditional_update(self.connection, newest, parsed))
        after = self.connection.execute("SELECT raw_base64,decoded_byte_length,block_height,tx_index FROM transactions WHERE id=%s", (newest,)).fetchone()
        self.assertEqual(before, after)
        self.assertEqual([row.id for row in select_candidates(self.connection, 10)], [old])
        self.connection.execute("UPDATE transactions SET payload_summary=%s WHERE id=%s", (psycopg.types.json.Jsonb(parsed), old))
        self.assertFalse(conditional_update(self.connection, old, generic_summary("unsupported")))

    def test_session_lock_does_not_block_ordinary_work(self):
        other = psycopg.connect(self.url, autocommit=True)
        try:
            self.assertTrue(try_advisory_lock(self.connection))
            self.assertFalse(try_advisory_lock(other))
            self.assertEqual(other.execute("SELECT 1").fetchone()[0], 1)
            self.insert_tx(10, 0)
        finally:
            release_advisory_lock(self.connection)
            other.close()
