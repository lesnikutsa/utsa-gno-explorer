import importlib
import logging
import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("FastAPI is not installed in this environment") from exc

from api.config import ApiConfig
from api.database import MissingIndexerStateError

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"


class FakeDatabase:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.opened_with = None
        self.open_count = 0
        self.close_count = 0

    def open(self, config):
        self.opened_with = config
        self.open_count += 1

    def close(self):
        self.close_count += 1

    def fetch_health_row(self):
        if self.error is not None:
            raise self.error
        return self.row


def health_row(**overrides):
    row = {
        "chain_id": "test-13",
        "indexed_height": 845840,
        "finalized_tip_height": 845840,
        "rpc_last_checked_at": datetime.now(UTC),
    }
    row.update(overrides)
    return row


class ApiHealthTests(unittest.TestCase):
    def make_client(self, fake_database, *, lag_threshold=10, stale_seconds=60):
        from api import app as app_module

        config = ApiConfig(
            database_url=SECRET_URL,
            indexer_lag_degraded_threshold=lag_threshold,
            rpc_check_stale_seconds=stale_seconds,
        )
        patches = [
            patch.object(app_module, "database", fake_database),
            patch.object(app_module, "load_config", return_value=config),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return TestClient(app_module.app)

    def test_successful_health_response(self):
        checked_at = datetime(2026, 7, 16, 12, 34, 55, tzinfo=UTC)
        fake_database = FakeDatabase(health_row(rpc_last_checked_at=checked_at))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "database": "ok",
                "chain_id": "test-13",
                "indexed_height": 845840,
                "finalized_tip_height": 845840,
                "indexer_lag": 0,
                "rpc_last_checked_at": "2026-07-16T12:34:55Z",
                "api_version": "0.6.0",
            },
        )

    def test_degraded_response_caused_by_indexer_lag(self):
        fake_database = FakeDatabase(health_row(indexed_height=100, finalized_tip_height=111))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["indexer_lag"], 11)

    def test_degraded_response_caused_by_stale_rpc_check(self):
        stale_time = datetime.now(UTC) - timedelta(seconds=61)
        fake_database = FakeDatabase(health_row(rpc_last_checked_at=stale_time))
        with self.make_client(fake_database, stale_seconds=60) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")

    def test_degraded_response_when_rpc_last_checked_at_is_null(self):
        fake_database = FakeDatabase(health_row(rpc_last_checked_at=None))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertIsNone(response.json()["rpc_last_checked_at"])

    def test_http_503_when_indexer_state_is_missing(self):
        fake_database = FakeDatabase(error=MissingIndexerStateError("missing default row"))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})

    def test_http_503_when_database_access_raises_exception(self):
        fake_database = FakeDatabase(error=RuntimeError(f"boom {SECRET_URL}"))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})

    def test_database_url_and_password_are_not_exposed_in_responses_or_logs(self):
        fake_database = FakeDatabase(error=RuntimeError(f"boom {SECRET_URL}"))
        logger = logging.getLogger("api.app")
        with self.assertLogs(logger, level="ERROR") as captured:
            with self.make_client(fake_database) as client:
                response = client.get("/api/health")
        combined = response.text + "\n" + "\n".join(captured.output)
        self.assertNotIn(SECRET_URL, combined)
        self.assertNotIn("super-secret-password", combined)
        self.assertNotIn("db.internal", combined)

    def test_application_startup_and_shutdown_open_and_close_pool(self):
        fake_database = FakeDatabase(health_row())
        with self.make_client(fake_database) as client:
            self.assertEqual(fake_database.open_count, 1)
            self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(fake_database.close_count, 1)

    def test_no_postgresql_connection_is_opened_during_module_import(self):
        sys.modules.pop("api.database", None)
        with patch("psycopg_pool.ConnectionPool") as pool_class:
            importlib.import_module("api.database")
        pool_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
