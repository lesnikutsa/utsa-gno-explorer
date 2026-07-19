import logging
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import (
    ApiDatabase,
    MissingIndexedBlockError,
    MissingIndexerStateError,
    VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL,
    VALIDATOR_SIGNING_HISTORY_MATRIX_SQL,
)

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"


def block(height):
    return {
        "height": height,
        "time_utc": datetime(2026, 7, 19, 7, 0, height % 60, tzinfo=timezone.utc),
        "internal_timestamp": "forbidden",
    }


def matrix_row(address, height, *, membership=True, signature=True, signed=False, vote_status="absent"):
    return {
        "address": address,
        "height": height,
        "membership_address": address if membership else None,
        "signature_address": address if signature else None,
        "signed": signed,
        "vote_status": vote_status,
        "voting_power": "forbidden",
        "raw_precommit": "forbidden",
    }


def history_result(*, blocks=None, items=None):
    return {
        "checkpoint": {"height": 926006, "block_exists": True},
        "blocks": [block(925999), block(926006)] if blocks is None else blocks,
        "items": items if items is not None else [
            matrix_row("g1high", 925999, signed=True),
            matrix_row("g1high", 926006, vote_status="nil"),
        ],
    }


class FakeDatabase:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.limits = []
        self.detail_calls = []

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_validator_signing_history(self, *, limit):
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return self.result

    def fetch_validator_detail(self, address):
        self.detail_calls.append(address)
        return None


class ApiValidatorSigningHistoryTests(unittest.TestCase):
    def make_client(self, fake_database):
        from api import app as app_module

        patches = [
            patch.object(app_module, "database", fake_database),
            patch.object(app_module, "load_config", return_value=ApiConfig(database_url=SECRET_URL)),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return TestClient(app_module.app)

    def test_default_and_custom_limits_and_route_precedence(self):
        fake = FakeDatabase(history_result())
        with self.make_client(fake) as client:
            self.assertEqual(client.get("/api/validators/signing-history").status_code, 200)
            self.assertEqual(client.get("/api/validators/signing-history?limit=20").status_code, 200)
        self.assertEqual(fake.limits, [100, 20])
        self.assertEqual(fake.detail_calls, [])

    def test_limit_bounds(self):
        fake = FakeDatabase(history_result())
        with self.make_client(fake) as client:
            self.assertEqual(client.get("/api/validators/signing-history?limit=0").status_code, 422)
            self.assertEqual(client.get("/api/validators/signing-history?limit=101").status_code, 422)
        self.assertEqual(fake.limits, [])

    def test_shared_axis_statuses_order_and_public_fields(self):
        heights = list(range(10, 17))
        statuses = [
            dict(membership=False, signature=False),
            dict(signature=False),
            dict(signed=True, vote_status="invalid"),
            dict(vote_status="nil"),
            dict(vote_status="absent"),
            dict(vote_status="invalid"),
            dict(vote_status="unexpected"),
        ]
        rows = [matrix_row("g1power", height, **values) for height, values in zip(heights, statuses)]
        rows += [matrix_row("g1address", height, signed=True) for height in heights]
        result = history_result(blocks=[block(height) for height in heights], items=rows)
        with self.make_client(FakeDatabase(result)) as client:
            response = client.get("/api/validators/signing-history")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(list(data), ["height", "network_blocks", "start_height", "end_height", "blocks", "items"])
        self.assertEqual([item["height"] for item in data["blocks"]], heights)
        self.assertTrue(all(item["time"].endswith("Z") for item in data["blocks"]))
        self.assertEqual([item["address"] for item in data["items"]], ["g1power", "g1address"])
        self.assertEqual(data["items"][0]["statuses"],
                         ["not_active", "unknown", "commit", "nil", "absent", "invalid", "unknown"])
        self.assertTrue(all(len(item["statuses"]) == len(data["blocks"]) for item in data["items"]))
        self.assertEqual(set(data["blocks"][0]), {"height", "time"})
        self.assertEqual(set(data["items"][0]), {"address", "statuses"})
        for forbidden in ("voting_power", "raw_precommit", "signed", "vote_status", "internal_timestamp"):
            self.assertNotIn(forbidden, response.text)

    def test_empty_active_set_keeps_blocks_and_empty_history_is_defensive(self):
        with self.make_client(FakeDatabase(history_result(items=[]))) as client:
            data = client.get("/api/validators/signing-history").json()
        self.assertEqual(data["network_blocks"], 2)
        self.assertEqual(data["items"], [])

        with self.make_client(FakeDatabase(history_result(blocks=[], items=[]))) as client:
            data = client.get("/api/validators/signing-history").json()
        self.assertEqual(data, {
            "height": 926006, "network_blocks": 0, "start_height": None, "end_height": None,
            "blocks": [], "items": [],
        })

    def test_alignment_mismatch_and_database_errors_are_safe(self):
        cases = [
            FakeDatabase(history_result(items=[matrix_row("g1", 925999)])),
            FakeDatabase(error=MissingIndexerStateError()),
            FakeDatabase(error=MissingIndexedBlockError()),
            FakeDatabase(error=RuntimeError(SECRET_URL)),
        ]
        for fake in cases:
            with self.subTest(error=type(fake.error).__name__ if fake.error else "alignment"):
                with self.assertLogs(logging.getLogger("api.app"), level="ERROR") as captured:
                    with self.make_client(fake) as client:
                        response = client.get("/api/validators/signing-history")
                combined = response.text + "\n".join(captured.output)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
                for secret in (SECRET_URL, "super-secret-password", "db.internal"):
                    self.assertNotIn(secret, combined)

    def test_sql_is_bounded_parameterized_and_ordered(self):
        self.assertIn("WHERE height <= %s", VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL)
        self.assertIn("LIMIT %s", VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL)
        self.assertIn("ORDER BY height DESC", VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL)
        self.assertIn("ORDER BY height ASC", VALIDATOR_SIGNING_HISTORY_BLOCKS_SQL)
        self.assertIn("CROSS JOIN recent_blocks recent", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL)
        self.assertIn("membership.height = recent.height", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL)
        self.assertIn("membership.signing_address = current.signing_address", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL)
        self.assertIn("signature.height = membership.height", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL)
        self.assertIn("signature.signing_address = membership.signing_address", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL)
        self.assertIn(
            "ORDER BY current.voting_power DESC, current.signing_address ASC, recent.height ASC",
            VALIDATOR_SIGNING_HISTORY_MATRIX_SQL,
        )
        self.assertNotIn("max(", VALIDATOR_SIGNING_HISTORY_MATRIX_SQL.lower())


class FakeCursor:
    def __init__(self, result_sets):
        self.result_sets = iter(result_sets)
        self.current = []
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, parameters):
        self.executions.append((sql, parameters))
        self.current = next(self.result_sets)

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self):
        return self.fake_cursor


