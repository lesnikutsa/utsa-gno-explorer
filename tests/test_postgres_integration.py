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

from api.database import ACTIVE_VALIDATORS_SQL, NETWORK_SQL, VALIDATOR_IDENTITY_SQL
from indexer.database import PostgresDatabase
from indexer.rpc import RpcProbeResult
from indexer.valopers_parser import ValoperProfile
from indexer.valopers_persistence import (
    StaleValopersSnapshot, ValopersChainIdentityError, ValopersSnapshotConflict,
)
from indexer.valopers_snapshot import ValopersSnapshot

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

            rows = [(height, epoch + timedelta(seconds=height * 3)) for height in range(1, 102)]
            rows[0] = (1, epoch - timedelta(days=30))
            row = sample(rows)
            self.assertEqual(row["average_block_time_sample_size"], 100)
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
            cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            self.assertEqual(cursor.fetchone()[0], 10)
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

        validated = self.run_init(database_url)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        rerun = self.run_migration(database_url)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn("Valopers schema is already compatible", rerun.stdout)
        self.assertEqual(rerun.stderr, "")

        after_tables, after_counts = self.table_names_and_counts(database_url)
        self.assertEqual(after_tables, LEGACY_TABLES | {"valoper_profiles", "valopers_snapshot_state"})
        self.assertEqual(len(after_tables), 10)
        for table in LEGACY_TABLES:
            self.assertEqual(after_counts[table], before_counts[table])
        self.assertEqual(after_counts["valoper_profiles"], 0)
        self.assertEqual(after_counts["valopers_snapshot_state"], 0)

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


if __name__ == "__main__":
    unittest.main()
