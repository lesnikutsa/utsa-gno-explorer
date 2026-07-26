import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import TRANSACTION_BY_HASH_SQL

HASH = "AB" * 32


class FakeDatabase:
    def __init__(self):
        self.calls = []
        self.row = {"block_height": 195420, "tx_index": 0, "tx_hash_hex": HASH}
        self.error = None

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_transaction_by_hash(self, tx_hash):
        self.calls.append(tx_hash)
        if self.error:
            raise self.error
        return self.row


class TransactionHashLookupTests(unittest.TestCase):
    def test_hash_fixture_is_exactly_64_uppercase_hexadecimal_characters(self):
        self.assertEqual(len(HASH), 64)
        self.assertRegex(HASH, r"^[0-9A-F]{64}$")

    def make_client(self, fake):
        from api import app as app_module
        patches = [
            patch.object(app_module, "database", fake),
            patch.object(
                app_module,
                "load_config",
                return_value=ApiConfig(
                    database_url="postgresql://user:password@localhost/test_database",
                ),
            ),
        ]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        return TestClient(app_module.app)

    def test_accepted_forms_are_normalized_and_response_is_minimal(self):
        for value in (HASH, HASH.lower(), f"0x{HASH}", f"0X{HASH.lower()}"):
            with self.subTest(value=value):
                fake = FakeDatabase()
                with self.make_client(fake) as client:
                    response = client.get(f"/api/transactions/by-hash/{value}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"block_height": 195420, "index": 0, "tx_hash": HASH})
                self.assertEqual(fake.calls, [HASH])

    def test_missing_hash_returns_404(self):
        fake = FakeDatabase()
        fake.row = None
        with self.make_client(fake) as client:
            response = client.get(f"/api/transactions/by-hash/{HASH}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Transaction not found"})

    def test_invalid_hashes_return_422_without_query(self):
        for value in ("A" * 63, "A" * 65, "G" * 64):
            with self.subTest(value=value):
                fake = FakeDatabase()
                with self.make_client(fake) as client:
                    response = client.get(f"/api/transactions/by-hash/{value}")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {"detail": "Invalid transaction hash"})
                self.assertEqual(fake.calls, [])

    def test_database_failure_is_safe(self):
        fake = FakeDatabase()
        fake.error = RuntimeError("secret SQL and DATABASE_URL")
        with self.make_client(fake) as client:
            response = client.get(f"/api/transactions/by-hash/{HASH}")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
        self.assertNotIn("secret", response.text)

    def test_query_is_bounded_exact_and_deterministic(self):
        normalized = " ".join(TRANSACTION_BY_HASH_SQL.upper().split())
        self.assertIn("WHERE TX_HASH_HEX = %S", normalized)
        self.assertIn("ORDER BY BLOCK_HEIGHT DESC, TX_INDEX DESC", normalized)
        self.assertIn("LIMIT 1", normalized)
        for forbidden in (" LIKE ", " ILIKE ", " COUNT", " OFFSET "):
            self.assertNotIn(forbidden, f" {normalized} ")

    def test_endpoint_paths_coexist_and_lookup_response_scope_is_explicit(self):
        from api.app import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/transactions", paths)
        self.assertIn("/api/transactions/by-hash/{tx_hash}", paths)
        self.assertIn("/api/blocks/{height}/transactions/{index}", paths)
        response_fields = app.openapi()["components"]["schemas"]["TransactionHashLookupResponse"]["properties"]
        self.assertEqual(set(response_fields), {"block_height", "index", "tx_hash"})


if __name__ == "__main__":
    unittest.main()
