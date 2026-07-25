import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app import _transaction_detail_from_row
from api.config import ApiConfig
from api.database import (
    ACTIVE_VALIDATORS_SQL,
    NETWORK_DISTRIBUTION_SQL,
    NETWORK_SQL,
    VALIDATOR_IDENTITY_SQL,
    ApiDatabase,
    MissingIndexerStateError,
)
from indexer.database import PostgresDatabase, _upsert_transactions
from indexer.parsers import parse_tx
from indexer.transaction_summary import MAX_SUMMARY_BYTES, summary_size_bytes
from indexer.rpc import RpcProbeResult
from indexer.valopers_parser import ValoperProfile
from indexer.valopers_persistence import (
    StaleValopersSnapshot, ValopersChainIdentityError, ValopersSnapshotConflict,
)
from indexer.valopers_snapshot import ValopersSnapshot
from network_distribution.geo import GeoRecord
from network_distribution.persistence import (
    has_geolocated_snapshot, load_geo_cache, save_geo_cache, save_snapshot, select_sources,
)
from scripts import init_database
from scripts.migrate_network_distribution_schema import migrate as migrate_network_distribution_schema

try:
    import psycopg
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    psycopg = None

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16.14-bookworm"
BASE_SHA = "b602e8b36851243b5b556ef8e4eb292a9370b1c2"
LEGACY_TABLES = {
    "blocks", "transactions", "validators", "validator_set_members",
    "validator_signatures", "rpc_endpoints", "rpc_endpoint_checks", "indexer_state",
}


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

    def run_migration(self, database_url, migration_path=None):
        env = dict(os.environ, DATABASE_URL=database_url)
        command = [sys.executable, "scripts/migrate_valopers_schema.py"]
        if migration_path is not None:
            command += ["--migration", str(migration_path)]
        return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)

    def run_transaction_hash_migration(self, database_url):
        env = dict(os.environ, DATABASE_URL=database_url)
        return subprocess.run(
            [sys.executable, "scripts/migrate_transaction_hashes.py"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )

    def connect(self, database="utsa_gno_explorer"):
        return psycopg.connect(f"postgresql://utsa_test:{self.password}@{self.host}:{self.port}/{database}")

    def create_database(self, name):
        with self.connect("postgres") as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE {name}")

    def database_url_for(self, name):
        return f"postgresql://utsa_test:{self.password}@{self.host}:{self.port}/{name}"

    def test_average_block_time_network_query_guards_and_latest_window(self):
        name = f"utsa_average_block_time_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)

        with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as connection, connection.cursor() as cursor:
            def sample(rows):
                cursor.execute("TRUNCATE blocks CASCADE")
                cursor.execute("DELETE FROM indexer_state")
                cursor.executemany(
                    "INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (%s, %s, %s, %s, 0)",
                    [(height, f"hash-{height}", f"{height:064X}", timestamp) for height, timestamp in rows],
                )
                last_height = max(height for height, _ in rows)
                cursor.execute(
                    "INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) VALUES ('default', 'test-13', %s)",
                    (last_height,),
                )
                cursor.execute(NETWORK_SQL, ("default",))
                return cursor.fetchone()

            row = sample([(1, epoch), (2, epoch + timedelta(seconds=4))])
            self.assertEqual((row["average_block_time_seconds"], row["average_block_time_sample_size"]), (4, 2))
            row = sample([(1, epoch), (2, epoch + timedelta(seconds=3)), (3, epoch + timedelta(seconds=8))])
            self.assertEqual(row["average_block_time_seconds"], 4)
            self.assertIsNone(sample([(1, epoch)])["average_block_time_seconds"])
            self.assertIsNone(sample([(1, epoch), (3, epoch + timedelta(seconds=8))])["average_block_time_seconds"])
            self.assertIsNone(sample([(1, epoch), (2, epoch)])["average_block_time_seconds"])

            rows = [(height, epoch + timedelta(seconds=height * 3)) for height in range(1, 12)]
            rows[0] = (1, epoch - timedelta(days=30))
            row = sample(rows)
            self.assertEqual(row["average_block_time_sample_size"], 10)
            self.assertEqual(row["average_block_time_seconds"], 3)

    def test_transaction_hash_constraints_allow_repeated_occurrences(self):
        name = f"utsa_tx_hash_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        tx_hash = hashlib.sha256(b"same").hexdigest().upper()
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (%s, %s, %s, now(), 1)",
                [(100, "ZA==", "64"), (200, "yA==", "C8")],
            )
            cursor.executemany(
                "INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex) VALUES (%s, %s, 'c2FtZQ==', 8, %s, 4, 'decoded', %s)",
                [(100, 0, b"same", tx_hash), (200, 2, b"same", tx_hash)],
            )
            cursor.execute("SELECT block_height, tx_index FROM transactions WHERE tx_hash_hex = %s ORDER BY block_height", (tx_hash,))
            self.assertEqual(cursor.fetchall(), [(100, 0), (200, 2)])
            cursor.execute("SELECT indisunique, pg_get_expr(indpred, indrelid) FROM pg_index WHERE indexrelid = 'transactions_tx_hash_hex_idx'::regclass")
            unique, predicate = cursor.fetchone()
            self.assertFalse(unique)
            self.assertEqual(predicate.strip("()"), "tx_hash_hex IS NOT NULL")

            invalid_rows = [
                ("INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex) VALUES (100, 3, 'YQ==', 4, %s, 1, 'decoded', 'bad')", (b"a",)),
                ("INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status) VALUES (100, 4, 'YQ==', 4, %s, 1, 'decoded')", (b"a",)),
                ("INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decode_status, tx_hash_hex) VALUES (100, 5, 'bad', 3, 'invalid_base64', %s)", (tx_hash,)),
                ("INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex) VALUES (100, 0, 'c2FtZQ==', 8, %s, 4, 'decoded', %s)", (b"same", tx_hash)),
            ]
            for sql, params in invalid_rows:
                with self.assertRaises(Exception), connection.transaction():
                    cursor.execute(sql, params)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE transactions SET tx_hash_hex = %s WHERE block_height = 100", ("F" * 64,))
        mismatch = self.run_transaction_hash_migration(database_url)
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertEqual(mismatch.stderr, "Transaction hash migration failed; ensure the indexer is stopped and inspect the database catalog\n")
        self.assertNotIn(database_url, mismatch.stdout + mismatch.stderr)
        self.assertNotIn(self.password, mismatch.stdout + mismatch.stderr)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE transactions SET tx_hash_hex = %s WHERE block_height = 100", (tx_hash,))
        verified = self.run_transaction_hash_migration(database_url)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(verified.stdout, "Transaction hash schema is already compatible\n")

    def test_transaction_payload_summary_persistence_and_refresh(self):
        name = f"utsa_tx_summary_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        parsed = type("Parsed", (), {"height": 100, "transactions": [parse_tx(0, "YWJj")]})()
        parsed.transactions[0]["payload_summary"] = {"messages": [{"signature": b"unsafe"}]}

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (100, 'ZA==', '64', now(), 1)"
            )
            _upsert_transactions(cursor, parsed)
            cursor.execute("SELECT raw_base64, tx_hash_hex, payload_summary, pg_typeof(payload_summary)::text FROM transactions WHERE block_height = 100 AND tx_index = 0")
            raw_base64, tx_hash, summary, value_type = cursor.fetchone()
            self.assertEqual(summary["schema_version"], 1)
            self.assertEqual(summary["parse_status"], "unparsed")
            self.assertEqual(value_type, "jsonb")

            parsed.transactions[0] = parse_tx(0, "YWJj")
            parsed.transactions[0]["payload_summary"]["parse_status"] = "unsupported"
            _upsert_transactions(cursor, parsed)
            cursor.execute("SELECT count(*), min(raw_base64), min(tx_hash_hex), min(payload_summary->>'parse_status'), bool_and(payload_summary IS NOT NULL) FROM transactions WHERE block_height = 100")
            self.assertEqual(cursor.fetchone(), (1, raw_base64, tx_hash, "unsupported", True))
            cursor.execute("SELECT payload_summary, pg_typeof(payload_summary)::text FROM transactions WHERE block_height = 100 AND tx_index = 0")
            refreshed, refreshed_type = cursor.fetchone()
            self.assertEqual(refreshed_type, "jsonb")
            self.assertLessEqual(summary_size_bytes(refreshed), MAX_SUMMARY_BYTES)

            invalid = parse_tx(1, "not base64!")
            invalid["payload_summary"] = {"raw_base64": b"unsafe"}
            _upsert_transactions(cursor, type("Parsed", (), {"height": 100, "transactions": [invalid]})())
            cursor.execute("SELECT payload_summary->>'parse_status' FROM transactions WHERE block_height = 100 AND tx_index = 1")
            self.assertEqual(cursor.fetchone(), ("invalid",))

            cursor.execute("UPDATE transactions SET payload_summary = NULL WHERE block_height = 100 AND tx_index = 0")
            cursor.execute("SELECT payload_summary FROM transactions WHERE block_height = 100 AND tx_index = 0")
            self.assertEqual(cursor.fetchone(), (None,))

    def test_transaction_detail_public_summary(self):
        name = f"utsa_api_tx_summary_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        primary = {"type": "gno.bank.MsgSend", "category": "bank", "action": "send", "label": "Send Tokens"}
        summary = {
            "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
            "message_count": 1, "messages_truncated": False, "primary": primary,
            "messages": [{**primary, "sender": "g1sender", "recipient": "g1recipient", "amount": "5000000ugnot"}],
        }
        raw_base64 = "YWJj"
        tx_hash = hashlib.sha256(b"abc").hexdigest().upper()
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (100, 'ZA==', '64', now(), 1)")
            cursor.execute(
                "INSERT INTO transactions (block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, tx_hash_hex, payload_summary) VALUES (100, 0, %s, 4, %s, 3, 'decoded', %s, %s)",
                (raw_base64, b"abc", tx_hash, psycopg.types.json.Jsonb(summary)),
            )
        database = ApiDatabase()
        database.open(ApiConfig(database_url=database_url))
        self.addCleanup(database.close)
        row = database.fetch_transaction_detail(100, 0)
        self.assertEqual(row["payload_summary"], summary)
        self.assertNotIn("decoded_bytes", row)
        public = _transaction_detail_from_row(row).model_dump()
        self.assertEqual(public["raw_base64"], raw_base64)
        self.assertEqual(public["tx_hash"], tx_hash)
        self.assertNotIn("payload_summary", public)
        self.assertEqual(public["summary"]["schema_version"], 1)
        self.assertEqual(public["summary"]["chain_family"], "gno")
        self.assertEqual(public["summary"]["parse_status"], "parsed")
        self.assertEqual(
            {key: public["summary"]["messages"][0][key] for key in ("sender", "recipient", "amount")},
            {"sender": "g1sender", "recipient": "g1recipient", "amount": "5000000ugnot"},
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE transactions SET payload_summary = NULL WHERE block_height = 100 AND tx_index = 0")
        self.assertIsNone(_transaction_detail_from_row(database.fetch_transaction_detail(100, 0)).summary)

        # Exercise the null first-page cursor against PostgreSQL, where an untyped
        # parameter used only by IS NULL would otherwise fail type inference.
        list_rows = database.fetch_transactions(
            limit=20,
            before_height=None,
            before_tx_index=None,
        )
        self.assertEqual([(item["block_height"], item["tx_index"]) for item in list_rows], [(100, 0)])

    def test_exact_transaction_hash_lookup_is_read_only_and_deterministic(self):
        name = f"utsa_api_tx_hash_lookup_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        tx_hash = "AB" * 32
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) "
                "VALUES (%s, %s, %s, now(), %s)",
                [(100, "YQ==", "AA" * 32, 1), (101, "Yg==", "BB" * 32, 1)],
            )
            cursor.executemany(
                "INSERT INTO transactions "
                "(block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, "
                "decoded_byte_length, decode_status, tx_hash_hex) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (100, 0, "YQ==", 4, b"a", 1, "decoded", tx_hash),
                    (101, 0, "YQ==", 4, b"a", 1, "decoded", tx_hash),
                ],
            )
            cursor.execute("SELECT count(*) FROM transactions")
            before_count = cursor.fetchone()[0]

        database = ApiDatabase()
        database.open(ApiConfig(database_url=database_url))
        self.addCleanup(database.close)
        self.assertEqual(database.fetch_transaction_by_hash(tx_hash), {
            "block_height": 101, "tx_index": 0, "tx_hash_hex": tx_hash,
        })
        self.assertIsNone(database.fetch_transaction_by_hash("CD" * 32))
        self.assertEqual(
            [(row["block_height"], row["tx_index"]) for row in database.fetch_transactions(
                limit=20, before_height=None, before_tx_index=None,
            )],
            [(101, 0), (100, 0)],
        )
        self.assertEqual(database.fetch_transaction_detail(100, 0)["tx_hash_hex"], tx_hash)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM transactions")
            self.assertEqual(cursor.fetchone()[0], before_count)

    def prepare_legacy_database(self, name):
        self.create_database(name)
        database_url = self.database_url_for(name)
        schema = subprocess.check_output(
            ["git", "show", f"{BASE_SHA}:database/schema.sql"], cwd=ROOT, text=True
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(schema)
            cursor.execute("""
                INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count)
                VALUES (1, 'AQ==', '01', '2026-01-01T00:00:00Z', 1);
                INSERT INTO transactions
                    (block_height, tx_index, raw_base64, raw_base64_length, decode_status)
                VALUES (1, 0, 'AQ==', 4, 'not_attempted');
                INSERT INTO validators
                    (signing_address, public_key_type, public_key_value, first_seen_height, last_seen_height)
                VALUES ('g1sentinel', '/tm.PubKeyEd25519', 'sentinel-key', 1, 1);
                INSERT INTO validator_set_members (height, signing_address, voting_power)
                VALUES (1, 'g1sentinel', 1);
                INSERT INTO validator_signatures
                    (height, signing_address, vote_status, signed, vote_block_id_is_zero, block_id_matches_commit)
                VALUES (1, 'g1sentinel', 'absent', false, false, false);
                INSERT INTO rpc_endpoints (url, chain_id) VALUES ('https://rpc.example.invalid', 'test-chain');
                INSERT INTO rpc_endpoint_checks (rpc_endpoint_id, chain_id, healthy)
                VALUES (1, 'test-chain', true);
                INSERT INTO indexer_state (state_key, chain_id, last_finalized_height)
                VALUES ('default', 'test-chain', 1);
            """)
        return database_url

    def table_names_and_counts(self, database_url):
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = {row[0] for row in cursor.fetchall()}
            counts = {}
            for table in sorted(tables):
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                counts[table] = cursor.fetchone()[0]
        return tables, counts

    def test_empty_database_initializes_and_second_run_validates(self):
        first = self.run_init()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn(self.password, first.stdout + first.stderr)
        second = self.run_init()
        self.assertEqual(second.returncode, 0, second.stderr)
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            tables = {row[0] for row in cursor.fetchall()}
            self.assertEqual(tables, init_database.EXPECTED_TABLES)
            self.assertTrue({
                "network_distribution_geo_cache",
                "network_distribution_snapshots",
                "network_distribution_snapshot_sources",
            } <= tables)
            cursor.execute("SELECT conname FROM pg_constraint WHERE conname = 'validator_signatures_height_signing_address_fkey'")
            self.assertIsNotNone(cursor.fetchone())
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'rpc_endpoints_one_selected_per_chain_idx'")
            self.assertIsNotNone(cursor.fetchone())

    def test_rpc_persistence_transaction_lifetime(self):
        name = f"utsa_rpc_persistence_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        database = PostgresDatabase(database_url)
        probe = RpcProbeResult(
            "https://rpc.example.test", True, True, "test-chain", 100, 0, False,
        )

        database.select_rpc_endpoint("test-chain", probe, "continuity verified")
        self.assertIsNotNone(database.selected_rpc_endpoint_id)
        endpoint_id = database.selected_rpc_endpoint_id
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_selected FROM rpc_endpoints WHERE id = %s", (endpoint_id,),
            )
            self.assertEqual(cursor.fetchone(), (True,))
            cursor.execute(
                "SELECT count(*) FROM rpc_endpoint_checks "
                "WHERE rpc_endpoint_id = %s AND switch_reason = %s",
                (endpoint_id, "continuity verified"),
            )
            self.assertEqual(cursor.fetchone(), (1,))

        database.record_rpc_runtime_failure("test-chain", probe, "runtime failure")
        self.assertIsNone(database.selected_rpc_endpoint_id)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT healthy, is_selected FROM rpc_endpoints WHERE id = %s",
                (endpoint_id,),
            )
            self.assertEqual(cursor.fetchone(), (False, False))

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

    def test_legacy_schema_migrates_preserves_rows_and_reruns(self):
        database_url = self.prepare_legacy_database(f"utsa_legacy_migration_{os.getpid()}")
        before_tables, before_counts = self.table_names_and_counts(database_url)
        self.assertEqual(before_tables, LEGACY_TABLES)
        self.assertTrue(all(before_counts[table] == 1 for table in LEGACY_TABLES))

        migrated = self.run_migration(database_url)
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertIn("Valopers schema migration applied and validated", migrated.stdout)
        self.assertEqual(migrated.stderr, "")
        self.assertNotIn(self.password, migrated.stdout + migrated.stderr)
        self.assertNotIn(database_url, migrated.stdout + migrated.stderr)

        after_valopers_tables, after_valopers_counts = self.table_names_and_counts(database_url)
        self.assertEqual(after_valopers_tables, LEGACY_TABLES | {"valoper_profiles", "valopers_snapshot_state"})
        for table in LEGACY_TABLES:
            self.assertEqual(after_valopers_counts[table], before_counts[table])

        rerun = self.run_migration(database_url)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn("Valopers schema is already compatible", rerun.stdout)
        self.assertEqual(rerun.stderr, "")

        transaction_migration = self.run_transaction_hash_migration(database_url)
        self.assertEqual(transaction_migration.returncode, 0, transaction_migration.stderr)
        self.assertEqual(transaction_migration.stdout, "Transaction hash migration applied and validated\n")
        self.assertEqual(transaction_migration.stderr, "")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*), count(tx_hash_hex) FROM transactions")
            self.assertEqual(cursor.fetchone(), (before_counts["transactions"], 0))
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='transactions' AND column_name='tx_hash_hex'")
            self.assertEqual(cursor.fetchone(), ("tx_hash_hex",))
            cursor.execute("SELECT conname FROM pg_constraint WHERE conname IN ('transactions_tx_hash_hex_format','transactions_tx_hash_consistent') ORDER BY conname")
            self.assertEqual({row[0] for row in cursor.fetchall()}, {"transactions_tx_hash_hex_format", "transactions_tx_hash_consistent"})
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname='transactions_tx_hash_hex_idx'")
            self.assertEqual(cursor.fetchone(), ("transactions_tx_hash_hex_idx",))

        before_transaction_rerun = self.table_names_and_counts(database_url)
        transaction_rerun = self.run_transaction_hash_migration(database_url)
        self.assertEqual(transaction_rerun.returncode, 0, transaction_rerun.stderr)
        self.assertEqual(transaction_rerun.stdout, "Transaction hash schema is already compatible\n")
        self.assertEqual(transaction_rerun.stderr, "")
        self.assertEqual(self.table_names_and_counts(database_url), before_transaction_rerun)

        before_guidance_tables, before_guidance_counts = self.table_names_and_counts(database_url)
        guidance = self.run_init(database_url)
        self.assertNotEqual(guidance.returncode, 0)
        self.assertIn("python scripts/migrate_network_distribution_schema.py", guidance.stderr)
        self.assertEqual(self.table_names_and_counts(database_url), (before_guidance_tables, before_guidance_counts))

        network_migration = self.run_network_distribution_migration(database_url)
        self.assertEqual(network_migration.returncode, 0, network_migration.stderr)
        network_rerun = self.run_network_distribution_migration(database_url)
        self.assertEqual(network_rerun.returncode, 0, network_rerun.stderr)
        validated = self.run_init(database_url)
        self.assertEqual(validated.returncode, 0, validated.stderr)

        post_network_valopers = self.run_migration(database_url)
        self.assertEqual(post_network_valopers.returncode, 0, post_network_valopers.stderr)
        self.assertIn("Valopers schema is already compatible", post_network_valopers.stdout)
        post_network_transactions = self.run_transaction_hash_migration(database_url)
        self.assertEqual(post_network_transactions.returncode, 0, post_network_transactions.stderr)
        self.assertIn("already compatible", post_network_transactions.stdout)

        outputs = [migrated, rerun, transaction_migration, transaction_rerun, guidance, network_migration,
                   network_rerun, validated, post_network_valopers, post_network_transactions]
        for result in outputs:
            self.assertNotIn(self.password, result.stdout + result.stderr)
            self.assertNotIn(database_url, result.stdout + result.stderr)

        after_tables, after_counts = self.table_names_and_counts(database_url)
        self.assertEqual(after_tables, init_database.EXPECTED_TABLES)
        for table in LEGACY_TABLES:
            self.assertEqual(after_counts[table], before_counts[table])
        self.assertEqual(after_counts["valoper_profiles"], 0)
        self.assertEqual(after_counts["valopers_snapshot_state"], 0)
        for table in ("network_distribution_geo_cache", "network_distribution_snapshots",
                      "network_distribution_snapshot_sources"):
            self.assertEqual(after_counts[table], 0)

    def test_post_ddl_incompatibility_rolls_back_migration(self):
        database_url = self.prepare_legacy_database(f"utsa_migration_rollback_{os.getpid()}")
        before_tables, before_counts = self.table_names_and_counts(database_url)
        migration = (ROOT / "database/migrations/0001_add_valopers_persistence.sql").read_text()
        incompatible = migration.replace("page_count BETWEEN 0 AND 20", "page_count BETWEEN 0 AND 19")
        self.assertNotEqual(incompatible, migration)
        migration_path = Path(self.temp.name) / "incompatible-valopers-migration.sql"
        migration_path.write_text(incompatible)

        result = self.run_migration(database_url, migration_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Valopers schema migration failed\n")
        self.assertNotIn(self.password, result.stdout + result.stderr)
        self.assertNotIn(database_url, result.stdout + result.stderr)

        after_tables, after_counts = self.table_names_and_counts(database_url)
        self.assertEqual(after_tables, before_tables)
        self.assertEqual(after_counts, before_counts)
        self.assertNotIn("valoper_profiles", after_tables)
        self.assertNotIn("valopers_snapshot_state", after_tables)

    def test_legacy_schema_supports_transaction_hash_migration_before_valopers(self):
        database_url = self.prepare_legacy_database(f"utsa_legacy_hash_first_{os.getpid()}")
        before_tables, before_counts = self.table_names_and_counts(database_url)

        transaction = self.run_transaction_hash_migration(database_url)
        self.assertEqual(transaction.returncode, 0, transaction.stderr)
        self.assertEqual(transaction.stdout, "Transaction hash migration applied and validated\n")
        transaction_rerun = self.run_transaction_hash_migration(database_url)
        self.assertEqual(transaction_rerun.returncode, 0, transaction_rerun.stderr)
        self.assertEqual(transaction_rerun.stdout, "Transaction hash schema is already compatible\n")

        valopers = self.run_migration(database_url)
        self.assertEqual(valopers.returncode, 0, valopers.stderr)
        self.assertIn("Valopers schema migration applied and validated", valopers.stdout)
        valopers_rerun = self.run_migration(database_url)
        self.assertEqual(valopers_rerun.returncode, 0, valopers_rerun.stderr)
        self.assertIn("Valopers schema is already compatible", valopers_rerun.stdout)

        guidance = self.run_init(database_url)
        self.assertNotEqual(guidance.returncode, 0)
        self.assertIn("python scripts/migrate_network_distribution_schema.py", guidance.stderr)
        network = self.run_network_distribution_migration(database_url)
        self.assertEqual(network.returncode, 0, network.stderr)
        final_init = self.run_init(database_url)
        self.assertEqual(final_init.returncode, 0, final_init.stderr)
        final_valopers = self.run_migration(database_url)
        final_transactions = self.run_transaction_hash_migration(database_url)
        final_network = self.run_network_distribution_migration(database_url)
        self.assertIn("already compatible", final_valopers.stdout)
        self.assertIn("already compatible", final_transactions.stdout)
        self.assertEqual(final_network.returncode, 0, final_network.stderr)

        outputs = (transaction, transaction_rerun, valopers, valopers_rerun, guidance,
                   network, final_init, final_valopers, final_transactions, final_network)
        for result in outputs:
            self.assertNotIn(self.password, result.stdout + result.stderr)
            self.assertNotIn(database_url, result.stdout + result.stderr)
        tables, counts = self.table_names_and_counts(database_url)
        self.assertEqual(tables, init_database.EXPECTED_TABLES)
        for table in LEGACY_TABLES:
            self.assertEqual(counts[table], before_counts[table])
        for table in ("valoper_profiles", "valopers_snapshot_state",
                      "network_distribution_geo_cache", "network_distribution_snapshots",
                      "network_distribution_snapshot_sources"):
            self.assertEqual(counts[table], 0)

    def test_atomic_valopers_snapshot_lifecycle(self):
        name = f"utsa_valopers_persistence_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        database = PostgresDatabase(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) "
                "VALUES ('default', 'test-chain', 1)"
            )

        def make_profile(marker, moniker="Validator", description="Description"):
            address = "g1" + marker * 38
            return ValoperProfile(moniker, description, address, address,
                                  "gpub1" + marker * 86, "cloud", "/profile")

        initial = ValopersSnapshot(10, 1, (make_profile("2"), make_profile("3", "Second")))
        self.assertEqual(database.replace_valopers_snapshot(initial, "test-chain").action, "applied")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT operator_address, moniker, description, server_type, signing_address, signing_pubkey, source_height, list_position, inserted_at, updated_at FROM valoper_profiles ORDER BY list_position")
            before = cursor.fetchall()
            cursor.execute("SELECT chain_id, source_height, page_count, profile_count, updated_at FROM valopers_snapshot_state")
            state_before = cursor.fetchone()
            self.assertEqual(state_before[:4], ("test-chain", 10, 1, 2))
        expected_profiles = [
            (profile.operator_address, profile.moniker, profile.description, profile.server_type,
             profile.signing_address, profile.signing_pubkey, 10, position)
            for position, profile in enumerate(initial.profiles)
        ]
        self.assertEqual([row[:8] for row in before], expected_profiles)

        self.assertEqual(database.replace_valopers_snapshot(initial, "test-chain").action, "unchanged")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT operator_address, moniker, description, server_type, signing_address, signing_pubkey, source_height, list_position, inserted_at, updated_at FROM valoper_profiles ORDER BY list_position")
            self.assertEqual(cursor.fetchall(), before)
            cursor.execute("SELECT chain_id, source_height, page_count, profile_count, updated_at FROM valopers_snapshot_state")
            self.assertEqual(cursor.fetchone(), state_before)

        newer = ValopersSnapshot(11, 1, (make_profile("4", "Replacement"),))
        self.assertEqual(database.replace_valopers_snapshot(newer, "test-chain").action, "applied")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM valoper_profiles ORDER BY list_position")
            stable_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM valopers_snapshot_state")
            stable_state = cursor.fetchone()
        self.assertEqual(stable_rows[0][0], newer.profiles[0].operator_address)
        self.assertEqual(stable_rows[0][6:8], (11, 0))

        for rejected, error, chain in (
            (initial, StaleValopersSnapshot, "test-chain"),
            (ValopersSnapshot(11, 1, (make_profile("5"),)), ValopersSnapshotConflict, "test-chain"),
            (ValopersSnapshot(12, 0, ()), ValopersChainIdentityError, "other-chain"),
        ):
            with self.assertRaises(error):
                database.replace_valopers_snapshot(rejected, chain)
            with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT * FROM valoper_profiles ORDER BY list_position")
                self.assertEqual(cursor.fetchall(), stable_rows)
                cursor.execute("SELECT * FROM valopers_snapshot_state")
                self.assertEqual(cursor.fetchone(), stable_state)

        # Moniker punctuation is valid; use the database server-type constraint
        # to exercise rollback after the replacement DELETE instead.
        invalid = ValopersSnapshot(12, 1, (ValoperProfile(
            "Valid moniker", "Description", "g1" + "5" * 38, "g1" + "5" * 38,
            "gpub1" + "5" * 86, "invalid-server-type", "/profile"),))
        with self.assertRaises(Exception):
            database.replace_valopers_snapshot(invalid, "test-chain")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM valoper_profiles ORDER BY list_position")
            self.assertEqual(cursor.fetchall(), stable_rows)
            cursor.execute("SELECT * FROM valopers_snapshot_state")
            self.assertEqual(cursor.fetchone(), stable_state)

        empty = ValopersSnapshot(12, 0, ())
        self.assertEqual(database.replace_valopers_snapshot(empty, "test-chain").action, "applied")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM valoper_profiles")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT chain_id, source_height, page_count, profile_count FROM valopers_snapshot_state")
            self.assertEqual(cursor.fetchone(), ("test-chain", 12, 0, 0))

    def test_first_write_checks_indexer_state_chain(self):
        name = f"utsa_valopers_chain_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) "
                "VALUES ('default', 'test-chain', 1)"
            )
        database = PostgresDatabase(database_url)
        with self.assertRaises(ValopersChainIdentityError):
            database.replace_valopers_snapshot(ValopersSnapshot(10, 0, ()), "other-chain")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM valoper_profiles")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM valopers_snapshot_state")
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertEqual(
            database.replace_valopers_snapshot(ValopersSnapshot(10, 0, ()), "test-chain").action,
            "applied",
        )

    def test_concurrent_first_writers_are_serialized(self):
        name = f"utsa_valopers_concurrent_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) "
                "VALUES ('default', 'test-chain', 1)"
            )

        def make_profile(marker):
            address = "g1" + marker * 38
            return ValoperProfile("Writer " + marker, "Complete writer " + marker, address,
                                  address, "gpub1" + marker * 86, "cloud", "/profile")

        low = ValopersSnapshot(20, 1, (make_profile("2"),))
        high = ValopersSnapshot(21, 1, (make_profile("3"), make_profile("4")))
        barrier = threading.Barrier(2, timeout=10)
        outcomes = []
        outcome_lock = threading.Lock()

        def write(item):
            barrier.wait()
            try:
                result = PostgresDatabase(database_url).replace_valopers_snapshot(item, "test-chain")
                outcome = result.action
            except Exception as exc:
                outcome = exc
            with outcome_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=write, args=(item,), daemon=True) for item in (low, high)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive(), "concurrent writer timed out")
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(outcome == "applied" or isinstance(outcome, StaleValopersSnapshot)
                            for outcome in outcomes), outcomes)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT source_height, page_count, profile_count FROM valopers_snapshot_state")
            self.assertEqual(cursor.fetchone(), (21, 1, 2))
            cursor.execute("SELECT operator_address, source_height, list_position FROM valoper_profiles ORDER BY list_position")
            rows = cursor.fetchall()
        self.assertEqual(rows, [
            (high.profiles[0].operator_address, 21, 0),
            (high.profiles[1].operator_address, 21, 1),
        ])


    def test_validator_api_valoper_identity_queries(self):
        name = f"utsa_api_valopers_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        matched, unmatched, historical, orphan = ("g1" + char * 38 for char in "2345")
        operators = ["g1" + char * 38 for char in "6789"]
        pubkeys = ["gpub1" + char * 86 for char in "acde"]
        with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (10, 'Cg==', '0A', now(), 0)")
                cursor.execute("INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) VALUES ('default', 'test-13', 10)")
                cursor.executemany("INSERT INTO validators (signing_address, public_key_type, public_key_value, first_seen_height, last_seen_height) VALUES (%s, '/tm.PubKeyEd25519', %s, 1, 10)", [(matched, 'key1'), (unmatched, 'key2'), (historical, 'key3')])
                cursor.executemany("INSERT INTO validator_set_members (height, signing_address, voting_power, proposer_priority) VALUES (10, %s, %s, 0)", [(matched, 20), (unmatched, 10)])
                cursor.executemany("INSERT INTO valoper_profiles (operator_address, moniker, description, server_type, signing_address, signing_pubkey, source_height, list_position) VALUES (%s, %s, 'Profile', %s, %s, %s, %s, %s)", [
                    (operators[0], 'Active Official', 'cloud', matched, pubkeys[0], 947852, 0),
                    (operators[1], 'Historical Official', 'on-prem', historical, pubkeys[1], 947852, 1),
                    (operators[2], 'Orphan Official', 'data-center', orphan, pubkeys[2], 947852, 2),
                ])
                cursor.execute(ACTIVE_VALIDATORS_SQL, (10, 10))
                active = cursor.fetchall()
                self.assertEqual([row['address'] for row in active], [matched, unmatched])
                self.assertEqual(len({row['address'] for row in active}), 2)
                self.assertEqual(sum(row['voting_power'] for row in active), 30)
                self.assertEqual((active[0]['moniker'], active[0]['operator_address'], active[0]['server_type'], active[0]['valoper_source_height']), ('Active Official', operators[0], 'cloud', 947852))
                self.assertTrue(all(active[1][key] is None for key in ('moniker', 'operator_address', 'server_type', 'valoper_source_height')))
                identities = {}
                for address in (matched, unmatched, historical, orphan, "g1" + "f" * 38):
                    cursor.execute(VALIDATOR_IDENTITY_SQL, (address,))
                    identities[address] = cursor.fetchone()
                self.assertEqual(identities[matched]['moniker'], 'Active Official')
                self.assertEqual(identities[matched]['valoper_source_height'], 947852)
                self.assertTrue(all(identities[unmatched][key] is None for key in ('moniker', 'operator_address', 'description', 'server_type', 'valoper_source_height')))
                self.assertEqual(identities[historical]['moniker'], 'Historical Official')
                self.assertIsNone(identities[orphan])
                self.assertIsNone(identities["g1" + "f" * 38])

        role = f"utsa_api_test_{os.getpid()}"
        role_password = secrets.token_urlsafe(24)
        legacy_api_tables = (
            "blocks", "indexer_state", "validators", "validator_set_members",
            "validator_signatures",
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                psycopg.sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(
                    psycopg.sql.Identifier(role),
                    psycopg.sql.Literal(role_password),
                )
            )
            cursor.execute(
                psycopg.sql.SQL(
                    "ALTER ROLE {} SET default_transaction_read_only = on"
                ).format(psycopg.sql.Identifier(role))
            )
            cursor.execute(
                psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    psycopg.sql.Identifier(name), psycopg.sql.Identifier(role)
                )
            )
            cursor.execute(
                psycopg.sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    psycopg.sql.Identifier(role)
                )
            )
            cursor.execute(
                psycopg.sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
                    psycopg.sql.SQL(", ").join(
                        psycopg.sql.Identifier("public", table) for table in legacy_api_tables
                    ),
                    psycopg.sql.Identifier(role),
                )
            )
            cursor.execute(
                "SELECT has_table_privilege(%s, 'public.valoper_profiles', 'SELECT')",
                (role,),
            )
            self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "SELECT has_table_privilege(%s, 'public.valopers_snapshot_state', 'SELECT')",
                (role,),
            )
            self.assertFalse(cursor.fetchone()[0])

        restricted_url = (
            f"postgresql://{role}:{role_password}@{self.host}:{self.port}/{name}"
        )
        with psycopg.connect(
            restricted_url, row_factory=psycopg.rows.dict_row
        ) as connection, connection.cursor() as cursor:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(ACTIVE_VALIDATORS_SQL, (10, 10))

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                psycopg.sql.SQL(
                    "GRANT SELECT ON TABLE public.valoper_profiles TO {}"
                ).format(psycopg.sql.Identifier(role))
            )
            cursor.execute(
                "SELECT has_table_privilege(%s, 'public.valoper_profiles', privilege) "
                "FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) privilege",
                (role,),
            )
            self.assertEqual([row[0] for row in cursor.fetchall()], [True, False, False, False, False])
            cursor.execute(
                "SELECT has_table_privilege(%s, 'public.valopers_snapshot_state', 'SELECT')",
                (role,),
            )
            self.assertFalse(cursor.fetchone()[0])

        with psycopg.connect(
            restricted_url, row_factory=psycopg.rows.dict_row
        ) as connection, connection.cursor() as cursor:
            cursor.execute(ACTIVE_VALIDATORS_SQL, (10, 10))
            restricted_active = cursor.fetchall()
            self.assertEqual(
                [(row["address"], row["moniker"]) for row in restricted_active],
                [(matched, "Active Official"), (unmatched, None)],
            )
            for address, expected_moniker in (
                (matched, "Active Official"), (unmatched, None)
            ):
                cursor.execute(VALIDATOR_IDENTITY_SQL, (address,))
                self.assertEqual(cursor.fetchone()["moniker"], expected_moniker)


    def run_network_distribution_migration(self, database_url):
        env = dict(os.environ, DATABASE_URL=database_url)
        return subprocess.run(
            [sys.executable, "scripts/migrate_network_distribution_schema.py"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )

    def test_api_network_distribution_latest_snapshot_contract(self):
        name = f"utsa_distribution_api_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        epoch = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)
        insert_sql = """
            INSERT INTO network_distribution_snapshots (
                chain_id, source_kind, scanned_at, rpc_sources_total, rpc_sources_ok,
                visible_node_ids, unique_public_ips, geolocated_node_ids,
                geolocated_public_ips, node_id_ip_conflicts, region_count,
                country_count, provider_count, regions, countries, providers
            ) VALUES (%s, 'tendermint_net_info', %s, 3, 3, 8, 7, 8, 7, 0,
                      1, 1, 1, %s::jsonb, %s::jsonb, %s::jsonb)
            RETURNING id
        """
        regions = '[{"name":"Europe","count":7}]'
        countries = '[{"code":"FI","name":"Finland","count":6}]'
        providers = '[{"asn":24940,"name":"Provider","count":5}]'

        api_database = ApiDatabase()
        api_database.open(ApiConfig(database_url=database_url))
        self.addCleanup(api_database.close)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) "
                "VALUES ('default', 'topaz-1', 0)"
            )
            cursor.execute(insert_sql, ("topaz-1", epoch, regions, countries, providers))
            cursor.execute(insert_sql, ("topaz-1", epoch + timedelta(minutes=1), regions, countries, providers))
        row = api_database.fetch_network_distribution()
        self.assertEqual(row["scanned_at"], epoch + timedelta(minutes=1))
        self.assertEqual(row["chain_id"], "topaz-1")
        self.assertIsInstance(row["regions"], list)
        self.assertIsInstance(row["regions"][0], dict)
        self.assertIsInstance(row["countries"], list)
        self.assertIsInstance(row["providers"], list)
        self.assertEqual(
            set(row),
            {"chain_id", "source_kind", "scanned_at", "rpc_sources_total", "rpc_sources_ok",
             "visible_node_ids", "unique_public_ips", "geolocated_node_ids",
             "geolocated_public_ips", "node_id_ip_conflicts", "region_count",
             "country_count", "provider_count", "regions", "countries", "providers"},
        )

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM network_distribution_snapshots")
            cursor.execute(insert_sql, ("topaz-1", epoch, regions, countries, providers)); first_id = cursor.fetchone()[0]
            cursor.execute(insert_sql, ("topaz-1", epoch, regions, countries, providers)); second_id = cursor.fetchone()[0]
        self.assertGreater(second_id, first_id)
        self.assertEqual(api_database.fetch_network_distribution()["providers"][0]["count"], 5)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE network_distribution_snapshots SET providers = '[{\"asn\":24940,\"name\":\"Newest ID\",\"count\":5}]'::jsonb WHERE id = %s", (second_id,))
        self.assertEqual(api_database.fetch_network_distribution()["providers"][0]["name"], "Newest ID")

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM network_distribution_snapshots")
            cursor.execute(insert_sql, ("topaz-1", epoch, regions, countries, providers))
            cursor.execute(insert_sql, ("other-1", epoch + timedelta(days=1), regions, countries, providers))
        self.assertEqual(api_database.fetch_network_distribution()["chain_id"], "topaz-1")

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM network_distribution_snapshots")
        row = api_database.fetch_network_distribution()
        self.assertEqual(row["chain_id"], "topaz-1")
        self.assertIsNone(row["scanned_at"])
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM indexer_state WHERE state_key = 'default'")
        with self.assertRaises(MissingIndexerStateError):
            api_database.fetch_network_distribution()

        normalized_sql = NETWORK_DISTRIBUTION_SQL.lower()
        for forbidden in ("network_distribution_geo_cache", "network_distribution_snapshot_sources", "rpc_endpoints"):
            self.assertNotIn(forbidden, normalized_sql)

    def test_network_distribution_migration_and_existing_rows(self):
        name = f"utsa_distribution_migration_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        schema = (ROOT / "database/schema.sql").read_text()
        migration = (ROOT / "database/migrations/0003_add_network_distribution.sql").read_text()
        pre_schema = schema.replace(migration, "")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(pre_schema)
            cursor.execute("INSERT INTO blocks (height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (1,'h',%s,now(),1)", ('A'*64,))
            cursor.execute("INSERT INTO transactions (block_height,tx_index,raw_base64,raw_base64_length,decode_status) VALUES (1,0,'x',1,'not_attempted')")
            cursor.execute("INSERT INTO validators (signing_address,public_key_type,public_key_value,first_seen_height,last_seen_height) VALUES ('validator','type','key',1,1)")
            cursor.execute("INSERT INTO rpc_endpoints (url,chain_id) VALUES ('https://rpc.example','chain')")
            cursor.execute("INSERT INTO valoper_profiles (operator_address,moniker,description,server_type,signing_address,signing_pubkey,source_height,list_position) VALUES (%s,'m','d','cloud',%s,%s,1,0)", ('g1'+'2'*38,'g1'+'3'*38,'gpub1'+'2'*86))
        self.assertEqual(self.run_network_distribution_migration(database_url).returncode, 0)
        self.assertEqual(self.run_network_distribution_migration(database_url).returncode, 0)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            for table in ('blocks','transactions','validators','rpc_endpoints','valoper_profiles'):
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_network_distribution_cache_snapshots_retention_and_sources(self):
        name = f"utsa_distribution_storage_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        now = datetime.now(timezone.utc)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO rpc_endpoints (url,chain_id,is_selected,healthy,catching_up,last_checked_at,latest_observed_height) VALUES ('https://selected','chain',true,true,false,now(),10),('https://height','chain',false,true,false,now(),9),('https://stable','chain',false,true,false,now(),9),('https://disabled','chain',false,true,false,now(),100),('https://wrong','wrong',false,true,false,now(),100),('https://unhealthy','chain',false,false,false,now(),100),('https://catching','chain',false,true,true,now(),100),('https://stale','chain',false,true,false,now()-interval '1 day',100) RETURNING id")
            ids=[row[0] for row in cursor.fetchall()]
            cursor.execute("UPDATE rpc_endpoints SET is_enabled=false WHERE url='https://disabled'")
            sources=select_sources(connection,'chain',3,600)
            self.assertEqual([row['id'] for row in sources],ids[:3])
            self.assertEqual(len(select_sources(connection,'chain',1,600)),1)
            endpoint_id=ids[0]
        success=GeoRecord('8.8.8.8',True,'North America','US','United States','Region',1,'Provider',fetched_at=now,expires_at=now+timedelta(hours=1))
        failed=GeoRecord('8.8.8.8',False,fetched_at=now,expires_at=now+timedelta(hours=1),error_code='timeout')
        with psycopg.connect(database_url) as connection:
            save_geo_cache(connection,[success]); save_geo_cache(connection,[failed])
            with connection.cursor() as cursor:
                cursor.execute("SELECT lookup_success,continent_name,country_code,country_name,region_name,asn,provider_name,error_code,fetched_at <= expires_at FROM network_distribution_geo_cache WHERE ip='8.8.8.8'")
                self.assertEqual(cursor.fetchone(), (True,'North America','US','United States','Region',1,'Provider',None,True))
                cursor.execute("""UPDATE network_distribution_geo_cache
                    SET fetched_at=now()-interval '2 hours', expires_at=now()-interval '1 hour'
                    WHERE ip='8.8.8.8'""")
                connection.commit()
                cursor.execute("SELECT fetched_at <= expires_at, expires_at < now() FROM network_distribution_geo_cache WHERE ip='8.8.8.8'")
                self.assertEqual(cursor.fetchone(), (True, True))
            save_geo_cache(connection,[failed])
            with connection.cursor() as cursor:
                cursor.execute("SELECT lookup_success,continent_name,country_code,country_name,region_name,asn,provider_name,error_code,fetched_at <= expires_at FROM network_distribution_geo_cache WHERE ip='8.8.8.8'")
                self.assertEqual(cursor.fetchone(),(False,None,None,None,None,None,None,'timeout',True))

        def result(chain, endpoint, scanned):
            return {'chain_id':chain,'source_kind':'tendermint_net_info','scanned_at':scanned,'rpc_sources_total':1,'rpc_sources_ok':1,'visible_node_ids':0,'unique_public_ips':0,'geolocated_node_ids':0,'geolocated_public_ips':0,'node_id_ip_conflicts':0,'region_count':0,'country_count':0,'provider_count':0,'regions':[],'countries':[],'providers':[],'sources':[{'source_order':0,'rpc_endpoint_id':endpoint,'success':True,'reported_peer_count':0,'accepted_peer_count':0,'duration_ms':1,'error_code':None}]}
        with psycopg.connect(database_url) as connection:
            first=save_snapshot(connection,result('chain',endpoint_id,now),2)
            save_snapshot(connection,result('other',endpoint_id,now),1)
            save_snapshot(connection,result('chain',endpoint_id,now+timedelta(seconds=1)),2)
            save_snapshot(connection,result('chain',endpoint_id,now+timedelta(seconds=2)),2)
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots WHERE chain_id='chain'"); self.assertEqual(cursor.fetchone()[0],2)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots WHERE chain_id='other'"); self.assertEqual(cursor.fetchone()[0],1)
                cursor.execute("DELETE FROM rpc_endpoints WHERE id=%s",(endpoint_id,)); connection.commit()
                cursor.execute("SELECT rpc_endpoint_id FROM network_distribution_snapshot_sources LIMIT 1"); self.assertIsNone(cursor.fetchone()[0])
                cursor.execute("DELETE FROM network_distribution_snapshots WHERE id=(SELECT min(id) FROM network_distribution_snapshots)"); connection.commit()
                cursor.execute("SELECT count(*) FROM network_distribution_snapshot_sources WHERE snapshot_id NOT IN (SELECT id FROM network_distribution_snapshots)"); self.assertEqual(cursor.fetchone()[0],0)
            previous=save_snapshot(connection,result('chain',None,now+timedelta(seconds=3)),2)
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots WHERE id=%s",(previous,))
                self.assertEqual(cursor.fetchone()[0],1)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots")
                snapshots_before_failure = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM network_distribution_snapshot_sources")
                sources_before_failure = cursor.fetchone()[0]
            broken=result('chain',None,now+timedelta(seconds=4)); broken['sources'][0]['error_code']='invalid'
            with self.assertRaises(Exception): save_snapshot(connection,broken,2)
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots WHERE id=%s",(previous,)); self.assertEqual(cursor.fetchone()[0],1)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots"); self.assertEqual(cursor.fetchone()[0],snapshots_before_failure)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshot_sources"); self.assertEqual(cursor.fetchone()[0],sources_before_failure)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshot_sources s LEFT JOIN network_distribution_snapshots n ON n.id=s.snapshot_id WHERE n.id IS NULL"); self.assertEqual(cursor.fetchone()[0],0)
                cursor.execute("SELECT count(*) FROM network_distribution_snapshots WHERE chain_id='chain'"); self.assertLessEqual(cursor.fetchone()[0],2)

    def test_network_distribution_geo_cache_uses_canonical_inet_keys(self):
        name = f"utsa_distribution_cache_keys_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        now = datetime.now(timezone.utc)
        ipv4 = GeoRecord('192.0.2.10', True, 'North America', 'US', 'United States',
                         'Test Region', 64500, 'IPv4 Provider', fetched_at=now,
                         expires_at=now + timedelta(hours=1))
        ipv6 = GeoRecord('2001:db8::1', True, 'Europe', 'DE', 'Germany',
                         'IPv6 Region', 64501, 'IPv6 Provider', fetched_at=now,
                         expires_at=now + timedelta(hours=1))
        with psycopg.connect(database_url) as connection:
            save_geo_cache(connection, [ipv4, ipv6])
            cached = load_geo_cache(connection, {ipv4.ip, ipv6.ip})
        self.assertEqual(set(cached), {'192.0.2.10', '2001:db8::1'})
        self.assertNotIn('192.0.2.10/32', cached)
        self.assertNotIn('2001:db8::1/128', cached)
        self.assertEqual(cached[ipv4.ip], ipv4)
        self.assertEqual(cached[ipv6.ip], ipv6)

    def test_geolocated_snapshot_exists_across_retained_history(self):
        name = f"utsa_distribution_good_history_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def result(chain, scanned_at, geolocated):
            return {
                'chain_id': chain, 'source_kind': 'tendermint_net_info', 'scanned_at': scanned_at,
                'rpc_sources_total': 1, 'rpc_sources_ok': 1, 'visible_node_ids': 1,
                'unique_public_ips': 1, 'geolocated_node_ids': int(geolocated > 0),
                'geolocated_public_ips': geolocated, 'node_id_ip_conflicts': 0,
                'region_count': int(geolocated > 0), 'country_count': int(geolocated > 0),
                'provider_count': int(geolocated > 0), 'regions': [], 'countries': [],
                'providers': [], 'sources': [],
            }

        with psycopg.connect(database_url) as connection:
            self.assertFalse(has_geolocated_snapshot(connection, 'chain'))
            save_snapshot(connection, result('chain', epoch, 0), 10)
            self.assertFalse(has_geolocated_snapshot(connection, 'chain'))
            save_snapshot(connection, result('other', epoch + timedelta(seconds=1), 1), 10)
            self.assertFalse(has_geolocated_snapshot(connection, 'chain'))
            save_snapshot(connection, result('chain', epoch + timedelta(seconds=2), 1), 10)
            save_snapshot(connection, result('chain', epoch + timedelta(seconds=3), 0), 10)
            self.assertTrue(has_geolocated_snapshot(connection, 'chain'))


if __name__ == "__main__":
    unittest.main()
