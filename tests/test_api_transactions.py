import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import TRANSACTIONS_SQL


DATABASE_URL = "postgresql://api:secret@database/explorer"
BLOCK_TIME = datetime(2026, 7, 25, 12, 30, 45, tzinfo=timezone.utc)


def summary(tx_type="gno.bank.MsgSend"):
    primary = {"type": tx_type, "category": "bank", "action": "send", "label": "Send Tokens"}
    return {
        "schema_version": 1,
        "chain_family": "gno",
        "parse_status": "parsed",
        "message_count": 1,
        "messages_truncated": False,
        "primary": primary,
        "messages": [{**primary, "sender": "g1sender", "internal_error": "secret"}],
        "decoder_error": "secret",
    }


def transaction_row(block_height, tx_index, **overrides):
    row = {
        "block_height": block_height,
        "tx_index": tx_index,
        "tx_hash_hex": f"{block_height * 100 + tx_index:064x}",
        "time_utc": BLOCK_TIME,
        "payload_summary": summary(),
        "raw_base64": "secret-raw",
        "decoded_bytes": b"secret-decoded",
        "execution_status": None,
        "gas_wanted": None,
        "gas_used": None,
        "error": None,
        "log": None,
        "info": None,
    }
    row.update(overrides)
    return row


class FakeDatabase:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []
        self.error = None
        self.details = {}

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_transactions(self, *, limit, before_height, before_tx_index):
        self.calls.append((limit, before_height, before_tx_index))
        if self.error:
            raise self.error
        rows = sorted(self.rows, key=lambda row: (row["block_height"], row["tx_index"]), reverse=True)
        if before_height is not None:
            rows = [
                row for row in rows
                if (row["block_height"], row["tx_index"]) < (before_height, before_tx_index)
            ]
        return rows[: limit + 1]

    def fetch_transaction_detail(self, height, index):
        return self.details.get((height, index))


