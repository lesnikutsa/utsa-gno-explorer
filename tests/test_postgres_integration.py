import base64
import copy
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api import app as app_module
from api.app import _transaction_detail_from_row
from api.config import ApiConfig
from api.database import (
    ACTIVE_VALIDATORS_SQL,
    NETWORK_DISTRIBUTION_SQL,
    NETWORK_SQL,
    REALM_CATALOG_SUMMARY_SQL,
    REALM_CALLS_PAGE_SQL,
    REALM_DETAIL_ITEM_SQL,
    REALM_DETAIL_SOURCE_SQL,
    REALM_NAMESPACE_TOP_SQL,
    REALM_APPLICATION_SOURCE_SQL,
    REALM_APPLICATION_TOP_SQL,
    VALIDATOR_IDENTITY_SQL,
    ApiDatabase,
    MissingIndexerStateError,
)
from indexer.database import (PostgresDatabase, RealmActivityCoverageError,
    _upsert_transactions, advance_realm_activity_coverage)
from indexer import database as indexer_database
from governance.gno import (GovernanceDiscovery, GovernanceListDiscovery,
    GovernanceProposalDetail, GovernanceProposalSummary, GovernanceSource, GovernanceVote)
from indexer.governance_persistence import (
    GovernancePersistenceError, GovernanceSnapshotConflict, StaleGovernanceSnapshot,
)
from indexer.parsers import ParsedHeight, parse_execution_results, parse_tx
from indexer.transaction_summary import (MAX_SUMMARY_BYTES, SCHEMA_VERSION,
    normalize_summary, summary_size_bytes)
