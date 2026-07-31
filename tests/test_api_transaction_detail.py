import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig


SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
BLOCK_TIME = datetime(2026, 7, 16, 15, 0, 2, 313877, tzinfo=timezone.utc)
PRIMARY = {"type": "gno.bank.MsgSend", "category": "bank", "action": "send", "label": "Send Tokens"}


def valid_summary(**overrides):
    summary = {
        "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
        "message_count": 1, "messages_truncated": False, "primary": dict(PRIMARY),
        "messages": [{**PRIMARY, "sender": "g1sender", "recipient": "g1recipient", "amount": "5000000ugnot"}],
    }
    summary.update(overrides)
    return summary


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
        "payload_summary": valid_summary(),
        "inserted_at": BLOCK_TIME,
        "updated_at": BLOCK_TIME,
        "execution_status": None,
        "gas_wanted": None,
        "gas_used": None,
        "error": None,
        "log": None,
        "info": None,
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
            "summary": valid_summary(),
            "execution_status": None,
            "gas_wanted": None,
            "gas_used": None,
            "error": None,
            "log": None,
            "info": None,
        })

    def test_failed_execution_fields_are_propagated_without_private_data(self):
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(
            execution_status="failed", gas_wanted="5000000", gas_used="934971",
            error="bounded failure", log="failed log", info="",
            raw_result={"private": True}, events=[{"private": True}],
            data_base64="cHJpdmF0ZQ==", source_rpc_endpoint_id=7,
        )
        with self.make_client(fake) as client:
            response = client.get("/api/blocks/984383/transactions/0")
        data = response.json()
        self.assertEqual({key: data[key] for key in (
            "execution_status", "gas_wanted", "gas_used", "error", "log", "info",
        )}, {
            "execution_status": "failed", "gas_wanted": "5000000",
            "gas_used": "934971", "error": "bounded failure",
            "log": "failed log", "info": "",
        })
        for private in ("raw_result", "events", "data_base64", "source_rpc_endpoint_id"):
            self.assertNotIn(private, data)
        self.assertNotIn({"private": True}, data.values())

    def test_nullable_fields_are_preserved(self):
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(proposer_address=None, proposer_moniker=None, decoded_byte_length=None, tx_hash_hex=None)
        with self.make_client(fake) as client:
            data = client.get("/api/blocks/984383/transactions/0").json()
        self.assertIsNone(data["proposer_address"])
        self.assertIsNone(data["proposer_moniker"])
        self.assertIsNone(data["decoded_byte_length"])
        self.assertIsNone(data["tx_hash"])

    def test_hash_normalization_and_malformed_fixture_safety(self):
        from api.app import _transaction_detail_from_row

        lowercase = "a" * 64
        self.assertEqual(_transaction_detail_from_row(transaction_row(tx_hash_hex=lowercase)).tx_hash, "A" * 64)
        self.assertEqual(_transaction_detail_from_row(transaction_row(tx_hash_hex="0x" + lowercase)).tx_hash, "A" * 64)
        self.assertIsNone(_transaction_detail_from_row(transaction_row(tx_hash_hex="malformed")).tx_hash)
        self.assertIsNone(_transaction_detail_from_row(transaction_row(tx_hash_hex=None)).tx_hash)

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

    def test_contract_call_keeps_only_safe_details(self):
        primary = {"type": "gno.vm.MsgCall", "category": "contract", "action": "call", "label": "Contract Call"}
        message = {**primary, "sender": "g1sender", "package_path": "gno.land/r/demo", "function": "Render", "args_count": 2, "send": "1ugnot", "args": [SECRET_URL]}
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(payload_summary=valid_summary(primary=primary, messages=[message]))
        with self.make_client(fake) as client:
            summary = client.get("/api/blocks/984383/transactions/0").json()["summary"]
        self.assertEqual(summary["messages"], [{key: value for key, value in message.items() if key != "args"}])

    def test_supported_fallback_statuses_and_null(self):
        for status, family in (("unsupported", "gno"), ("unparsed", "unknown"), ("invalid", "unknown")):
            fake = FakeDatabase()
            fake.details[(984383, 0)] = transaction_row(payload_summary=valid_summary(parse_status=status, chain_family=family))
            with self.make_client(fake) as client:
                summary = client.get("/api/blocks/984383/transactions/0").json()["summary"]
            self.assertEqual((summary["parse_status"], summary["chain_family"]), (status, family))
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(payload_summary=None)
        with self.make_client(fake) as client:
            self.assertIsNone(client.get("/api/blocks/984383/transactions/0").json()["summary"])

    def test_unknown_and_sensitive_message_fields_are_discarded(self):
        unsafe = ("memo", "args", "signature", "public_key", "source_code", "internal_error", "stack_trace", "arbitrary")
        message = {**valid_summary()["messages"][0], **{key: f"secret-{key}" for key in unsafe}}
        fake = FakeDatabase()
        fake.details[(984383, 0)] = transaction_row(payload_summary=valid_summary(messages=[message]))
        with self.make_client(fake) as client:
            text = client.get("/api/blocks/984383/transactions/0").text
        for key in unsafe:
            self.assertNotIn(key, text)
            self.assertNotIn(f"secret-{key}", text)

    def test_malformed_summaries_become_null_without_payload_logging(self):
        malformed = [
            "secret-non-object", {}, valid_summary(schema_version=2),
            valid_summary(parse_status="secret-status"), valid_summary(chain_family="GNO"),
            valid_summary(messages_truncated=1), valid_summary(message_count=-1),
            valid_summary(message_count=100001), valid_summary(messages={}),
            valid_summary(messages=["secret-message"]),
            valid_summary(messages=[{"type": "x"}]),
            valid_summary(messages=[{**PRIMARY, "sender": {"secret": True}}]),
            valid_summary(messages=[dict(PRIMARY)] * 21, message_count=21),
            valid_summary(message_count=0),
            valid_summary(primary={**PRIMARY, "label": "Mismatch"}),
            valid_summary(messages=[{**PRIMARY, "sender": float("inf")}]),
            valid_summary(messages=[{**PRIMARY, "sender": "x" * 161}]),
        ]
        for stored in malformed:
            fake = FakeDatabase()
            fake.details[(984383, 0)] = transaction_row(payload_summary=stored)
            with self.assertLogs(logging.getLogger("api.app"), level="WARNING") as captured:
                with self.make_client(fake) as client:
                    response = client.get("/api/blocks/984383/transactions/0")
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["summary"])
            self.assertNotIn("secret", "\n".join(captured.output) + response.text)

    def test_openapi_uses_public_summary_and_scalar_message_fields(self):
        with self.make_client(FakeDatabase()) as client:
            schemas = client.get("/openapi.json").json()["components"]["schemas"]
        detail = schemas["TransactionDetailResponse"]["properties"]
        self.assertIn("summary", detail)
        self.assertNotIn("payload_summary", detail)
        message = schemas["TransactionSummaryMessage"]
        self.assertNotIn("additionalProperties", message)
        self.assertNotIn("object", str(message["properties"]["sender"]))


if __name__ == "__main__":
    unittest.main()