class ApiTransactionsTests(unittest.TestCase):
    def make_client(self, database):
        from api import app as app_module

        database_patch = patch.object(app_module, "database", database)
        config_patch = patch.object(
            app_module,
            "load_config",
            return_value=ApiConfig(database_url=DATABASE_URL),
        )
        database_patch.start()
        config_patch.start()
        self.addCleanup(database_patch.stop)
        self.addCleanup(config_patch.stop)
        return TestClient(app_module.app)

    def test_first_page_is_newest_with_descending_composite_order(self):
        fake = FakeDatabase([
            transaction_row(9, 0), transaction_row(10, 0),
            transaction_row(10, 2), transaction_row(10, 1),
        ])
        with self.make_client(fake) as client:
            data = client.get("/api/transactions").json()
        self.assertEqual([(row["block_height"], row["index"]) for row in data["items"]], [
            (10, 2), (10, 1), (10, 0), (9, 0),
        ])
        self.assertEqual(fake.calls, [(20, None, None)])
        # Like Blocks API, the backend default stays 20; UI page size is client-controlled.
        self.assertEqual(data["pagination"]["limit"], 20)

    def test_composite_cursor_has_no_duplicates_or_gaps(self):
        fake = FakeDatabase([
            transaction_row(10, 2), transaction_row(10, 1), transaction_row(10, 0),
            transaction_row(9, 1), transaction_row(9, 0),
        ])
        with self.make_client(fake) as client:
            first = client.get("/api/transactions?limit=2").json()
            cursor = first["pagination"]
            second = client.get(
                "/api/transactions",
                params={
                    "limit": 3,
                    "before_height": cursor["next_before_height"],
                    "before_tx_index": cursor["next_before_tx_index"],
                },
            ).json()
        first_keys = [(row["block_height"], row["index"]) for row in first["items"]]
        second_keys = [(row["block_height"], row["index"]) for row in second["items"]]
        self.assertEqual(first_keys, [(10, 2), (10, 1)])
        self.assertEqual(second_keys, [(10, 0), (9, 1), (9, 0)])
        self.assertEqual(first_keys + second_keys, [(10, 2), (10, 1), (10, 0), (9, 1), (9, 0)])
        self.assertTrue(set(first_keys).isdisjoint(second_keys))
        self.assertEqual(cursor["next_before_height"], 10)
        self.assertEqual(cursor["next_before_tx_index"], 1)
        self.assertIsNone(second["pagination"]["next_before_height"])
        self.assertIsNone(second["pagination"]["next_before_tx_index"])

    def test_cursor_components_are_required_together(self):
        with self.make_client(FakeDatabase()) as client:
            height_only = client.get("/api/transactions?before_height=10")
            index_only = client.get("/api/transactions?before_tx_index=0")
        self.assertEqual(height_only.status_code, 422)
        self.assertEqual(index_only.status_code, 422)

    def test_limits_match_blocks_api(self):
        with self.make_client(FakeDatabase()) as client:
            self.assertEqual(client.get("/api/transactions?limit=0").status_code, 422)
            self.assertEqual(client.get("/api/transactions?limit=101").status_code, 422)
            self.assertEqual(client.get("/api/transactions?limit=25").status_code, 200)
            self.assertEqual(client.get("/api/transactions?limit=100").status_code, 200)

    def test_time_type_nullable_hash_and_private_fields(self):
        malformed = {"parse_status": "invalid", "internal_error": "do not expose"}
        fake = FakeDatabase([
            transaction_row(10, 1, tx_hash_hex=None),
            transaction_row(10, 0, payload_summary=malformed),
        ])
        with self.make_client(fake) as client:
            response = client.get("/api/transactions")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(items[0], {
            "block_height": 10,
            "index": 1,
            "tx_hash": None,
            "block_time": "2026-07-25T12:30:45Z",
            "type": "gno.bank.MsgSend",
            "operation": "Send Tokens",
            "execution_status": None,
            "gas_wanted": None,
            "gas_used": None,
            "error": None,
            "log": None,
            "info": None,
        })
        self.assertEqual(items[1]["type"], "unknown")
        self.assertEqual(items[1]["operation"], "Transaction")
        for private in ("raw_base64", "decoded_bytes", "payload_summary", "internal_error", "decoder_error"):
            self.assertNotIn(private, response.text)

    def test_execution_fields_are_propagated_and_private_fields_stay_hidden(self):
        fake = FakeDatabase([transaction_row(
            10, 0, execution_status="failed", gas_wanted="5000000",
            gas_used="934971", error="bounded failure", log="failed log", info="",
            raw_result={"private": True}, events=[{"private": True}],
            data_base64="cHJpdmF0ZQ==", source_rpc_endpoint_id=7,
        )])
        with self.make_client(fake) as client:
            response = client.get("/api/transactions")
        item = response.json()["items"][0]
        self.assertEqual({key: item[key] for key in (
            "execution_status", "gas_wanted", "gas_used", "error", "log", "info",
        )}, {
            "execution_status": "failed", "gas_wanted": "5000000",
            "gas_used": "934971", "error": "bounded failure",
            "log": "failed log", "info": "",
        })
        for private in ("raw_result", "events", "data_base64", "source_rpc_endpoint_id"):
            self.assertNotIn(private, item)
        self.assertNotIn({"private": True}, item.values())

    def test_database_failure_is_safe(self):
        fake = FakeDatabase()
        fake.error = RuntimeError(DATABASE_URL)
        with self.make_client(fake) as client:
            response = client.get("/api/transactions")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
        self.assertNotIn(DATABASE_URL, response.text)

    def test_sql_joins_blocks_and_uses_deterministic_cursor_order(self):
        normalized = " ".join(TRANSACTIONS_SQL.lower().split())
        self.assertIn("join blocks block on block.height = transaction.block_height", normalized)
        self.assertIn("order by transaction.block_height desc, transaction.tx_index desc", normalized)
        self.assertNotIn("count(", normalized)
        self.assertIn("%s::bigint is null", normalized)
        self.assertIn("transaction.block_height < %s::bigint", normalized)
        self.assertIn("transaction.block_height = %s::bigint", normalized)
        self.assertIn("transaction.tx_index < %s::integer", normalized)

    def test_missing_summary_uses_safe_type_and_operation_fallbacks(self):
        fake = FakeDatabase([transaction_row(10, 0, payload_summary=None)])
        with self.make_client(fake) as client:
            item = client.get("/api/transactions").json()["items"][0]
        self.assertEqual(item["type"], "unknown")
        self.assertEqual(item["operation"], "Transaction")


if __name__ == "__main__":
    unittest.main()