from indexer.realm_catalog import extract_observations
from indexer.realm_metadata_persistence import (
    JsonCapability, MetadataFile, MetadataRefreshState, MetadataSnapshot,
    RenderCapability, StaleMetadataSnapshot, StorageCapability,
    persist_metadata_refresh_state_cursor, publish_metadata_snapshot,
    publish_metadata_snapshot_cursor,
)
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
from scripts.migrate_governance_schema import migrate as migrate_governance_schema
from scripts.rebuild_realm_activity import rebuild_cursor
from scripts.rebuild_realm_call_index import rebuild_cursor as rebuild_realm_call_index_cursor
from scripts.refresh_realm_catalog import RefreshStatus, persist_refresh

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

    def assert_governance_migration_required_then_apply(self, database_url):
        """Validate the explicit pre-governance to final-schema operator contract."""
        before_guidance = self.table_names_and_counts(database_url)
        guidance = self.run_init(database_url)
        self.assertEqual(guidance.returncode, 1)
        self.assertIn("python scripts/migrate_governance_schema.py", guidance.stderr)
        self.assertNotIn(database_url, guidance.stdout + guidance.stderr)
        self.assertNotIn(self.password, guidance.stdout + guidance.stderr)
        self.assertEqual(self.table_names_and_counts(database_url), before_guidance)
        self.assertEqual(migrate_governance_schema(database_url), "applied")
        self.assertEqual(migrate_governance_schema(database_url), "already-compatible")
        validated = self.run_init(database_url)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertNotIn(database_url, validated.stdout + validated.stderr)
        self.assertNotIn(self.password, validated.stdout + validated.stderr)
        return guidance, validated

    def assert_empty_governance_tables(self, database_url):
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            for table in ("governance_proposals", "governance_votes", "governance_sync_state"):
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.assertEqual(cursor.fetchone()[0], 0)

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

    def create_writer_owned_database(self, name):
        """Create the documented production ownership model in a disposable database."""
        from psycopg import sql

        self.ensure_application_roles()
        with self.connect("postgres") as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE utsa_gno_indexer LOGIN PASSWORD {}").format(
                        sql.Literal(self.password)
                    )
                )
                cursor.execute(f'CREATE DATABASE "{name}" OWNER utsa_gno_indexer')
        with self.connect(name) as connection, connection.cursor() as cursor:
            cursor.execute("ALTER SCHEMA public OWNER TO utsa_gno_indexer")
        return (
            f"postgresql://utsa_gno_indexer:{self.password}@"
            f"{self.host}:{self.port}/{name}"
        )

    @staticmethod
    def build_historical_schema(expectations):
        """Remove every canonical DDL section later than an exact known stage."""
        schema = (ROOT / "database/schema.sql").read_text()
        sections = (
            ("realm_metadata", "BEGIN;\n\nCREATE TABLE realm_metadata", None),
            ("realm_call_index", "BEGIN;\n\nCREATE TABLE realm_call_index", None),
            ("transaction_participants", "CREATE TABLE transaction_participants", "-- Block detail pages"),
            ("network_distribution_geo_cache", "CREATE TABLE network_distribution_geo_cache", "CREATE TABLE governance_proposals"),
            ("governance_proposals", "CREATE TABLE governance_proposals", "CREATE TABLE valoper_profiles"),
            ("realm_catalog", "BEGIN;\n\nCREATE TABLE realm_catalog", None),
            ("transaction_execution_results", "BEGIN;\n\nCREATE TABLE transaction_execution_results", None),
        )
        for table, start_marker, end_marker in sections:
            if table in expectations["tables"]:
                continue
            if schema.count(start_marker) != 1:
                raise AssertionError(f"historical schema marker must occur once: {start_marker}")
            start = schema.index(start_marker)
            if end_marker is None:
                schema = schema[:start]
                continue
            if schema.count(end_marker) != 1:
                raise AssertionError(f"historical schema marker must occur once: {end_marker}")
            end = schema.index(end_marker, start)
            schema = schema[:start] + schema[end:]
        return schema

    def ensure_application_roles(self):
        """Create the non-login application roles before conditional schema grants."""
        with self.connect("postgres") as connection, connection.cursor() as cursor:
            cursor.execute("""DO $roles$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_api') THEN
                CREATE ROLE utsa_gno_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
              END IF;
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'utsa_gno_indexer') THEN
                CREATE ROLE utsa_gno_indexer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
              END IF;
            END $roles$""")

    def create_exact_stage_database(
        self, name, expectations, *, create_roles_before_schema=False
    ):
        self.create_database(name)
        if create_roles_before_schema:
            self.ensure_application_roles()
        database_url = self.database_url_for(name)
        schema = self.build_historical_schema(expectations)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(schema)
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor), expectations,
            )
        return database_url

    def create_pre_participant_database(self, name):
        return self.create_exact_stage_database(
            name, init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
        )

    def create_pre_execution_result_database(self, name):
        return self.create_exact_stage_database(
            name, init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS,
        )

    def test_execution_result_upgrade_success_and_rerun_are_idempotent(self):
        database_url = self.create_pre_execution_result_database(
            f"utsa_execution_result_success_{os.getpid()}"
        )
        init_database.initialize_or_validate(database_url)
        init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.transaction_execution_results')")
            self.assertEqual(cursor.fetchone()[0], "transaction_execution_results")
            cursor.execute("SELECT count(*) FROM transaction_execution_results")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_historical_fixture_table_sets_are_exact_and_ordered(self):
        stages = (
            ("pre_network", init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS),
            ("pre_governance", init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS),
            ("pre_participants", init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS),
            ("pre_execution", init_database.PRE_TRANSACTION_EXECUTION_RESULT_EXPECTATIONS),
            ("final", init_database.FINAL_SCHEMA_EXPECTATIONS),
        )
        observed = {}
        for suffix, expectations in stages:
            url = self.create_exact_stage_database(
                f"utsa_exact_{suffix}_{os.getpid()}", expectations,
            )
            observed[suffix] = self.table_names_and_counts(url)[0]
            self.assertEqual(observed[suffix], expectations["tables"])
        late = {"transaction_participants", "transaction_execution_results"}
        for suffix in ("pre_network", "pre_governance", "pre_participants"):
            self.assertTrue(observed[suffix].isdisjoint(late))
        self.assertIn("transaction_participants", observed["pre_execution"])
        self.assertNotIn("transaction_execution_results", observed["pre_execution"])
        self.assertTrue(late <= observed["final"])

        impossible = copy.deepcopy(init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS)
        impossible["tables"] = impossible["tables"] | {"transaction_participants"}
        with self.assertRaises(init_database.SchemaCompatibilityError):
            init_database.validate_schema_snapshot(
                {**impossible, "columns": impossible["columns"]},
                init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
            )

    def test_execution_result_upgrade_rolls_back_after_privilege_failure(self):
        database_url = self.create_pre_execution_result_database(
            f"utsa_execution_result_rollback_{os.getpid()}"
        )
        with patch.object(
            init_database, "validate_participant_privileges",
            side_effect=init_database.SchemaCompatibilityError("forced privilege failure"),
        ):
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.transaction_execution_results')")
            self.assertIsNone(cursor.fetchone()[0])

    def test_participant_upgrade_rolls_back_after_final_schema_failure(self):
        database_url = self.create_pre_participant_database(f"utsa_participant_schema_rollback_{os.getpid()}")
        original = init_database.validate_schema_snapshot
        calls = 0
        def fail_final(snapshot, expectations=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise init_database.SchemaCompatibilityError("forced final failure")
            return original(snapshot, expectations)
        with patch.object(init_database, "validate_schema_snapshot", side_effect=fail_final):
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.transaction_participants')")
            self.assertIsNone(cursor.fetchone()[0])

    def test_participant_upgrade_rolls_back_after_privilege_failure(self):
        database_url = self.create_pre_participant_database(f"utsa_participant_grant_rollback_{os.getpid()}")
        with patch.object(
            init_database, "validate_participant_privileges",
            side_effect=init_database.SchemaCompatibilityError("forced privilege failure"),
        ):
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.transaction_participants')")
            self.assertIsNone(cursor.fetchone()[0])

    def test_participant_upgrade_success_and_rerun_are_idempotent(self):
        database_url = self.create_pre_participant_database(f"utsa_participant_success_{os.getpid()}")
        init_database.initialize_or_validate(database_url)
        init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.transaction_participants')")
            self.assertEqual(cursor.fetchone()[0], "transaction_participants")
            cursor.execute("SELECT count(*) FROM transaction_participants")
            self.assertEqual(cursor.fetchone()[0], 0)

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

    def test_block_detail_with_transaction_execution_result(self):
        from fastapi.testclient import TestClient

        name = f"utsa_api_block_execution_result_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        tx_hash = "AB" * 32
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO blocks "
                "(height, block_hash_base64, block_hash_hex, time_utc, tx_count) "
                "VALUES (334761, 'ZA==', %s, '2026-07-31T12:00:00Z', 1)",
                ("CD" * 32,),
            )
            cursor.execute(
                "INSERT INTO transactions "
                "(block_height, tx_index, tx_hash_hex, raw_base64, raw_base64_length, "
                "decoded_bytes, decoded_byte_length, decode_status) "
                "VALUES (334761, 0, %s, 'YWJj', 4, %s, 3, 'decoded')",
                (tx_hash, b"abc"),
            )
            cursor.execute(
                "INSERT INTO transaction_execution_results "
                "(block_height, tx_index, execution_status, gas_wanted, gas_used) "
                "VALUES (334761, 0, 'success', 5000000, 934971)"
            )

        api_database = ApiDatabase()
        config = ApiConfig(database_url=database_url)
        with (
            patch.object(app_module, "database", api_database),
            patch.object(app_module, "load_config", return_value=config),
            TestClient(app_module.app) as client,
        ):
            detail = api_database.fetch_block_detail(334761)
            self.assertIsNotNone(detail)
            self.assertEqual(len(detail["transactions"]), 1)
            self.assertEqual(
                {key: detail["transactions"][0][key] for key in (
                    "execution_status", "gas_wanted", "gas_used",
                )},
                {
                    "execution_status": "success",
                    "gas_wanted": "5000000",
                    "gas_used": "934971",
                },
            )

            block_response = client.get("/api/blocks/334761")
            self.assertEqual(block_response.status_code, 200, block_response.text)
            self.assertEqual(
                block_response.json()["transactions"][0]["execution_status"],
                "success",
            )

            transaction_response = client.get("/api/blocks/334761/transactions/0")
            self.assertEqual(transaction_response.status_code, 200, transaction_response.text)
            self.assertEqual(transaction_response.json()["gas_used"], "934971")

    def test_execution_result_with_nested_nuls_is_persisted(self):
        name = f"utsa_execution_result_nul_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        raw_result = {
            "ResponseBase": {
                "Error": None,
                "Data": None,
                "Events": [{"counterparty\x00key": {"chain_id": "chain\x00id"}}],
                "Log": "log\x00text",
                "Info": "",
            },
            "GasWanted": "5000000",
            "GasUsed": "934971",
        }
        execution_results = parse_execution_results(
            1,
            {"result": {"height": "1", "results": {"deliver_tx": [raw_result]}}},
            1,
        )
        transaction = parse_tx(0, "YWJj")
        parsed = ParsedHeight(
            height=1,
            block={
                "hash_base64": "ZA==",
                "hash_hex": "64",
                "time": "2026-07-31T12:00:00Z",
                "proposer_address": None,
                "tx_count": 1,
            },
            transactions=[transaction],
            execution_results=execution_results,
            validators=[],
            signatures=[],
            raw_block={"result": {"block": "test"}},
        )

        PostgresDatabase(database_url).write_height(parsed, "test-chain", 1)

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT events, raw_result FROM transaction_execution_results "
                "WHERE block_height = 1 AND tx_index = 0"
            )
            events, stored_raw_result = cursor.fetchone()
        self.assertEqual(events[0]["counterparty\\u0000key"]["chain_id"], "chain\\u0000id")
        self.assertEqual(stored_raw_result["ResponseBase"]["Log"], "log\\u0000text")
        self.assertNotIn("\x00", json.dumps([events, stored_raw_result]))

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
        latency_migration = (
            ROOT / "database/migrations/0005_add_rpc_endpoint_latency.sql"
        ).read_text()
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(schema)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'rpc_endpoints'
                      AND column_name = 'latency_ms'
                ), EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'rpc_endpoints'::regclass
                      AND conname = 'rpc_endpoints_latency_ms_check'
                )
            """)
            self.assertEqual(cursor.fetchone(), (False, False))
            cursor.execute(latency_migration)
            cursor.execute("""
                SELECT data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'rpc_endpoints'
                  AND column_name = 'latency_ms'
            """)
            self.assertEqual(cursor.fetchone(), ("integer", "YES"))
            cursor.execute("""
                SELECT count(*) FROM pg_constraint
                WHERE conrelid = 'rpc_endpoints'::regclass
                  AND conname = 'rpc_endpoints_latency_ms_check'
            """)
            self.assertEqual(cursor.fetchone(), (1,))
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.BASE_LEGACY_EXPECTATIONS,
            )
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
            cursor.execute(latency_migration)
            cursor.execute("SELECT count(*) FROM rpc_endpoints")
            self.assertEqual(cursor.fetchone(), (1,))
            normalized = init_database.fetch_schema_snapshot(cursor)
            init_database.validate_schema_snapshot(
                normalized, init_database.BASE_LEGACY_EXPECTATIONS,
            )
            self.assertNotIn("tx_hash_hex", normalized["columns"]["transactions"])
            self.assertTrue(normalized["tables"].isdisjoint({
                "valoper_profiles", "valopers_snapshot_state",
                "network_distribution_geo_cache", "network_distribution_snapshots",
                "network_distribution_snapshot_sources", "governance_proposals",
                "governance_votes", "governance_sync_state",
                "transaction_participants", "transaction_execution_results",
            }))
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
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
            )
        governance_guidance, validated = self.assert_governance_migration_required_then_apply(database_url)

        post_network_valopers = self.run_migration(database_url)
        self.assertEqual(post_network_valopers.returncode, 0, post_network_valopers.stderr)
        self.assertIn("Valopers schema is already compatible", post_network_valopers.stdout)
        post_network_transactions = self.run_transaction_hash_migration(database_url)
        self.assertEqual(post_network_transactions.returncode, 0, post_network_transactions.stderr)
        self.assertIn("already compatible", post_network_transactions.stdout)
        post_governance_network = self.run_network_distribution_migration(database_url)
        self.assertEqual(post_governance_network.returncode, 0, post_governance_network.stderr)

        outputs = [migrated, rerun, transaction_migration, transaction_rerun, guidance, network_migration,
                   network_rerun, governance_guidance, validated, post_network_valopers,
                   post_network_transactions, post_governance_network]
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
        self.assert_empty_governance_tables(database_url)

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
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
            )
        governance_guidance, final_init = self.assert_governance_migration_required_then_apply(database_url)
        final_valopers = self.run_migration(database_url)
        final_transactions = self.run_transaction_hash_migration(database_url)
        final_network = self.run_network_distribution_migration(database_url)
        self.assertIn("already compatible", final_valopers.stdout)
        self.assertIn("already compatible", final_transactions.stdout)
        self.assertEqual(final_network.returncode, 0, final_network.stderr)

        outputs = (transaction, transaction_rerun, valopers, valopers_rerun, guidance,
                   network, governance_guidance, final_init, final_valopers,
                   final_transactions, final_network)
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
        self.assert_empty_governance_tables(database_url)

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
                cursor.executemany("INSERT INTO blocks (height, block_hash_base64, block_hash_hex, time_utc, tx_count) VALUES (%s, %s, %s, now(), 0)", [(height, f'hash-{height}', f'{height:02X}') for height in range(6, 11)])
                cursor.execute("INSERT INTO indexer_state (state_key, chain_id, last_finalized_height) VALUES ('default', 'test-13', 10)")
                cursor.executemany("INSERT INTO validators (signing_address, public_key_type, public_key_value, first_seen_height, last_seen_height) VALUES (%s, '/tm.PubKeyEd25519', %s, 1, 10)", [(matched, 'key1'), (unmatched, 'key2'), (historical, 'key3')])
                cursor.executemany("INSERT INTO validator_set_members (height, signing_address, voting_power, proposer_priority) VALUES (%s, %s, %s, 0)", [
                    *((height, matched, 20) for height in range(6, 11)),
                    *((height, unmatched, 10) for height in range(9, 11)),
                    *((height, historical, 5) for height in range(6, 10)),
                ])
                cursor.executemany("INSERT INTO validator_signatures (height, signing_address, signed, vote_status, vote_block_id_is_zero, block_id_matches_commit) VALUES (%s, %s, false, %s, %s, false)", [
                    (7, matched, 'nil', True),
                    (8, matched, 'absent', False),
                    (9, matched, 'invalid', False),
                ])
                cursor.executemany("INSERT INTO validator_signatures (height, signing_address, signed, vote_status, vote_block_id_hash_base64, vote_block_id_hash_hex, vote_block_id_parts_total, vote_block_id_parts_hash_base64, vote_block_id_parts_hash_hex, block_id_matches_commit, signature_base64) VALUES (%s, %s, true, 'commit', 'AQ==', '01', 1, 'AQ==', '01', true, 'signature')", [
                    (6, matched),
                    (9, unmatched),
                ])
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
                self.assertEqual(active[0]['active_blocks_1000'], 5)
                self.assertEqual(active[0]['signed_blocks_1000'], 1)
                self.assertEqual(active[0]['nil_blocks_1000'], 1)
                self.assertEqual(active[0]['absent_blocks_1000'], 1)
                self.assertEqual(active[0]['invalid_blocks_1000'], 1)
                self.assertEqual(active[0]['unknown_blocks_1000'], 1)
                self.assertEqual(active[1]['active_blocks_1000'], 2)
                self.assertEqual(active[1]['signed_blocks_1000'], 1)
                self.assertEqual(active[1]['unknown_blocks_1000'], 1)
                self.assertNotIn(historical, [row['address'] for row in active])
                expected = [
                    (5, 1, 1, 1, 1, 1),
                    (2, 1, 0, 0, 0, 1),
                ]
                for row, counters in zip(active, expected):
                    actual = tuple(row[f'{name}_blocks_1000'] for name in ('active', 'signed', 'nil', 'absent', 'invalid', 'unknown'))
                    self.assertEqual(actual, counters)
                    self.assertEqual(actual[0], sum(actual[1:]))
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
        database_url = self.create_exact_stage_database(
            name, init_database.PRE_NETWORK_DISTRIBUTION_EXPECTATIONS,
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO blocks (height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (1,'h',%s,now(),1)", ('A'*64,))
            cursor.execute("INSERT INTO transactions (block_height,tx_index,raw_base64,raw_base64_length,decode_status) VALUES (1,0,'x',1,'not_attempted')")
            cursor.execute("INSERT INTO validators (signing_address,public_key_type,public_key_value,first_seen_height,last_seen_height) VALUES ('validator','type','key',1,1)")
            cursor.execute("INSERT INTO rpc_endpoints (url,chain_id) VALUES ('https://rpc.example','chain')")
            cursor.execute("INSERT INTO valoper_profiles (operator_address,moniker,description,server_type,signing_address,signing_pubkey,source_height,list_position) VALUES (%s,'m','d','cloud',%s,%s,1,0)", ('g1'+'2'*38,'g1'+'3'*38,'gpub1'+'2'*86))
        self.assertEqual(self.run_network_distribution_migration(database_url).returncode, 0)
        self.assertEqual(self.run_network_distribution_migration(database_url).returncode, 0)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO network_distribution_geo_cache(ip,lookup_success,lookup_provider,fetched_at,expires_at,error_code) VALUES ('192.0.2.1',false,'integration',now(),now()+interval '1 hour','not_found')")
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
            )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            for table in ('blocks','transactions','validators','rpc_endpoints','valoper_profiles'):
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM network_distribution_geo_cache")
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assert_governance_migration_required_then_apply(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            for table in ('blocks','transactions','validators','rpc_endpoints','valoper_profiles',
                          'network_distribution_geo_cache'):
                cursor.execute(f"SELECT count(*) FROM {table}")
                self.assertEqual(cursor.fetchone()[0], 1)
        self.assert_empty_governance_tables(database_url)

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


    def test_governance_persistence_migration_and_constraints(self):
        name = f"utsa_governance_{os.getpid()}"
        database_url = self.create_exact_stage_database(
            name, init_database.PRE_GOVERNANCE_SCHEMA_EXPECTATIONS,
        )
        failing_migration = Path(self.temp.name) / "failing-governance-migration.sql"
        failing_migration.write_text(
            (ROOT / "database/migrations/0004_add_governance_persistence.sql").read_text()
            + "\nSELECT missing_governance_migration_function();\n"
        )
        with self.assertRaises(Exception):
            migrate_governance_schema(database_url, failing_migration)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.governance_proposals'),to_regclass('public.governance_votes'),to_regclass('public.governance_sync_state')")
            self.assertEqual(cursor.fetchone(), (None, None, None))
        invalid_catalog_migration = Path(self.temp.name) / "invalid-catalog-governance-migration.sql"
        invalid_catalog_migration.write_text(
            (ROOT / "database/migrations/0004_add_governance_persistence.sql").read_text()
            + "\nCREATE TABLE unexpected_governance_test_table(value integer);\n"
        )
        with self.assertRaises(Exception):
            migrate_governance_schema(database_url, invalid_catalog_migration)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.governance_proposals'),to_regclass('public.unexpected_governance_test_table')")
            self.assertEqual(cursor.fetchone(), (None, None))
        self.assertEqual(migrate_governance_schema(database_url), "applied")
        self.assertEqual(migrate_governance_schema(database_url), "already-compatible")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.PRE_TRANSACTION_PARTICIPANT_EXPECTATIONS,
            )

        def make_snapshot(height=100, count=21, status="ACTIVE", empty_votes=False,
                          parsed_empty=False, yes_percent=33.33333):
            proposals = []
            raw = {}
            for proposal_id in range(count - 1, -1, -1):
                votes = () if empty_votes else (GovernanceVote(f"Voter {proposal_id}", None, "YES", "CORE", str(proposal_id + 1)),)
                vote_status = "empty" if empty_votes else "parsed"
                if parsed_empty:
                    votes = ()
                proposals.append(GovernanceProposalDetail(
                    proposal_id, f"Proposal {proposal_id}", None, None, status, ("CORE",),
                    f"Description {proposal_id}", None, None, None, yes_percent, 25.0, 25.0,
                    "parsed", vote_status, votes, (),
                ))
                raw[f"proposal/{proposal_id}"] = f"raw detail {proposal_id}\n"
                raw[f"proposal/{proposal_id}/votes"] = f"raw votes {proposal_id}\n"
            return GovernanceDiscovery(
                GovernanceSource("topaz-1", "redacted", height, "gno.land/r/gov/dao"),
                True, 5 if count else 1, tuple(proposals), (), raw,
            )

        database = PostgresDatabase(database_url)
        first = database.persist_governance_snapshot(make_snapshot(), "topaz-1")
        self.assertEqual((first.action, first.proposal_count, first.vote_count), ("applied", 21, 21))
        self.assertEqual(database.persist_governance_snapshot(make_snapshot(), "topaz-1").action, "unchanged")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO indexer_state(state_key,chain_id,last_finalized_height) "
                "VALUES ('default','topaz-1',0)"
            )
            cursor.execute("SELECT yes_percent,first_observed_height,last_observed_height,first_observed_at,last_observed_at FROM governance_proposals WHERE proposal_id=0")
            percentage, first_height, last_height, first_at, last_at = cursor.fetchone()
            self.assertEqual(percentage, Decimal("33.3333"))
            self.assertEqual((first_height, last_height), (100, 100))
            cursor.execute("INSERT INTO blocks(height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (1,'AA==','AA',now(),0)")
            cursor.execute("DELETE FROM blocks WHERE height=1")
            cursor.execute("SELECT (SELECT count(*) FROM governance_proposals),(SELECT count(*) FROM governance_votes),(SELECT count(*) FROM governance_sync_state)")
            self.assertEqual(cursor.fetchone(), (21, 21, 1))
            connection.commit()

        api_database = ApiDatabase()
        api_database.open(ApiConfig(database_url=database_url))
        try:
            first_page = api_database.fetch_governance_proposals(
                realm_path="gno.land/r/gov/dao", limit=10, before_proposal_id=None,
            )
            self.assertEqual([row["proposal_id"] for row in first_page["items"]], list(range(20, 9, -1)))
            self.assertEqual(
                (first_page["source"]["proposal_count"], first_page["source"]["first_proposal_id"],
                 first_page["source"]["latest_proposal_id"], first_page["source"]["active_count"]),
                (21, 0, 20, 21),
            )
            second_page = api_database.fetch_governance_proposals(
                realm_path="gno.land/r/gov/dao", limit=20, before_proposal_id=10,
            )
            self.assertEqual([row["proposal_id"] for row in second_page["items"]], list(range(9, -1, -1)))
            self.assertEqual(first_page["items"][0]["voter_count"], 1)
            for proposal_id in (0, 20):
                detail = api_database.fetch_governance_proposal_detail(
                    realm_path="gno.land/r/gov/dao", proposal_id=proposal_id,
                )
                self.assertEqual(detail["proposal"]["proposal_id"], proposal_id)
                self.assertEqual(detail["votes"][0]["voting_power"], str(proposal_id + 1))
                self.assertNotIn("voter_key", detail["votes"][0])
                self.assertNotIn("raw_detail_render", detail["proposal"])
            self.assertIsNone(api_database.fetch_governance_proposals(
                realm_path="gno.land/r/gov/other", limit=20, before_proposal_id=None,
            ))

            original_source_fetch = api_database._fetch_governance_source
            writer_committed = False
            def fetch_source_then_commit_writer(cursor, realm_path):
                nonlocal writer_committed
                row = original_source_fetch(cursor, realm_path)
                if not writer_committed:
                    with psycopg.connect(database_url) as writer, writer.cursor() as writer_cursor:
                        writer_cursor.execute(
                            "UPDATE governance_proposals SET title='Concurrent title' "
                            "WHERE chain_id='topaz-1' AND realm_path=%s AND proposal_id=20",
                            (realm_path,),
                        )
                    writer_committed = True
                return row
            api_database._fetch_governance_source = fetch_source_then_commit_writer
            consistent_page = api_database.fetch_governance_proposals(
                realm_path="gno.land/r/gov/dao", limit=1, before_proposal_id=None,
            )
            self.assertEqual(consistent_page["items"][0]["title"], "Proposal 20")
            api_database._fetch_governance_source = original_source_fetch
            next_request = api_database.fetch_governance_proposals(
                realm_path="gno.land/r/gov/dao", limit=1, before_proposal_id=None,
            )
            self.assertEqual(next_request["items"][0]["title"], "Concurrent title")
            with psycopg.connect(database_url) as writer, writer.cursor() as writer_cursor:
                writer_cursor.execute(
                    "UPDATE governance_proposals SET title='Proposal 20' "
                    "WHERE chain_id='topaz-1' AND realm_path='gno.land/r/gov/dao' AND proposal_id=20"
                )
        finally:
            api_database.close()
        with self.assertRaises(StaleGovernanceSnapshot):
            database.persist_governance_snapshot(make_snapshot(height=99), "topaz-1")
        with self.assertRaises(GovernanceSnapshotConflict):
            database.persist_governance_snapshot(make_snapshot(height=101, count=20), "topaz-1")
        with self.assertRaises(GovernancePersistenceError):
            database.persist_governance_snapshot(make_snapshot(height=101, parsed_empty=True), "topaz-1")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT source_height,(SELECT count(*) FROM governance_votes) FROM governance_sync_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone(), (100, 21))
        accepted = database.persist_governance_snapshot(make_snapshot(height=101, status="ACCEPTED"), "topaz-1")
        self.assertEqual(accepted.action, "applied")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT first_observed_height,last_observed_height,first_observed_at,last_observed_at FROM governance_proposals WHERE proposal_id=0")
            new_first_height, new_last_height, new_first_at, new_last_at = cursor.fetchone()
            self.assertEqual((new_first_height, new_last_height), (100, 101))
            self.assertEqual(new_first_at, first_at)
            self.assertGreaterEqual(new_last_at, last_at)
        with self.assertRaises(GovernanceSnapshotConflict):
            database.persist_governance_snapshot(make_snapshot(height=102, status="ACTIVE"), "topaz-1")
        with self.assertRaises(GovernanceSnapshotConflict):
            database.persist_governance_snapshot(make_snapshot(height=102, status="REJECTED"), "topaz-1")
        emptied = database.persist_governance_snapshot(make_snapshot(height=102, status="ACCEPTED", empty_votes=True), "topaz-1")
        self.assertEqual(emptied.vote_count, 0)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT raw_detail_render,raw_votes_render FROM governance_proposals WHERE proposal_id=0")
            self.assertEqual(cursor.fetchone(), ("raw detail 0\n", "raw votes 0\n"))
            cursor.execute("SELECT count(*) FROM governance_votes")
            self.assertEqual(cursor.fetchone()[0], 0)
            for first_id, latest_id in ((None, 20), (0, None)):
                with self.assertRaises(Exception):
                    cursor.execute("INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES ('bad','bad',1,1,21,%s,%s)", (first_id, latest_id))
                connection.rollback()
            with self.assertRaises(Exception):
                cursor.execute("INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES ('bad','bad',1,1,0,0,NULL)")
            connection.rollback()
            cursor.execute("INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES ('empty','empty',1,1,0,NULL,NULL)")
            connection.rollback()

    def test_governance_incremental_real_transaction(self):
        name = f"utsa_governance_incremental_{os.getpid()}"
        self.create_database(name)
        database_url = self.database_url_for(name)
        self.assertEqual(self.run_init(database_url).returncode, 0)
        realm = "gno.land/r/gov/dao"

        def item(proposal_id, status, votes, suffix=""):
            return GovernanceProposalDetail(
                proposal_id, f"Proposal {proposal_id}", None, None, status, ("CORE",),
                f"Description {suffix}", None, None, None, 50.0, 25.0, 25.0,
                "parsed", "parsed" if votes else "empty", tuple(votes), (),
            )

        source100 = GovernanceSource("topaz-1", "redacted", 100, realm)
        active_vote = GovernanceVote("Alice", None, "YES", "CORE", "10")
        frozen_vote = GovernanceVote("Bob", None, "YES", "CORE", "20")
        initial_items = (item(1, "ACTIVE", (active_vote,)), item(0, "ACCEPTED", (frozen_vote,)))
        raw = {"proposal/1": "active detail", "proposal/1/votes": "active votes",
               "proposal/0": "frozen detail", "proposal/0/votes": "frozen votes"}
        database = PostgresDatabase(database_url)
        self.assertEqual(database.persist_governance_snapshot(
            GovernanceDiscovery(source100, True, 1, initial_items, (), raw), "topaz-1").action, "applied")

        source101 = GovernanceSource("topaz-1", "redacted", 101, realm)
        summaries = (GovernanceProposalSummary(2, "Proposal 2", None, None, "ACCEPTED", ("CORE",)),
                     GovernanceProposalSummary(1, "Proposal 1", None, None, "ACTIVE", ("CORE",)),
                     GovernanceProposalSummary(0, "Proposal 0", None, None, "ACCEPTED", ("CORE",)))
        listed = GovernanceListDiscovery(source101, True, 1, summaries)
        changed_vote = GovernanceVote("Carol", None, "NO", "CORE", "30")
        targeted_items = (item(1, "ACTIVE", (changed_vote,), "changed"),
                          item(2, "ACCEPTED", (), "offline terminal"))
        targeted = []
        for proposal in targeted_items:
            proposal_raw = {f"proposal/{proposal.proposal_id}": f"detail {proposal.proposal_id}",
                            f"proposal/{proposal.proposal_id}/votes": f"votes {proposal.proposal_id}"}
            targeted.append(GovernanceDiscovery(source101, True, 0, (proposal,), (), proposal_raw))
        result = database.persist_governance_incremental(listed, targeted, "topaz-1")
        self.assertEqual((result.action, result.inserted_proposals, result.updated_proposals),
                         ("applied", 1, 1))
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT source_height,proposal_count FROM governance_sync_state WHERE chain_id='topaz-1' AND realm_path=%s", (realm,))
            self.assertEqual(cursor.fetchone(), (101, 3))
            cursor.execute("SELECT proposal_id,first_observed_height,last_observed_height FROM governance_proposals ORDER BY proposal_id")
            self.assertEqual(cursor.fetchall(), [(0, 100, 100), (1, 100, 101), (2, 101, 101)])
            cursor.execute("SELECT proposal_id,voter_display FROM governance_votes ORDER BY proposal_id")
            self.assertEqual(cursor.fetchall(), [(0, "Bob"), (1, "Carol")])

        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT proposal_id,status,last_observed_height,last_observed_at FROM governance_proposals ORDER BY proposal_id")
            proposals_before_retry = cursor.fetchall()
            cursor.execute("SELECT proposal_id,voter_key,option,voting_power,last_observed_height,last_observed_at FROM governance_votes ORDER BY proposal_id,voter_key")
            votes_before_retry = cursor.fetchall()
            cursor.execute("SELECT source_height,last_success_at,updated_at FROM governance_sync_state WHERE chain_id='topaz-1' AND realm_path=%s", (realm,))
            sync_before_retry = cursor.fetchone()
        self.assertEqual(database.persist_governance_incremental(listed, targeted, "topaz-1").action, "unchanged")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT proposal_id,status,last_observed_height,last_observed_at FROM governance_proposals ORDER BY proposal_id")
            self.assertEqual(cursor.fetchall(), proposals_before_retry)
            cursor.execute("SELECT proposal_id,voter_key,option,voting_power,last_observed_height,last_observed_at FROM governance_votes ORDER BY proposal_id,voter_key")
            self.assertEqual(cursor.fetchall(), votes_before_retry)
            cursor.execute("SELECT source_height,last_success_at,updated_at FROM governance_sync_state WHERE chain_id='topaz-1' AND realm_path=%s", (realm,))
            self.assertEqual(cursor.fetchone(), sync_before_retry)
        stale = GovernanceListDiscovery(GovernanceSource("topaz-1", "redacted", 99, realm), True, 1, summaries)
        with self.assertRaises(StaleGovernanceSnapshot):
            database.persist_governance_incremental(stale, [], "topaz-1")


    def test_realm_catalog_0007_late_roles_remain_fail_closed(self):
        database_url = self.create_exact_stage_database(
            f"utsa_realm_late_roles_{os.getpid()}",
            init_database.PRE_REALM_CATALOG_EXPECTATIONS,
        )
        self.ensure_application_roles()
        with self.assertRaises(init_database.SchemaCompatibilityError):
            init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.realm_catalog'),to_regclass('public.realm_catalog_state')")
            self.assertEqual(cursor.fetchone(), (None, None))

    def test_realm_catalog_refresh_ordering_and_atomic_rollback(self):
        name = f"utsa_realm_catalog_refresh_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        old_path = "gno.land/r/catalog/old"
        new_path = "gno.land/p/catalog/new"

        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            initial = persist_refresh(cursor, "topaz-1", 100, None, [(old_path, "realm")])
            self.assertEqual(initial.status, RefreshStatus.APPLIED)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE realm_catalog_state SET activity_from_height=10,
              activity_through_height=90,refreshed_at=TIMESTAMPTZ '2000-01-01 00:00:00+00'
              WHERE chain_id='topaz-1'""")
            cursor.execute("""UPDATE realm_catalog SET seen_via_transactions=true,
              call_count=3,successful_call_count=2,failed_call_count=1,
              last_counted_height=90 WHERE chain_id='topaz-1' AND path=%s""", (old_path,))
            newer = persist_refresh(cursor, "topaz-1", 101, None, [(new_path, "package")])
            self.assertEqual(newer.status, RefreshStatus.APPLIED)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT observed_height,rpc_path_count,activity_from_height,
              activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'""")
            self.assertEqual(cursor.fetchone(), (101, 1, 10, 90))
            cursor.execute("""SELECT path,rpc_visible,call_count,successful_call_count,
              failed_call_count FROM realm_catalog WHERE chain_id='topaz-1' ORDER BY path""")
            self.assertEqual(cursor.fetchall(), [
                (new_path, True, 0, 0, 0),
                (old_path, False, 3, 2, 1),
            ])
            cursor.execute("SELECT refreshed_at,updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            state_timestamps = cursor.fetchone()

        for height, expected in ((101, RefreshStatus.UNCHANGED), (100, RefreshStatus.STALE_IGNORED)):
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                result = persist_refresh(cursor, "topaz-1", height, None, [(old_path, "realm")])
                self.assertEqual(result.status, expected)
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT observed_height,refreshed_at,updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
                self.assertEqual(cursor.fetchone(), (101, *state_timestamps))
                cursor.execute("SELECT path,rpc_visible FROM realm_catalog WHERE chain_id='topaz-1' ORDER BY path")
                self.assertEqual(cursor.fetchall(), [(new_path, True), (old_path, False)])

        class FailingCursor:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def execute(self, sql, params=()):
                if "INSERT INTO realm_catalog_state" in sql:
                    raise RuntimeError("forced_state_failure")
                return self.wrapped.execute(sql, params)

            def fetchone(self):
                return self.wrapped.fetchone()

        with self.assertRaisesRegex(RuntimeError, "forced_state_failure"):
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                persist_refresh(FailingCursor(cursor), "topaz-1", 102, None, [(old_path, "realm")])
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT observed_height,activity_from_height,activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone(), (101, 10, 90))
            cursor.execute("SELECT path,rpc_visible,call_count FROM realm_catalog WHERE chain_id='topaz-1' ORDER BY path")
            self.assertEqual(cursor.fetchall(), [(new_path, True, 0), (old_path, False, 3)])

    def test_realm_catalog_0008_upgrade_and_exact_grants(self):
        name = f"utsa_realm_upgrade_{os.getpid()}"
        database_url = self.create_exact_stage_database(
            name, init_database.PRE_REALM_CATALOG_EXPECTATIONS,
            create_roles_before_schema=True,
        )
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO blocks(height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (1,'a',repeat('A',64),now(),0)")
        init_database.initialize_or_validate(database_url)
        init_database.initialize_or_validate(database_url)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(init_database.fetch_schema_snapshot(cursor))
            cursor.execute("SELECT count(*) FROM blocks WHERE height=1")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT to_regclass('public.realm_calls'),to_regclass('public.realm_activity')")
            self.assertEqual(cursor.fetchone(), (None, None))
            cursor.execute("""SELECT grantee,table_name,privilege_type FROM information_schema.role_table_grants
              WHERE grantee IN ('utsa_gno_api','utsa_gno_indexer')
                AND table_name IN ('transaction_participants','transaction_execution_results','realm_catalog','realm_catalog_state')
              ORDER BY grantee,table_name,privilege_type""")
            self.assertEqual(cursor.fetchall(), [
              ('utsa_gno_api','realm_catalog','SELECT'),('utsa_gno_api','realm_catalog_state','SELECT'),
              ('utsa_gno_api','transaction_execution_results','SELECT'),('utsa_gno_api','transaction_participants','SELECT'),
              ('utsa_gno_indexer','realm_catalog','INSERT'),('utsa_gno_indexer','realm_catalog','SELECT'),('utsa_gno_indexer','realm_catalog','UPDATE'),
              ('utsa_gno_indexer','realm_catalog_state','INSERT'),('utsa_gno_indexer','realm_catalog_state','SELECT'),('utsa_gno_indexer','realm_catalog_state','UPDATE'),
              ('utsa_gno_indexer','transaction_execution_results','INSERT'),('utsa_gno_indexer','transaction_execution_results','SELECT'),('utsa_gno_indexer','transaction_execution_results','UPDATE'),
              ('utsa_gno_indexer','transaction_participants','DELETE'),('utsa_gno_indexer','transaction_participants','INSERT'),('utsa_gno_indexer','transaction_participants','SELECT')])
            for table in ('transaction_participants', 'transaction_execution_results',
                          'realm_catalog', 'realm_catalog_state'):
                cursor.execute(
                    "SELECT has_table_privilege('utsa_gno_api', %s, 'INSERT,UPDATE,DELETE')",
                    (table,),
                )
                self.assertFalse(cursor.fetchone()[0], table)
            cursor.execute("""SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolbypassrls
              FROM pg_roles WHERE rolname IN ('utsa_gno_api','utsa_gno_indexer') ORDER BY rolname""")
            self.assertEqual(cursor.fetchall(), [
              ('utsa_gno_api',False,True,False,False,False,False),
              ('utsa_gno_indexer',False,True,False,False,False,False)])

    def test_realm_detail_and_realm_calls_api_queries(self):
        name = f"utsa_realm_detail_calls_{os.getpid()}"
        self.create_database(name)
        self.ensure_application_roles()
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO utsa_gno_api")
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('utsa_gno_api','utsa_gno_indexer') ORDER BY rolname")
            self.assertEqual(cursor.fetchall(), [('utsa_gno_api',), ('utsa_gno_indexer',)])
            for table in ('realm_call_index', 'realm_call_index_state'):
                cursor.execute("SELECT has_table_privilege('utsa_gno_api', %s, 'SELECT')", (table,))
                self.assertTrue(cursor.fetchone()[0], table)
                cursor.execute("SELECT has_table_privilege('utsa_gno_api', %s, 'INSERT,UPDATE,DELETE')", (table,))
                self.assertFalse(cursor.fetchone()[0], table)
        api_db = ApiDatabase()
        api_db.open(ApiConfig(database_url=url, chain_id="topaz-1"))
        try:
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("INSERT INTO indexer_state(state_key, chain_id, last_finalized_height) VALUES ('default','topaz-1',3)")
                cursor.execute("INSERT INTO realm_catalog_state(chain_id,observed_height,rpc_path_count,activity_from_height,activity_through_height,refreshed_at) VALUES ('topaz-1',3,2,1,3,now())")
                cursor.execute("INSERT INTO realm_call_index_state(chain_id,from_height,through_height) VALUES ('topaz-1',2,3)")
                cursor.execute("""INSERT INTO realm_catalog(chain_id,path,path_kind,seen_via_rpc,seen_via_transactions,rpc_visible,last_rpc_seen_at,
                    deployer_address,deploy_height,deploy_tx_index,first_seen_height,last_activity_height,last_activity_tx_index,last_activity_at,
                    call_count,successful_call_count,failed_call_count,unknown_result_call_count,last_counted_height)
                    VALUES ('topaz-1','gno.land/r/gnoswap/app','realm',true,true,true,now(),NULL,1,0,1,3,1,now(),3,2,1,0,3),
                           ('topaz-1','gno.land/p/demo/pkg','package',true,false,true,now(),NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,0,0,0,NULL),
                           ('other-chain','gno.land/r/gnoswap/app','realm',true,true,true,now(),NULL,1,0,1,1,0,now(),1,1,0,0,1)""")
                for height in range(1, 5):
                    cursor.execute("INSERT INTO blocks(height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (%s,%s,%s,now(),1)", (height, f"h{height}", f"{height:064X}"))
                    cursor.execute("""INSERT INTO transactions(block_height,tx_index,raw_base64,raw_base64_length,decoded_bytes,decoded_byte_length,decode_status,tx_hash_hex)
                        VALUES (%s,0,'eA==',4,decode('78','hex'),1,'decoded',%s)""", (height, f"{height + 200:064X}"))
                cursor.execute("INSERT INTO transaction_execution_results(block_height,tx_index,execution_status,gas_wanted,gas_used) VALUES (3,0,'success',100,50)")
                cursor.executemany("""INSERT INTO realm_call_index(chain_id,block_height,tx_index,message_index,path,caller_address,function_name,args_count,send_amount)
                    VALUES ('topaz-1',%s,0,%s,'gno.land/r/gnoswap/app',NULL,'Render',0,'1ugnot')""", [(4,0),(3,1),(3,0),(2,0),(1,0)])
            detail = api_db.fetch_realm_detail(chain_id="topaz-1", path="gno.land/r/gnoswap/app")
            self.assertEqual(detail["item"]["path"], "gno.land/r/gnoswap/app")
            package = api_db.fetch_realm_detail(chain_id="topaz-1", path="gno.land/p/demo/pkg")
            self.assertEqual(package["item"]["path_kind"], "package")
            first = api_db.fetch_realm_calls(chain_id="topaz-1", path="gno.land/r/gnoswap/app", limit=2, before_height=None, before_tx_index=None, before_message_index=None)
            self.assertEqual([(row["block_height"], row["tx_index"], row["message_index"]) for row in first["items"][:2]], [(3,0,1),(3,0,0)])
            second = api_db.fetch_realm_calls(chain_id="topaz-1", path="gno.land/r/gnoswap/app", limit=2, before_height=3, before_tx_index=0, before_message_index=0)
            self.assertEqual([(row["block_height"], row["tx_index"], row["message_index"]) for row in second["items"]], [(2,0,0)])
            positions = [(row["block_height"], row["tx_index"], row["message_index"]) for row in first["items"] + second["items"]]
            self.assertNotIn((1,0,0), positions)
            self.assertNotIn((4,0,0), positions)
            checkpoint_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE blocks SET time_utc=%s WHERE height=2", (checkpoint_time - timedelta(hours=25),))
                cursor.execute("UPDATE blocks SET time_utc=%s WHERE height=3", (checkpoint_time,))
            ranking = api_db.fetch_top_realm_applications(chain_id="topaz-1", limit=3, window_hours=24)
            self.assertTrue(ranking["coverage_available"])
            self.assertEqual(ranking["source"]["window_end_at"], checkpoint_time)
            self.assertEqual(ranking["source"]["window_start_at"], checkpoint_time - timedelta(hours=24))
            self.assertEqual(ranking["items"][0]["namespace_key"], "gnoswap")
            self.assertEqual((ranking["items"][0]["direct_call_count"], ranking["items"][0]["called_realm_count"]), (2, 1))
            self.assertEqual((ranking["items"][0]["successful_call_count"], ranking["items"][0]["unknown_result_call_count"]), (2, 0))
            self.assertIsNone(api_db.fetch_realm_detail(chain_id="topaz-1", path="gno.land/r/isolated" )["item"])
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SET ROLE utsa_gno_api")
                cursor.execute(REALM_DETAIL_ITEM_SQL, ("topaz-1", "gno.land/r/gnoswap/app"))
                self.assertEqual(cursor.fetchone()[1], "gno.land/r/gnoswap/app")
                cursor.execute(REALM_DETAIL_SOURCE_SQL, ("topaz-1",))
                self.assertEqual(cursor.fetchone()[1], 3)
                cursor.execute(REALM_CALLS_PAGE_SQL, ("topaz-1", "gno.land/r/gnoswap/app", 2, 3, None, None, None, None, 3))
                self.assertEqual([(row[0], row[1], row[2]) for row in cursor.fetchall()], [(3,0,1),(3,0,0),(2,0,0)])
                cursor.execute(REALM_APPLICATION_SOURCE_SQL, ("topaz-1",))
                application_source = cursor.fetchone()
                self.assertEqual((application_source[0], application_source[1]), ("topaz-1", 3))
                cursor.execute(REALM_APPLICATION_TOP_SQL, (
                    "topaz-1", "topaz-1", 2, 3,
                    checkpoint_time - timedelta(hours=24), checkpoint_time, 3))
                application_rows = cursor.fetchall()
                self.assertEqual((application_rows[0][0], application_rows[0][1]), ("gnoswap", 2))
                self.assertEqual(tuple(application_rows[0][2:6]), (1, 2, 0, 0))
                self.assertEqual(tuple(application_rows[0][8:11]), (3, 0, 1))
                for table in ("blocks", "transactions", "indexer_state", "transaction_execution_results",
                              "realm_catalog", "realm_catalog_state", "realm_call_index", "realm_call_index_state"):
                    cursor.execute(f"SELECT count(*) FROM {table}")
                    self.assertGreaterEqual(cursor.fetchone()[0], 0, table)
                for sql in ("INSERT INTO realm_call_index_state(chain_id,from_height,through_height) VALUES ('x',1,1)",
                            "UPDATE realm_call_index_state SET through_height=through_height",
                            "DELETE FROM realm_call_index WHERE chain_id='topaz-1'",
                            "TRUNCATE realm_call_index",
                            "INSERT INTO blocks(height,block_hash_base64,block_hash_hex,time_utc,tx_count) VALUES (99,'x',repeat('F',64),now(),0)",
                            "UPDATE transactions SET tx_index=tx_index WHERE block_height=1",
                            "DELETE FROM indexer_state WHERE state_key='default'",
                            "TRUNCATE transactions"):
                    with self.subTest(sql=sql), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        cursor.execute(sql)
                    connection.rollback()
                    cursor.execute("SET ROLE utsa_gno_api")
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM realm_call_index_state WHERE chain_id='topaz-1'")
            missing = api_db.fetch_realm_calls(chain_id="topaz-1", path="gno.land/r/gnoswap/app", limit=2, before_height=None, before_tx_index=None, before_message_index=None)
            self.assertIsNone(missing["source"].get("call_index_from_height"))
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SET ROLE utsa_gno_api")
                cursor.execute("SELECT count(*) FROM realm_call_index")
                self.assertEqual(cursor.fetchone()[0], 5)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute("INSERT INTO realm_call_index_state(chain_id,from_height,through_height) VALUES ('x',1,1)")
                connection.rollback()
                cursor.execute("SET ROLE utsa_gno_api")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute("DELETE FROM realm_call_index WHERE chain_id='topaz-1'")
                connection.rollback()
                cursor.execute("SET ROLE utsa_gno_api")
                cursor.execute("SET LOCAL enable_seqscan = off")
                cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + REALM_CALLS_PAGE_SQL,
                    ("topaz-1", "gno.land/r/gnoswap/app", 2, 3, None, None, None, None, 3))
                plan = json.dumps(cursor.fetchone()[0])
                self.assertIn("realm_call_index_path_position_idx", plan)
                self.assertNotIn('"Relation Name": "realm_call_index", "Alias": "call", "Node Type": "Seq Scan"', plan)
        finally:
            api_db.close()

    def test_realm_call_index_migration_order_cursor_cascade_plan_and_lock(self):
        name = f"utsa_realm_call_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        summary = json.dumps({"parse_status": "parsed", "messages": []})
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            for height in range(1, 31):
                cursor.execute(
                    "INSERT INTO blocks(height, block_hash_base64, block_hash_hex, "
                    "time_utc, tx_count) VALUES (%s, %s, %s, now(), 1)",
                    (height, f"h{height}", f"{height:064X}")
                )
                cursor.execute(
                    "INSERT INTO transactions(block_height, tx_index, raw_base64, "
                    "raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, "
                    "tx_hash_hex, payload_summary) VALUES (%s, 0, 'eA==', 4, "
                    "decode('78','hex'), 1, 'decoded', %s, %s::jsonb)",
                    (height, f"{height + 100:064X}", summary),
                )
                for message_index in range(2):
                    cursor.execute(
                        "INSERT INTO realm_call_index(chain_id, block_height, tx_index, "
                        "message_index, path, function_name) VALUES "
                        "('topaz-1', %s, 0, %s, 'gno.land/r/demo', 'Render')",
                        (height, message_index),
                    )
            cursor.execute(
                "SELECT block_height, tx_index, message_index FROM realm_call_index "
                "WHERE chain_id='topaz-1' AND path='gno.land/r/demo' AND "
                "(block_height, tx_index, message_index) < (30, 0, 1) "
                "ORDER BY block_height DESC, tx_index DESC, message_index DESC LIMIT 3"
            )
            self.assertEqual(cursor.fetchall(), [(30, 0, 0), (29, 0, 1), (29, 0, 0)])
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT block_height, tx_index, "
                "message_index FROM realm_call_index WHERE chain_id='topaz-1' "
                "AND path='gno.land/r/demo' AND (block_height, tx_index, message_index) "
                "< (30, 0, 1) ORDER BY block_height DESC, tx_index DESC, "
                "message_index DESC LIMIT 10"
            )
            plan = json.dumps(cursor.fetchone()[0])
            self.assertIn("realm_call_index_path_position_idx", plan)
            self.assertNotIn('"Node Type": "Seq Scan"', plan)
            cursor.execute("DELETE FROM blocks WHERE height=1")
            cursor.execute("SELECT count(*) FROM realm_call_index WHERE block_height=1")
            self.assertEqual(cursor.fetchone()[0], 0)

        first = psycopg.connect(url)
        second = psycopg.connect(url)
        try:
            with first.cursor() as cursor:
                indexer_database.lock_realm_call_index(cursor)
            with second.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)",
                    (indexer_database.REALM_CALL_INDEX_LOCK_ID,),
                )
                self.assertFalse(cursor.fetchone()[0])
            first.rollback()
            second.rollback()
            with second.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)",
                    (indexer_database.REALM_CALL_INDEX_LOCK_ID,),
                )
                self.assertTrue(cursor.fetchone()[0])
        finally:
            first.close()
            second.close()

    def test_realm_call_index_0009_upgrade_constraints_grants_and_rerun(self):
        name = f"utsa_realm_call_upgrade_{os.getpid()}"
        url = self.create_exact_stage_database(
            name, init_database.PRE_REALM_CALL_INDEX_EXPECTATIONS,
            create_roles_before_schema=True,
        )
        init_database.initialize_or_validate(url)
        init_database.initialize_or_validate(url)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(init_database.fetch_schema_snapshot(cursor))
            cursor.execute(
                "SELECT grantee, table_name, privilege_type FROM "
                "information_schema.role_table_grants WHERE grantee IN "
                "('utsa_gno_api','utsa_gno_indexer') AND table_name IN "
                "('realm_call_index','realm_call_index_state') ORDER BY 1,2,3"
            )
            self.assertEqual(cursor.fetchall(), [
                ('utsa_gno_api', 'realm_call_index', 'SELECT'),
                ('utsa_gno_api', 'realm_call_index_state', 'SELECT'),
                ('utsa_gno_indexer', 'realm_call_index', 'DELETE'),
                ('utsa_gno_indexer', 'realm_call_index', 'INSERT'),
                ('utsa_gno_indexer', 'realm_call_index', 'SELECT'),
                ('utsa_gno_indexer', 'realm_call_index', 'UPDATE'),
                ('utsa_gno_indexer', 'realm_call_index_state', 'DELETE'),
                ('utsa_gno_indexer', 'realm_call_index_state', 'INSERT'),
                ('utsa_gno_indexer', 'realm_call_index_state', 'SELECT'),
                ('utsa_gno_indexer', 'realm_call_index_state', 'UPDATE'),
            ])
            cursor.execute(
                "INSERT INTO blocks(height, block_hash_base64, block_hash_hex, "
                "time_utc, tx_count) VALUES (1, 'realm-call-upgrade', repeat('A',64), now(), 1)"
            )
            cursor.execute(
                "INSERT INTO transactions(block_height, tx_index, raw_base64, "
                "raw_base64_length, decoded_bytes, decoded_byte_length, decode_status, "
                "tx_hash_hex) VALUES (1,0,'eA==',4,decode('78','hex'),1,'decoded',repeat('B',64))"
            )
            cursor.execute(
                "INSERT INTO realm_call_index(chain_id,block_height,tx_index,message_index,path) "
                "VALUES ('topaz-1',1,0,0,'gno.land/r/valid')"
            )
            for column, value in (
                ("path", "gno.land/p/package"),
                ("path", "gno.land/r/bad path"),
                ("caller_address", "g1bad"),
                ("function_name", ""),
                ("args_count", -1),
                ("send_amount", ""),
            ):
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with connection.transaction():
                        cursor.execute(
                            f"UPDATE realm_call_index SET {column}=%s "
                            "WHERE chain_id='topaz-1' AND block_height=1 "
                            "AND tx_index=0 AND message_index=0",
                            (value,),
                        )

    def test_realm_activity_coverage_helper_and_zero_transaction_block(self):
        name = f"utsa_realm_coverage_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)

        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO realm_catalog_state(
              chain_id,observed_height,rpc_path_count,refreshed_at,
              activity_from_height,activity_through_height)
              VALUES ('topaz-1',20,0,now(),10,20)""")
            cursor.execute("""UPDATE realm_catalog_state
              SET updated_at=TIMESTAMPTZ '2000-01-01 00:00:00+00'
              WHERE chain_id='topaz-1'""")
            cursor.executemany("""INSERT INTO blocks(
              height,block_hash_base64,block_hash_hex,time_utc,tx_count)
              VALUES (%s,%s,%s,now(),0)""",
              [(height, base64.b64encode(f"coverage-block-{height}".encode()).decode(),
                f"{height:064X}") for height in range(21, 26)])
            cursor.execute("SELECT updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            initial_updated = cursor.fetchone()[0]
            result = advance_realm_activity_coverage(cursor, "topaz-1", 21)
            self.assertEqual((result.previous_through_height, result.new_through_height,
                              result.advanced), (20, 21, True))
            cursor.execute("SELECT activity_through_height,updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            through, advanced_updated = cursor.fetchone()
            self.assertEqual(through, 21)
            self.assertGreater(advanced_updated, initial_updated)
            replay = advance_realm_activity_coverage(cursor, "topaz-1", 21)
            cursor.execute("SELECT updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], advanced_updated)
            self.assertFalse(replay.advanced)
            with self.assertRaises(RealmActivityCoverageError):
                with connection.transaction():
                    advance_realm_activity_coverage(cursor, "topaz-1", 25)
            cursor.execute("SELECT activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], 21)
        # Exercise the live write path with a real zero-transaction parsed block.
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM blocks WHERE height >= 21")
            cursor.execute("UPDATE realm_catalog_state SET activity_through_height=20 WHERE chain_id='topaz-1'")
            cursor.execute("INSERT INTO indexer_state(state_key,chain_id,last_finalized_height) VALUES ('default','topaz-1',20)")
        parsed = ParsedHeight(21, {
            "hash_base64": "ZA==", "hash_hex": "A" * 64,
            "time": datetime.now(timezone.utc), "proposer_address": None, "tx_count": 0,
        }, [], [], [], [], {"result": {}})
        PostgresDatabase(url).write_height(parsed, "topaz-1", 21)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], 21)

        def parsed_height(height, summary=None, execution_results=None):
            transactions = []
            if summary is not None:
                transaction = parse_tx(0, base64.b64encode(f"tx-{height}".encode()).decode())
                transaction["payload_summary"] = summary
                transactions.append(transaction)
            return ParsedHeight(height, {
                "hash_base64": base64.b64encode(f"live-block-{height}".encode()).decode(),
                "hash_hex": f"{height + 1000:064X}", "time": datetime.now(timezone.utc),
                "proposer_address": None, "tx_count": len(transactions),
            }, transactions, execution_results or [], [], [], {"result": {}})

        def valid_summary(messages, *, primary_type, category, action, label):
            return {"schema_version": SCHEMA_VERSION, "chain_family": "gno",
                "parse_status": "parsed", "message_count": len(messages),
                "messages_truncated": False,
                "primary": {"type": primary_type, "category": category,
                            "action": action, "label": label},
                "messages": messages}

        ordinary_message = {"type": "bank.MsgSend", "sender": "g1" + "q" * 38}
        ordinary_summary = valid_summary([ordinary_message], primary_type="bank.MsgSend",
            category="transfer", action="send", label="Send")
        ordinary = parsed_height(22, ordinary_summary)
        PostgresDatabase(url).write_height(ordinary, "topaz-1", 22)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM blocks WHERE height=22")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM transactions WHERE block_height=22")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT coalesce(sum(call_count),0) FROM realm_catalog WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], 22)
            cursor.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key='default'")
            self.assertEqual(cursor.fetchone()[0], 22)

        call_message = {
            "type": "gno.vm.MsgCall", "package_path": "gno.land/r/coverage/app",
            "package_path_complete": True, "sender": "g1" + "q" * 38,
        }
        call_summary = valid_summary([call_message], primary_type="gno.vm.MsgCall",
            category="realm", action="call", label="Realm Call")
        normalized_call = normalize_summary(call_summary)
        self.assertEqual(normalized_call["parse_status"], "parsed")
        observations = extract_observations(normalized_call)
        self.assertEqual(len(observations), 1)
        self.assertEqual((observations[0].path, observations[0].observation_type),
                         ("gno.land/r/coverage/app", "call"))
        success_result = {"tx_index": 0, "execution_status": "success", "gas_wanted": 1,
            "gas_used": 1, "error_text": None, "log_text": None, "info_text": None,
            "data_base64": None, "events": [], "raw_result": {}}
        realm_call = parsed_height(23, call_summary, [success_result])
        PostgresDatabase(url).write_height(realm_call, "topaz-1", 23)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT call_count,successful_call_count,failed_call_count
              FROM realm_catalog WHERE chain_id='topaz-1' AND path='gno.land/r/coverage/app'""")
            self.assertEqual(cursor.fetchone(), (1, 1, 0))
            cursor.execute("SELECT activity_through_height,updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual((coverage_height := cursor.fetchone())[0], 23)
            replay_updated_at = coverage_height[1]
            cursor.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key='default'")
            self.assertEqual(cursor.fetchone()[0], 23)

        PostgresDatabase(url).write_height(realm_call, "topaz-1", 23)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT call_count,successful_call_count FROM realm_catalog
              WHERE chain_id='topaz-1' AND path='gno.land/r/coverage/app'""")
            self.assertEqual(cursor.fetchone(), (1, 1))
            cursor.execute("SELECT activity_through_height,updated_at FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone(), (23, replay_updated_at))
            cursor.execute("SELECT count(*) FROM blocks WHERE height=23")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM transactions WHERE block_height=23")
            self.assertEqual(cursor.fetchone()[0], 1)

        rollback_block = parsed_height(24, call_summary, [success_result])
        with patch.object(indexer_database, "_upsert_validators_and_members",
                          side_effect=RuntimeError("forced post-coverage failure")):
            with self.assertRaises(RuntimeError):
                PostgresDatabase(url).write_height(rollback_block, "topaz-1", 24)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM blocks WHERE height=24")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM transactions WHERE block_height=24")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT call_count FROM realm_catalog WHERE chain_id='topaz-1' AND path='gno.land/r/coverage/app'")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT activity_through_height FROM realm_catalog_state WHERE chain_id='topaz-1'")
            self.assertEqual(cursor.fetchone()[0], 23)
            cursor.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key='default'")
            self.assertEqual(cursor.fetchone()[0], 23)

    def test_realm_activity_coverage_lag_requires_full_rebuild(self):
        name = f"utsa_realm_coverage_rebuild_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        summary = json.dumps({"schema_version": 1, "parse_status": "parsed", "messages": [{
            "type": "gno.vm.MsgCall", "package_path": "gno.land/r/coverage/rebuild",
            "package_path_complete": True, "sender": "g1" + "q" * 38,
        }]})
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO indexer_state(state_key,chain_id,last_finalized_height) VALUES ('default','topaz-1',25)")
            cursor.execute("""INSERT INTO realm_catalog_state(
              chain_id,observed_height,rpc_path_count,refreshed_at,
              activity_from_height,activity_through_height)
              VALUES ('topaz-1',25,1,now(),10,20)""")
            cursor.executemany("""INSERT INTO blocks(
              height,block_hash_base64,block_hash_hex,time_utc,tx_count)
              VALUES (%s,%s,%s,now(),1)""", [
                (height, base64.b64encode(f"rebuild-block-{height}".encode()).decode(),
                 f"{height + 2000:064X}") for height in range(10, 26)
            ])
            cursor.executemany("""INSERT INTO transactions(
              block_height,tx_index,raw_base64,raw_base64_length,decoded_bytes,
              decoded_byte_length,decode_status,tx_hash_hex,payload_summary)
              VALUES (%s,0,%s,%s,%s,%s,'decoded',%s,%s::jsonb)""", [
                (height, raw := base64.b64encode(f"rebuild-tx-{height}".encode()).decode(),
                 len(raw), base64.b64decode(raw), len(base64.b64decode(raw)),
                 f"{height + 3000:064X}", summary) for height in range(10, 26)
            ])
            cursor.execute("""INSERT INTO realm_catalog(
              chain_id,path,path_kind,seen_via_transactions,first_seen_height,
              last_activity_height,last_activity_tx_index,last_activity_at,call_count,
              successful_call_count,failed_call_count,unknown_result_call_count,last_counted_height)
              VALUES ('topaz-1','gno.land/r/coverage/rebuild','realm',true,10,
                      20,0,now(),11,0,0,11,20)""")
            with self.assertRaises(RealmActivityCoverageError):
                advance_realm_activity_coverage(cursor, "topaz-1", 25)
            cursor.execute("SELECT activity_through_height,call_count FROM realm_catalog_state CROSS JOIN realm_catalog WHERE realm_catalog_state.chain_id='topaz-1' AND realm_catalog.path='gno.land/r/coverage/rebuild'")
            self.assertEqual(cursor.fetchone(), (20, 11))
            self.assertEqual(rebuild_cursor(cursor, "topaz-1", 10, 25), 1)
            cursor.execute("""SELECT activity_from_height,activity_through_height,call_count,
              unknown_result_call_count FROM realm_catalog_state CROSS JOIN realm_catalog
              WHERE realm_catalog_state.chain_id='topaz-1'
                AND realm_catalog.path='gno.land/r/coverage/rebuild'""")
            self.assertEqual(cursor.fetchone(), (10, 25, 16, 16))

    def test_realm_api_queries_are_scoped_searchable_and_cursor_ordered(self):
        name = f"utsa_realm_chains_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO indexer_state(state_key,chain_id,last_finalized_height) VALUES ('default','topaz-1',0)")
            cursor.execute("""INSERT INTO realm_catalog_state(
              chain_id,observed_height,rpc_path_count,refreshed_at,activity_from_height,activity_through_height)
              VALUES ('topaz-1',10,1,now(),3,10),('other-1',20,1,now(),3,20)""")
            cursor.execute("""INSERT INTO realm_catalog(
              chain_id,path,path_kind,seen_via_rpc,seen_via_transactions,rpc_visible,last_rpc_seen_at,
              last_activity_height,last_activity_tx_index,last_activity_at,call_count,
              successful_call_count,last_counted_height)
              VALUES
              ('topaz-1','gno.land/r/alpha','realm',true,true,true,now(),10,0,now(),1,1,10),
              ('topaz-1','gno.land/r/beta','realm',true,true,true,now(),10,1,now(),1,1,10),
              ('topaz-1','gno.land/r/percent%marker','realm',true,true,true,now(),8,0,now(),1,1,8),
              ('topaz-1','gno.land/p/inactive','package',true,false,true,now(),NULL,NULL,NULL,0,0,NULL),
              ('other-1','gno.land/r/other','realm',true,true,true,now(),20,0,now(),100,100,20)""")
            cursor.execute(REALM_CATALOG_SUMMARY_SQL, ('topaz-1',))
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0][0], rows[0][6]), ('topaz-1', 4))

        database = ApiDatabase()
        database.open(ApiConfig(database_url=url))
        self.addCleanup(database.close)
        first_page = database.fetch_realm_catalog(
            chain_id='topaz-1', limit=10, kind='all', q=None,
            before_activity_height=None, before_path=None,
        )
        self.assertEqual(
            [item['path'] for item in first_page['items']],
            ['gno.land/r/alpha', 'gno.land/r/beta', 'gno.land/r/percent%marker', 'gno.land/p/inactive'],
        )
        search_page = database.fetch_realm_catalog(
            chain_id='topaz-1', limit=10, kind='all', q='%MARKER',
            before_activity_height=None, before_path=None,
        )
        self.assertEqual([item['path'] for item in search_page['items']], ['gno.land/r/percent%marker'])
        cursor_page = database.fetch_realm_catalog(
            chain_id='topaz-1', limit=10, kind='all', q=None,
            before_activity_height=10, before_path='gno.land/r/alpha',
        )
        self.assertEqual(
            [item['path'] for item in cursor_page['items']],
            ['gno.land/r/beta', 'gno.land/r/percent%marker', 'gno.land/p/inactive'],
        )
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO realm_catalog(
              chain_id,path,path_kind,seen_via_rpc,seen_via_transactions,rpc_visible,last_rpc_seen_at,
              last_activity_height,last_activity_tx_index,last_activity_at,call_count,
              successful_call_count,last_counted_height)
              VALUES
              ('topaz-1','gno.land/r/high','realm',true,true,true,now(),9,0,now(),3,3,9),
              ('topaz-1','gno.land/p/high-package','package',true,true,true,now(),20,0,now(),99,99,20),
              ('topaz-1','gno.land/r/historical','realm',true,true,false,now(),20,0,now(),99,99,20),
              ('topaz-1','gno.land/r/zero-visible','realm',true,false,true,now(),NULL,NULL,NULL,0,0,NULL)""")
        top = database.fetch_top_realms(chain_id='topaz-1', limit=10)
        self.assertEqual(top['source']['chain_id'], 'topaz-1')
        self.assertEqual((top['source']['activity_from_height'], top['source']['activity_through_height']), (3, 10))
        self.assertEqual(
            [item['path'] for item in top['items']],
            ['gno.land/r/high', 'gno.land/r/alpha', 'gno.land/r/beta', 'gno.land/r/percent%marker'],
        )

    def test_realm_namespace_aggregation_members_scopes_and_plan(self):
        name = f"utsa_realm_namespace_{os.getpid()}"
        self.create_database(name)
        url = self.database_url_for(name)
        init_database.initialize_or_validate(url)
        observed = datetime(2026, 8, 4, tzinfo=timezone.utc)
        rows = [
            ('gno.land/r/gnoswap/a', 'realm', True, 2, 40, 1, observed, 4, 3, 0, 1),
            ('gno.land/r/gnoswap/b', 'realm', False, 3, 40, 3, observed + timedelta(seconds=1), 4, 2, 1, 1),
            ('gno.land/r/gnoswap/c', 'realm', True, 4, 40, 3, observed + timedelta(seconds=2), 2, 1, 1, 0),
            ('gno.land/r/gnops/a', 'realm', True, 5, 30, 0, observed, 2, 1, 1, 0),
            ('gno.land/r/historical_only/a', 'realm', False, 6, 45, 0, observed, 20, 20, 0, 0),
            ('gno.land/r/zero_calls/a', 'realm', True, 7, None, None, None, 0, 0, 0, 0),
            ('gno.land/p/gnoswap/package', 'package', True, 1, 50, 0, observed, 99, 99, 0, 0),
            ('gno.land/r/Example/a', 'realm', True, 8, 20, 0, observed, 1, 1, 0, 0),
            ('gno.land/r/example/a', 'realm', True, 9, 20, 0, observed, 1, 1, 0, 0),
        ]
        rows.extend((f'gno.land/r/big/{index:03}', 'realm', True, 10 + index, 10 if index == 0 else None,
                     0 if index == 0 else None, observed if index == 0 else None,
                     1 if index == 0 else 0, 1 if index == 0 else 0, 0, 0) for index in range(101))
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO indexer_state(state_key,chain_id,last_finalized_height) VALUES ('default','topaz-1',50)")
            cursor.execute("""INSERT INTO realm_catalog_state(chain_id,observed_height,rpc_path_count,refreshed_at,
              activity_from_height,activity_through_height) VALUES ('topaz-1',49,110,%s,1,45)""", (observed,))
            cursor.executemany("""INSERT INTO realm_catalog(chain_id,path,path_kind,seen_via_rpc,seen_via_transactions,
              rpc_visible,last_rpc_seen_at,first_seen_height,last_activity_height,last_activity_tx_index,last_activity_at,
              call_count,successful_call_count,failed_call_count,unknown_result_call_count,last_counted_height)
              VALUES ('topaz-1',%s,%s,true,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              [(path, kind, visible, observed, first, height, tx, timestamp, calls, success, failed, unknown,
                height) for path, kind, visible, first, height, tx, timestamp, calls, success, failed, unknown in rows])
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + REALM_NAMESPACE_TOP_SQL,
                           ('topaz-1', False, ['gnoswap'], 10))
            plan = cursor.fetchone()[0][0]
            self.assertGreaterEqual(plan['Execution Time'], 0)
            self.assertIn('Shared Hit Blocks', plan['Plan'])
        database = ApiDatabase(); database.open(ApiConfig(database_url=url)); self.addCleanup(database.close)
        result = database.fetch_top_realm_namespaces(chain_id='topaz-1', limit=10, curated_only=False,
                                                     curated_namespace_keys=('gnoswap',))
        self.assertEqual((result['source']['indexed_height'], result['source']['observed_height'],
                          result['source']['activity_from_height'], result['source']['activity_through_height']), (50,49,1,45))
        by_key = {item['namespace_key']: item for item in result['items']}
        self.assertEqual(list(by_key)[:2], ['gnoswap','gnops'])
        self.assertNotIn('historical_only', by_key); self.assertNotIn('zero_calls', by_key)
        self.assertNotIn('package', by_key); self.assertIn('Example', by_key); self.assertIn('example', by_key)
        gnoswap = by_key['gnoswap']
        self.assertEqual((gnoswap['realm_count'],gnoswap['called_realm_count'],gnoswap['rpc_visible_realm_count']), (3,3,2))
        self.assertEqual((gnoswap['direct_call_count'],gnoswap['successful_call_count'],gnoswap['failed_call_count'],
                          gnoswap['unknown_result_call_count']), (10,6,2,2))
        self.assertEqual((gnoswap['first_seen_height'],gnoswap['latest_activity_path'],gnoswap['last_activity_height'],
                          gnoswap['last_activity_tx_index'],gnoswap['last_activity_at']),
                         (2,'gno.land/r/gnoswap/b',40,3,observed + timedelta(seconds=1)))
        members = [row for row in result['members'] if row['namespace_key']=='gnoswap']
        self.assertEqual([row['path'] for row in members], ['gno.land/r/gnoswap/a','gno.land/r/gnoswap/b','gno.land/r/gnoswap/c'])
        self.assertFalse(members[1]['rpc_visible'])
        big_members = [row for row in result['members'] if row['namespace_key']=='big']
        self.assertEqual([row['path'] for row in big_members],
                         [f'gno.land/r/big/{index:03}' for index in range(100)])
        self.assertNotIn('gno.land/r/big/100', [row['path'] for row in big_members])
        self.assertEqual((big_members[0]['member_number'], big_members[-1]['member_number']), (1, 100))
        curated = database.fetch_top_realm_namespaces(chain_id='topaz-1', limit=10, curated_only=True,
                                                       curated_namespace_keys=('gnoswap',))
        self.assertEqual([row['namespace_key'] for row in curated['items']], ['gnoswap'])
        empty = database.fetch_top_realm_namespaces(chain_id='topaz-1', limit=10, curated_only=True,
                                                     curated_namespace_keys=())
        self.assertEqual((empty['items'],empty['members']), ([],[]))
        limited = database.fetch_top_realm_namespaces(chain_id='topaz-1', limit=1, curated_only=False,
                                                       curated_namespace_keys=())
        self.assertEqual(len(limited['items']), 1)

    def test_partial_realm_catalogs_are_rejected_and_rolled_back(self):
        for suffix, ddl in (
            ('catalog', 'CREATE TABLE realm_catalog(chain_id text)'),
            ('state', 'CREATE TABLE realm_catalog_state(chain_id text)'),
        ):
            url = self.create_exact_stage_database(
                f"utsa_realm_partial_{suffix}_{os.getpid()}",
                init_database.PRE_REALM_CATALOG_EXPECTATIONS,
            )
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute(ddl)
            with self.assertRaises(init_database.SchemaCompatibilityError):
                init_database.initialize_or_validate(url)
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.realm_catalog'),to_regclass('public.realm_catalog_state')")
                observed = cursor.fetchone()
                self.assertEqual(observed, ('realm_catalog', None) if suffix == 'catalog' else (None, 'realm_catalog_state'))


    def metadata_snapshot(self, *, height=10, collected_at=None, content="package demo\n"):
        path = "gno.land/r/metadata_demo"
        files = (
            MetadataFile("main.gno", content + 'import "gno.land/p/missing/dependency"\n'),
            MetadataFile("README.md", "bounded metadata\n"),
        )
        return MetadataSnapshot(
            "topaz-1", path, "realm", height, "complete",
            tuple(item.filename for item in files), files,
            collected_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def prepare_metadata_database(self, name):
        self.ensure_application_roles()
        self.create_database(name)
        url = self.database_url_for(name)
        initialized = self.run_init(url)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO realm_catalog(
              chain_id,path,path_kind,seen_via_rpc,rpc_visible,last_rpc_seen_at
            ) VALUES ('topaz-1','gno.land/r/metadata_demo','realm',true,true,now())""")
        return url

    def test_metadata_schema_upgrade_checks_indexes_and_privileges(self):
        self.ensure_application_roles()
        url = self.create_exact_stage_database(
            f"utsa_metadata_upgrade_{os.getpid()}",
            init_database.PRE_REALM_METADATA_EXPECTATIONS,
            create_roles_before_schema=True,
        )
        upgraded = self.run_init(url)
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        repeated = self.run_init(url)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            snapshot = init_database.fetch_schema_snapshot(cursor)
            init_database.validate_schema_snapshot(snapshot)
            metadata = {name for name in snapshot["tables"] if name.startswith("realm_metadata")}
            self.assertEqual(metadata, init_database.METADATA_TABLES)
            self.assertEqual(
                {name for name in snapshot["indexes"] if name.startswith("realm_metadata_imports_")},
                {"realm_metadata_imports_source_idx", "realm_metadata_imports_reverse_idx"},
            )
            for table in init_database.METADATA_TABLES:
                expected_api_select = table != "realm_metadata_refresh_state"
                for privilege in (
                    "SELECT", "INSERT", "UPDATE", "DELETE",
                    "TRUNCATE", "REFERENCES", "TRIGGER",
                ):
                    cursor.execute(
                        "SELECT has_table_privilege('utsa_gno_indexer', %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0],
                        privilege in {"SELECT", "INSERT", "UPDATE", "DELETE"},
                    )
                    cursor.execute(
                        "SELECT has_table_privilege('utsa_gno_api', %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0],
                        expected_api_select if privilege == "SELECT" else False,
                    )
            cursor.execute("SET ROLE utsa_gno_api")
            cursor.execute("SELECT path FROM realm_metadata LIMIT 1")
            cursor.fetchall()
            cursor.execute("RESET ROLE")
            cursor.execute("SET ROLE utsa_gno_api")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("SELECT * FROM realm_metadata_refresh_state")
            connection.rollback()
            cursor.execute("SET ROLE utsa_gno_api")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("DELETE FROM realm_metadata")
            connection.rollback()

        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("REVOKE DELETE ON realm_metadata FROM utsa_gno_indexer")
            with self.assertRaisesRegex(
                init_database.SchemaCompatibilityError, "Indexer role"
            ):
                init_database.validate_participant_privileges(cursor)
            connection.rollback()

        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("GRANT TRUNCATE ON realm_metadata TO utsa_gno_indexer")
            with self.assertRaisesRegex(
                init_database.SchemaCompatibilityError, "Indexer role"
            ):
                init_database.validate_participant_privileges(cursor)
            connection.rollback()

        partial_url = self.create_exact_stage_database(
            f"utsa_metadata_partial_{os.getpid()}",
            init_database.PRE_REALM_METADATA_EXPECTATIONS,
        )
        with psycopg.connect(partial_url) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE realm_metadata(chain_id text)")
        with self.assertRaises(init_database.SchemaCompatibilityError):
            init_database.initialize_or_validate(partial_url)

    def test_metadata_upgrade_with_production_writer_ownership(self):
        name = f"utsa_metadata_writer_owner_{os.getpid()}"
        writer_url = self.create_writer_owned_database(name)
        schema = self.build_historical_schema(
            init_database.PRE_REALM_METADATA_EXPECTATIONS
        )
        with psycopg.connect(writer_url) as connection, connection.cursor() as cursor:
            cursor.execute(schema)
            init_database.validate_schema_snapshot(
                init_database.fetch_schema_snapshot(cursor),
                init_database.PRE_REALM_METADATA_EXPECTATIONS,
            )
            cursor.execute(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = 'transaction_participants'"
            )
            self.assertEqual(cursor.fetchone()[0], "utsa_gno_indexer")

        upgraded = self.run_init(writer_url)
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        repeated = self.run_init(writer_url)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)

        with psycopg.connect(writer_url) as connection, connection.cursor() as cursor:
            init_database.validate_schema_snapshot(init_database.fetch_schema_snapshot(cursor))
            init_database.validate_participant_privileges(cursor)
            cursor.execute(
                "SELECT tablename, tableowner FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = ANY(%s)",
                (list(init_database.METADATA_TABLES),),
            )
            self.assertEqual(
                dict(cursor.fetchall()),
                {table: "utsa_gno_indexer" for table in init_database.METADATA_TABLES},
            )
            for table in init_database.METADATA_TABLES:
                expected_api_select = table != "realm_metadata_refresh_state"
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege('utsa_gno_indexer', %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    self.assertTrue(cursor.fetchone()[0])
                for privilege in (
                    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
                    "REFERENCES", "TRIGGER",
                ):
                    cursor.execute(
                        "SELECT has_table_privilege('utsa_gno_api', %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    self.assertEqual(
                        cursor.fetchone()[0],
                        expected_api_select if privilege == "SELECT" else False,
                    )

    def test_metadata_publication_replacement_preservation_and_stale_guard(self):
        url = self.prepare_metadata_database(f"utsa_metadata_publish_{os.getpid()}")
        with psycopg.connect(url) as connection:
            first = self.metadata_snapshot()
            publish_metadata_snapshot(connection, first)
            self.assertFalse(connection.closed)
            with connection.cursor() as cursor:
                cursor.execute("""SELECT file_count,dependency_count,total_file_bytes
                  FROM realm_metadata WHERE chain_id=%s AND path=%s""", (first.chain_id, first.path))
                self.assertEqual(cursor.fetchone()[:2], (2, 1))
                cursor.execute("SELECT count(*) FROM realm_metadata_files")
                self.assertEqual(cursor.fetchone()[0], 2)
                cursor.execute("""SELECT source_filename,imported_path,imported_kind
                  FROM realm_metadata_imports WHERE imported_path=%s""",
                  ("gno.land/p/missing/dependency",))
                self.assertEqual(cursor.fetchone(), ("main.gno", "gno.land/p/missing/dependency", "package"))
                cursor.execute("SELECT inserted_at FROM realm_metadata_files WHERE filename='main.gno'")
                inserted_at = cursor.fetchone()[0]

            unchanged = MetadataSnapshot(
                first.chain_id, first.path, first.path_kind, 11, first.collection_status,
                first.expected_filenames, first.files,
                first.collected_at + timedelta(minutes=1),
            )
            publish_metadata_snapshot(connection, unchanged)
            with connection.cursor() as cursor:
                cursor.execute("SELECT inserted_at FROM realm_metadata_files WHERE filename='main.gno'")
                self.assertEqual(cursor.fetchone()[0], inserted_at)

            successful = MetadataSnapshot(
                first.chain_id, first.path, first.path_kind, 12, first.collection_status,
                first.expected_filenames, first.files, first.collected_at + timedelta(minutes=2),
                qdoc=JsonCapability("ok", json.dumps({"package_path": first.path, "funcs": [], "values": [], "types": []})),
                qpkg_json=JsonCapability("ok", '{"name":"demo"}'),
                qfuncs=JsonCapability("ok", '[{"FuncName":"Hello","Params":[],"Results":[]}]'),
                qrender=RenderCapability("ok", "a" * 64, 5, 1, True),
                qstorage=StorageCapability("ok", 7, 8),
            )
            publish_metadata_snapshot(connection, successful)
            failed = MetadataSnapshot(
                first.chain_id, first.path, first.path_kind, 13, first.collection_status,
                first.expected_filenames, first.files, first.collected_at + timedelta(minutes=3),
                qdoc=JsonCapability("rpc_error"), qpkg_json=JsonCapability("application_error"),
                qfuncs=JsonCapability("invalid_response"), qrender=RenderCapability("rpc_error"),
                qstorage=StorageCapability("application_error"),
            )
            publish_metadata_snapshot(connection, failed)
            with connection.cursor() as cursor:
                cursor.execute("""SELECT qdoc_status,qdoc_last_successful_height,qdoc_payload,
                  qpkg_json_last_successful_height,qfuncs_last_successful_height,
                  qrender_last_successful_height,qstorage_last_successful_height
                  FROM realm_metadata WHERE chain_id=%s AND path=%s""", (first.chain_id, first.path))
                row = cursor.fetchone()
                self.assertEqual(row[0:2], ("rpc_error", 12))
                self.assertEqual(row[2]["package_path"], first.path)
                self.assertEqual(row[3:], (12, 12, 12, 12))
            with self.assertRaises(StaleMetadataSnapshot):
                publish_metadata_snapshot(connection, unchanged)
            self.assertFalse(connection.closed)
            with connection.cursor() as cursor:
                cursor.execute("SELECT observed_height FROM realm_metadata")
                self.assertEqual(cursor.fetchone()[0], 13)

            changed = self.metadata_snapshot(
                height=14, collected_at=first.collected_at + timedelta(minutes=4),
                content="package changed\n",
            )
            publish_metadata_snapshot(connection, changed)
            with connection.cursor() as cursor:
                cursor.execute("SELECT content FROM realm_metadata_files WHERE filename='main.gno'")
                self.assertIn("package changed", cursor.fetchone()[0])

    def test_metadata_parent_lock_serializes_first_publication_and_refresh_preserves_success(self):
        url = self.prepare_metadata_database(f"utsa_metadata_lock_{os.getpid()}")
        newer = self.metadata_snapshot(
            height=11,
            collected_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        older = self.metadata_snapshot(
            height=10,
            collected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        started = threading.Event()
        result = []

        def delayed_publisher():
            with psycopg.connect(url) as connection:
                started.set()
                try:
                    publish_metadata_snapshot(connection, older)
                except Exception as exc:  # captured for assertion in the parent thread
                    result.append(exc)

        with psycopg.connect(url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    publish_metadata_snapshot_cursor(cursor, newer)
                    thread = threading.Thread(target=delayed_publisher)
                    thread.start()
                    self.assertTrue(started.wait(2))
                    time.sleep(0.2)
                    self.assertTrue(thread.is_alive())
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], StaleMetadataSnapshot)
            with connection.cursor() as cursor:
                cursor.execute("SELECT observed_height FROM realm_metadata")
                self.assertEqual(cursor.fetchone()[0], 11)

                first_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
                persist_metadata_refresh_state_cursor(cursor, MetadataRefreshState(
                    "topaz-1", 10, "complete", 1, 1, 0, first_at,
                    first_at + timedelta(seconds=1), 10, first_at + timedelta(seconds=1),
                ))
                retry_at = first_at + timedelta(minutes=1)
                persist_metadata_refresh_state_cursor(cursor, MetadataRefreshState(
                    "topaz-1", 11, "running", 1, 0, 0, retry_at,
                ))
                persist_metadata_refresh_state_cursor(cursor, MetadataRefreshState(
                    "topaz-1", 11, "failed", 1, 0, 1, retry_at,
                    retry_at + timedelta(seconds=1),
                ))
                cursor.execute("""SELECT last_successful_height,last_successful_at
                  FROM realm_metadata_refresh_state WHERE chain_id='topaz-1'""")
                self.assertEqual(cursor.fetchone(), (10, first_at + timedelta(seconds=1)))

    def test_metadata_cursor_failure_rolls_back_and_connection_remains_usable(self):
        url = self.prepare_metadata_database(f"utsa_metadata_rollback_{os.getpid()}")
        with psycopg.connect(url) as connection:
            first = self.metadata_snapshot()
            publish_metadata_snapshot(connection, first)
            with self.assertRaises(psycopg.errors.CheckViolation) as raised:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        replacement = self.metadata_snapshot(
                            height=11,
                            collected_at=first.collected_at + timedelta(minutes=1),
                            content="package replacement\n",
                        )
                        publish_metadata_snapshot_cursor(cursor, replacement)
                        cursor.execute("""INSERT INTO realm_metadata_refresh_state(
                          chain_id,observed_height,run_status,selected_path_count,
                          published_path_count,failed_path_count,started_at
                        ) VALUES ('invalid',0,'running',0,0,0,now())""")
            self.assertEqual(
                raised.exception.diag.constraint_name,
                "realm_metadata_refresh_state_height_check",
            )
            self.assertFalse(connection.closed)
            with connection.cursor() as cursor:
                cursor.execute("SELECT observed_height FROM realm_metadata")
                self.assertEqual(cursor.fetchone()[0], 10)
                cursor.execute("SELECT content FROM realm_metadata_files WHERE filename='main.gno'")
                self.assertIn("package demo", cursor.fetchone()[0])
                cursor.execute("SELECT 1")
                self.assertEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
