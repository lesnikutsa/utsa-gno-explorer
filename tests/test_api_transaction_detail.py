import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig


SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
BLOCK_TIME = datetime(2026, 7, 16, 15, 0, 2, 313877, tzinfo=timezone.utc)


class FakeDatabase:
    def __init__(self):
        self.details = {}
        self.error = None

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_transaction_detail(self, height, index):
        if self.error:
            raise self.error
        return self.details.get((height, index))


def transaction_row(**overrides):
    row = {
        "id": 17,
        "block_height": 984383,
        "tx_index": 0,
        "tx_hash_hex": "0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "raw_base64": " exact+Base64== ",
        "raw_base64_length": 17,
        "decoded_byte_length": 10,
        "decode_status": "decoded",
        "block_hash_hex": "0xabcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "time_utc": BLOCK_TIME,
        "proposer_address": "g1proposer",
        "proposer_moniker": "UTSA",
        "decoded_bytes": b"secret",
        "payload_summary": {"secret": SECRET_URL},
        "inserted_at": BLOCK_TIME,
        "updated_at": BLOCK_TIME,
    }
    row.update(overrides)
    return row


class ApiTransactionDetailTests(unittest.TestCase):
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

    def test_success_has_exact_public_fields_and_accepts_zero(self):
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row()
        with self.make_client(fake) as client:
            response = client.get("/api/blocks/984383/transactions/0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "block_height": 984383,
            "block_hash": "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
            "block_time": "2026-07-16T15:00:02.313877Z",
            "proposer_address": "g1proposer",
            "proposer_moniker": "UTSA",
            "index": 0,
            "tx_hash": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
            "raw_base64": " exact+Base64== ",
            "raw_base64_length": 17,
            "decoded_byte_length": 10,
            "decode_status": "decoded",
        })

    def test_nullable_fields_are_preserved(self):
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(proposer_address=None, proposer_moniker=None, decoded_byte_length=None, tx_hash_hex=None)
        with self.make_client(fake) as client:
            data = client.get("/api/blocks/984383/transactions/0").json()
        self.assertIsNone(data["proposer_address"])
        self.assertIsNone(data["proposer_moniker"])
        self.assertIsNone(data["decoded_byte_length"])
        self.assertIsNone(data["tx_hash"])

    def test_invalid_location_returns_422(self):
        with self.make_client(FakeDatabase()) as client:
            for path in ("/api/blocks/0/transactions/0", "/api/blocks/-1/transactions/0", "/api/blocks/1/transactions/-1"):
                self.assertEqual(client.get(path).status_code, 422)

    def test_missing_transaction_returns_404(self):
        with self.make_client(FakeDatabase()) as client:
            response = client.get("/api/blocks/984383/transactions/0")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Transaction not found"})

    def test_database_exception_is_safe(self):
        fake = FakeDatabase()
        fake.error = RuntimeError(SECRET_URL)
        with self.assertLogs(logging.getLogger("api.app"), level="ERROR") as captured:
            with self.make_client(fake) as client:
                response = client.get("/api/blocks/984383/transactions/0")
        combined = response.text + "\n" + "\n".join(captured.output)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
        self.assertNotIn(SECRET_URL, combined)
        self.assertNotIn("super-secret-password", combined)

    def test_internal_fields_are_absent(self):
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row()
        with self.make_client(fake) as client:
            text = client.get("/api/blocks/984383/transactions/0").text
        for field in ("decoded_bytes", "payload_summary", "tx_hash_hex", '"id"', "inserted_at", "updated_at"):
            self.assertNotIn(field, text)
        self.assertNotIn(SECRET_URL, text)


if __name__ == "__main__":
    unittest.main()
