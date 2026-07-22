import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig

SECRET = "postgresql://api_user:change-me@db.example.invalid/explorer"


class FakeDatabase:
    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.calls = rows or [], error, []
    def open(self, config): pass
    def close(self): pass
    def fetch_validator_search(self, query, limit):
        self.calls.append((query, limit))
        if self.error: raise self.error
        return self.rows


class ApiValidatorSearchTests(unittest.TestCase):
    def client(self, database):
        from api import app as module
        patches = [
            patch.object(module, "database", database),
            patch.object(module, "load_config", return_value=ApiConfig(database_url=SECRET)),
        ]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        return TestClient(module.app)

    def test_validation_bounds_and_required_query(self):
        with self.client(FakeDatabase()) as client:
            for path in [
                "/api/search/validators", "/api/search/validators?q=+",
                f"/api/search/validators?q={'a' * 129}", "/api/search/validators?q=utsa&limit=0",
                "/api/search/validators?q=utsa&limit=11",
            ]:
                self.assertEqual(client.get(path).status_code, 422, path)

    def test_compact_response_trims_query_and_uses_default_limit(self):
        database = FakeDatabase([{
            "address": "g1signing", "moniker": "UTSA", "operator_address": "g1operator",
            "description": "must not leak", "server_type": "cloud",
        }])
        with self.client(database) as client:
            response = client.get("/api/search/validators", params={"q": "  UTSA  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [{"address": "g1signing", "moniker": "UTSA", "operator_address": "g1operator"}]})
        self.assertEqual(database.calls, [("UTSA", 6)])

    def test_empty_result_and_safe_database_failure(self):
        with self.client(FakeDatabase()) as client:
            self.assertEqual(client.get("/api/search/validators?q=none").json(), {"items": []})
        logger = logging.getLogger("api.app")
        with self.assertLogs(logger, level="ERROR") as captured:
            with self.client(FakeDatabase(error=RuntimeError(SECRET))) as client:
                response = client.get("/api/search/validators?q=utsa")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
        self.assertNotIn(SECRET, response.text + "".join(captured.output))


if __name__ == "__main__":
    unittest.main()