class FakePool:
    def __init__(self, cursor):
        self.fake_connection = FakeConnection(cursor)
        self.connection_count = 0

    @contextmanager
    def connection(self, timeout):
        self.connection_count += 1
        yield self.fake_connection


class ValidatorSigningHistoryDatabaseTests(unittest.TestCase):
    def test_one_connection_three_queries_and_parameterized_limit(self):
        checkpoint = {"height": 42, "block_exists": True}
        cursor = FakeCursor([[checkpoint], [block(41), block(42)], [
            matrix_row("g1a", 41), matrix_row("g1a", 42), matrix_row("g1b", 41), matrix_row("g1b", 42),
        ]])
        pool = FakePool(cursor)
        database = ApiDatabase()
        database.pool = pool

        result = database.fetch_validator_signing_history(limit=20)

        self.assertEqual(pool.connection_count, 1)
        self.assertEqual(len(cursor.executions), 3)
        self.assertEqual(cursor.executions[1][1], (42, 20))
        self.assertEqual(cursor.executions[2][1], (42, 20, 42))
        self.assertEqual(len(result["items"]), 4)

    def test_checkpoint_consistency_errors_prevent_history_queries(self):
        for checkpoint, error in ((None, MissingIndexerStateError),
                                  ({"height": 42, "block_exists": False}, MissingIndexedBlockError)):
            cursor = FakeCursor([[] if checkpoint is None else [checkpoint]])
            database = ApiDatabase()
            database.pool = FakePool(cursor)
            with self.assertRaises(error):
                database.fetch_validator_signing_history(limit=100)
            self.assertEqual(len(cursor.executions), 1)


if __name__ == "__main__":
    unittest.main()
