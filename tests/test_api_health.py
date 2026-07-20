import importlib
import logging
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import MissingIndexerStateError

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
FIXED_NOW = datetime(2026, 7, 16, 12, 35, 0, tzinfo=timezone.utc)
RECENT_CHECK = datetime(2026, 7, 16, 12, 34, 55, tzinfo=timezone.utc)


class FakeDatabase:
    def __init__(self, row=None, error=None, open_error=None):
        self.row = row
        self.error = error
        self.open_error = open_error
        self.opened_with = None
        self.open_count = 0
        self.close_count = 0

    def open(self, config):
        self.opened_with = config
        self.open_count += 1
        if self.open_error is not None:
            raise self.open_error

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
        "rpc_last_checked_at": RECENT_CHECK,
        "has_healthy_rpc": True,
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
            patch.object(app_module, "utc_now", return_value=FIXED_NOW),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return TestClient(app_module.app)

    def test_successful_health_response(self):
        fake_database = FakeDatabase(health_row())
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
                "api_version": "0.7.0",
            },
        )


    def test_at_least_one_healthy_enabled_rpc_allows_ok_status(self):
        fake_database = FakeDatabase(health_row(has_healthy_rpc=True))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_no_healthy_enabled_rpc_produces_degraded_status(self):
        fake_database = FakeDatabase(health_row(has_healthy_rpc=False))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")

    def test_fresh_rpc_last_checked_at_does_not_hide_no_healthy_rpc(self):
        fake_database = FakeDatabase(
            health_row(rpc_last_checked_at=RECENT_CHECK, has_healthy_rpc=False)
        )
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rpc_last_checked_at"], "2026-07-16T12:34:55Z")
        self.assertEqual(response.json()["status"], "degraded")

    def test_degraded_response_caused_by_indexer_lag(self):
        fake_database = FakeDatabase(health_row(indexed_height=100, finalized_tip_height=111))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["indexer_lag"], 11)

    def test_degraded_response_caused_by_stale_rpc_check(self):
        stale_time = FIXED_NOW - timedelta(seconds=61)
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

    def test_temporary_postgresql_unavailability_does_not_prevent_startup(self):
        fake_database = FakeDatabase(error=TimeoutError(f"temporary outage {SECRET_URL}"))
        with self.make_client(fake_database) as client:
            response = client.get("/api/health")
        self.assertEqual(fake_database.open_count, 1)
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
        self.assertNotIn("api_user", combined)
        self.assertNotIn("explorer", combined)

    def test_startup_exception_does_not_preserve_sensitive_exception_text(self):
        from api import app as app_module

        fake_database = FakeDatabase(open_error=RuntimeError(f"cannot open {SECRET_URL}"))
        config = ApiConfig(database_url=SECRET_URL)
        with patch.object(app_module, "database", fake_database), patch.object(
            app_module, "load_config", return_value=config
        ):
            logger = logging.getLogger("api.app")
            with self.assertLogs(logger, level="ERROR") as captured:
                with self.assertRaises(RuntimeError) as raised:
                    with TestClient(app_module.app):
                        pass
        public_message = str(raised.exception)
        combined = public_message + "\n" + "\n".join(captured.output)
        self.assertEqual(public_message, "Explorer database is unavailable")
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(SECRET_URL, combined)
        self.assertNotIn("super-secret-password", combined)
        self.assertNotIn("db.internal", combined)
        self.assertNotIn("api_user", combined)
        self.assertNotIn("explorer", combined)
        self.assertNotIn("cannot open", combined)

    def test_application_startup_and_shutdown_open_and_close_pool(self):
        fake_database = FakeDatabase(health_row())
        with self.make_client(fake_database) as client:
            self.assertEqual(fake_database.open_count, 1)
            self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(fake_database.close_count, 1)

    def test_no_pool_or_postgresql_connection_is_created_during_module_import(self):
        sys.modules.pop("api.database", None)
        with patch("psycopg_pool.ConnectionPool") as pool_class:
            importlib.import_module("api.database")
        pool_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
