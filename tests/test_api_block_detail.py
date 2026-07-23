import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
BLOCK_TIME = datetime(2026, 7, 16, 15, 0, 2, 313877, tzinfo=timezone.utc)
BLOCK_HASH = "0x0f21fd30003cbb6eb8a58117ddb0ee97d68d8115488430c99a2b1bb8361f1e33"
BLOCK_HASH_UPPER = "0F21FD30003CBB6EB8A58117DDB0EE97D68D8115488430C99A2B1BB8361F1E33"
BASE64_HASH = "DyH9MAA8u264pYEX3bDul9aNgRVIhDDJkqKbuDYfHjM="


class FakeDatabase:
    def __init__(self):
        self.details = {}
        self.error = None
        self.open_count = 0
        self.close_count = 0

    def open(self, config):
        self.open_count += 1

    def close(self):
        self.close_count += 1

    def fetch_block_detail(self, height):
        if self.error is not None:
            raise self.error
        return self.details.get(height)


def block_detail(**overrides):
    detail = {
        "block": {
            "height": 870117,
            "block_hash_hex": BLOCK_HASH,
            "block_hash_base64": BASE64_HASH,
            "time_utc": BLOCK_TIME,
            "proposer_address": None,
            "proposer_moniker": None,
            "tx_count": 2,
            "raw_block_response": {"secret": SECRET_URL},
            "inserted_at": BLOCK_TIME,
            "updated_at": BLOCK_TIME,
        },
        "commit": {
            "validators": 4,
            "signed": 1,
            "nil": 1,
            "absent": 1,
            "invalid": 1,
            "unknown": 1,
            "missed": 3,
        },
        "transactions": [
            {
                "tx_index": 1,
                "tx_hash_hex": None,
                "raw_base64": "second",
                "raw_base64_length": 6,
                "decoded_byte_length": None,
                "decode_status": "invalid_base64",
                "decoded_bytes": b"secret",
                "payload_summary": {"secret": SECRET_URL},
                "inserted_at": BLOCK_TIME,
            },
            {
                "tx_index": 0,
                "tx_hash_hex": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "raw_base64": "first",
                "raw_base64_length": 5,
                "decoded_byte_length": 3,
                "decode_status": "decoded",
                "decoded_bytes": b"abc",
                "payload_summary": {"secret": SECRET_URL},
                "inserted_at": BLOCK_TIME,
            },
        ],
    }
    detail.update(overrides)
    return detail


class ApiBlockDetailTests(unittest.TestCase):
    def make_client(self, fake_database):
        from api import app as app_module

        config = ApiConfig(database_url=SECRET_URL)
        patches = [
            patch.object(app_module, "database", fake_database),
            patch.object(app_module, "load_config", return_value=config),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return TestClient(app_module.app)

    def test_successful_block_detail_response(self):
        fake_database = FakeDatabase()
        detail = block_detail()
        detail["transactions"] = sorted(detail["transactions"], key=lambda row: row["tx_index"])
        fake_database.details[870117] = detail
        with self.make_client(fake_database) as client:
            response = client.get("/api/blocks/870117")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "height": 870117,
                "block_hash": BLOCK_HASH_UPPER,
                "block_hash_base64": BASE64_HASH,
                "time": "2026-07-16T15:00:02.313877Z",
                "proposer_address": None,
                "proposer_moniker": None,
                "tx_count": 2,
                "commit": {
                    "validators": 4,
                    "signed": 1,
                    "missed": 3,
                    "nil": 1,
                    "absent": 1,
                    "invalid": 1,
                    "unknown": 1,
                },
                "transactions": [
                    {
                        "index": 0,
                        "tx_hash": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
                        "raw_base64": "first",
                        "raw_base64_length": 5,
                        "decoded_byte_length": 3,
                        "decode_status": "decoded",
                    },
                    {
                        "index": 1,
                        "tx_hash": None,
                        "raw_base64": "second",
                        "raw_base64_length": 6,
                        "decoded_byte_length": None,
                        "decode_status": "invalid_base64",
                    },
                ],
            },
        )

    def test_empty_transactions_and_zero_commit_counters(self):
        fake_database = FakeDatabase()
        fake_database.details[870118] = block_detail(
            block={
                "height": 870118,
                "block_hash_hex": BLOCK_HASH_UPPER,
                "block_hash_base64": BASE64_HASH,
                "time_utc": BLOCK_TIME,
                "proposer_address": "g1proposer",
                "proposer_moniker": "UTSA",
                "tx_count": 0,
            },
            commit={
                "validators": 0,
                "signed": 0,
                "nil": 0,
                "absent": 0,
                "invalid": 0,
                "unknown": 0,
                "missed": 0,
            },
            transactions=[],
        )
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks/870118").json()
        self.assertEqual(data["proposer_moniker"], "UTSA")
        self.assertEqual(data["proposer_address"], "g1proposer")
        self.assertEqual(data["transactions"], [])
        self.assertEqual(data["commit"], {"validators": 0, "signed": 0, "missed": 0, "nil": 0, "absent": 0, "invalid": 0, "unknown": 0})

    def test_missing_block_returns_404(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            response = client.get("/api/blocks/999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Block not found"})

    def test_invalid_heights_return_422(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            self.assertEqual(client.get("/api/blocks/0").status_code, 422)
            self.assertEqual(client.get("/api/blocks/-1").status_code, 422)
            self.assertEqual(client.get("/api/blocks/not-an-integer").status_code, 422)

    def test_database_exception_returns_safe_503(self):
        fake_database = FakeDatabase()
        fake_database.error = RuntimeError(f"boom {SECRET_URL}")
        logger = logging.getLogger("api.app")
        with self.assertLogs(logger, level="ERROR") as captured:
            with self.make_client(fake_database) as client:
                response = client.get("/api/blocks/870117")
        combined = response.text + "\n" + "\n".join(captured.output)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
        self.assertNotIn(SECRET_URL, combined)
        self.assertNotIn("super-secret-password", combined)
        self.assertNotIn("db.internal", combined)
        self.assertNotIn("api_user", combined)

    def test_raw_database_fields_are_not_exposed(self):
        fake_database = FakeDatabase()
        detail = block_detail()
        detail["transactions"] = sorted(detail["transactions"], key=lambda row: row["tx_index"])
        fake_database.details[870117] = detail
        with self.make_client(fake_database) as client:
            text = response_text = client.get("/api/blocks/870117").text
        self.assertNotIn("decoded_bytes", text)
        self.assertNotIn("raw_block_response", text)
        self.assertNotIn("payload_summary", text)
        self.assertNotIn("inserted_at", text)
        self.assertNotIn("updated_at", text)
        self.assertNotIn(SECRET_URL, response_text)


if __name__ == "__main__":
    unittest.main()
