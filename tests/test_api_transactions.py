import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.asset_classification import asset_classification_cache
from api.database import TRANSACTIONS_SQL
from api.transaction_semantics import semantic_transaction_operation


DATABASE_URL = "postgresql://api:secret@database/explorer"
BLOCK_TIME = datetime(2026, 7, 25, 12, 30, 45, tzinfo=timezone.utc)


def summary(tx_type="gno.bank.MsgSend", message_count=1):
    primary = {"type": tx_type, "category": "bank", "action": "send", "label": "Send Tokens"}
    return {
        "schema_version": 1,
        "chain_family": "gno",
        "parse_status": "parsed",
        "message_count": message_count,
        "messages_truncated": message_count > 1,
        "primary": primary,
        "messages": [{**primary, "sender": "g1sender", "internal_error": "secret"}],
        "decoder_error": "secret",
    }


def call_summary(path, function, *, later_messages=()):
    primary = {"type": "gno.vm.MsgCall", "category": "vm", "action": "call", "label": "Contract Call"}
    first = {**primary, "package_path": path, "function": function, "args_count": 1,
             "arguments": ["private"], "source": "private source"}
    messages = [first, *later_messages]
    return {
        "schema_version": 1, "chain_family": "gno", "parse_status": "parsed",
        "message_count": len(messages), "messages_truncated": False,
        "primary": primary, "messages": messages,
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
        self.asset_candidates = []
        self.asset_files = []
        self.asset_path_calls = []
        self.asset_file_calls = []

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

    def fetch_asset_candidates_for_paths(self, *, chain_id, paths):
        self.asset_path_calls.append((chain_id, paths))
        return [row for row in self.asset_candidates if row["path"] in paths]

    def fetch_asset_candidate_files(self, *, chain_id, paths):
        self.asset_file_calls.append((chain_id, paths))
        return [row for row in self.asset_files if row["path"] in paths]


class TransactionSemanticClassifierTests(unittest.TestCase):
    def test_exact_semantic_mapping(self):
        base = {
            "gno.bank.MsgSend": "Coin Transfer",
            "gno.vm.MsgAddPackage": "Deployment",
            "gno.vm.MsgRun": "Package Run",
        }
        for raw_type, expected in base.items():
            self.assertEqual(semantic_transaction_operation(raw_type, "old"), expected)
        mappings = {
            "grc721": {
                "Mint": "NFT Mint", "TransferFrom": "NFT Transfer",
                "SafeTransferFrom": "NFT Transfer", "Approve": "NFT Approval",
                "SetApprovalForAll": "NFT Approval", "Burn": "NFT Burn",
            },
            "grc20": {
                "Transfer": "GRC20 Transfer", "TransferFrom": "GRC20 Transfer",
                "Approve": "GRC20 Approval",
            },
        }
        for standard, functions in mappings.items():
            for function, expected in functions.items():
                self.assertEqual(semantic_transaction_operation(
                    "gno.vm.MsgCall", "Call", "gno.land/r/demo/asset", function, standard,
                ), expected)

    def test_unverified_and_inexact_calls_fail_closed(self):
        cases = [
            (None, "Mint"), ("grc20", "Mint"), ("grc721", "Transfer"),
            ("grc721", "mint"), ("grc721", "MintSpecial"), ("grc20", "Burn"),
        ]
        for standard, function in cases:
            self.assertEqual(semantic_transaction_operation(
                "gno.vm.MsgCall", "Call", "gno.land/r/demo/asset", function, standard,
            ), "Contract Call")
        self.assertEqual(semantic_transaction_operation(
            "gno.vm.MsgCall", "Call", None, "Mint", "grc721",
        ), "Contract Call")


class ApiTransactionsTests(unittest.TestCase):
    def setUp(self):
        asset_classification_cache.clear()

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

    def test_verified_failed_nft_mint_is_batched_and_private_data_stays_hidden(self):
        path = "gno.land/r/demo/art"
        fake = FakeDatabase([
            transaction_row(10, 1, payload_summary=call_summary(path, "Mint"), execution_status="failed"),
            transaction_row(10, 0, payload_summary=call_summary(path, "Burn")),
        ])
        fake.asset_candidates = [{
            "path": path, "standard": "grc721", "metadata_observed_height": 9,
            "qfunc_names": ["OwnerOf", "TransferFrom", "Mint", "Burn"],
        }]
        fake.asset_files = [{
            "path": path, "filename": "main.gno", "file_kind": "gno_source",
            "metadata_observed_height": 9,
            "content": 'import "gno.land/p/vendor/grc721"\nvar nft=grc721.NewBasicNFT(0, cur, "Art", "ART")\nfunc OwnerOf() {}\nfunc Mint() {}',
        }]
        with self.make_client(fake) as client:
            response = client.get("/api/transactions")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual((items[0]["type"], items[0]["operation"], items[0]["execution_status"]),
                         ("gno.vm.MsgCall", "NFT Mint", "failed"))
        self.assertEqual(items[1]["operation"], "NFT Burn")
        self.assertEqual(fake.asset_path_calls, [("pearl-1", [path])])
        self.assertEqual(fake.asset_file_calls, [("pearl-1", [path])])
        for private in ("payload_summary", "arguments", "source", "private source"):
            self.assertNotIn(private, response.text)

    def test_primary_message_only_and_classification_failure_fall_back(self):
        path = "gno.land/r/demo/art"
        later = {"type": "gno.vm.MsgCall", "category": "vm", "action": "call",
                 "label": "Contract Call", "package_path": path, "function": "Mint"}
        payload = summary(message_count=2)
        payload["messages"].append(later)
        fake = FakeDatabase([transaction_row(10, 1, payload_summary=payload),
                             transaction_row(10, 0, payload_summary=call_summary(path, "Mint"))])
        fake.asset_candidates = [{"path": path, "standard": "grc721",
                                  "metadata_observed_height": 9, "qfunc_names": []}]
        fake.fetch_asset_candidate_files = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("source failure"))
        with self.make_client(fake) as client:
            items = client.get("/api/transactions").json()["items"]
        self.assertEqual(items[0]["operation"], "Coin Transfer")
        self.assertEqual(items[1]["operation"], "Contract Call")

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
            "operation": "Coin Transfer",
            "message_count": 1,
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
        self.assertIsNone(item["message_count"])

    def test_message_count_comes_from_validated_public_summary(self):
        fake = FakeDatabase([
            transaction_row(10, 1, payload_summary=summary(message_count=7)),
            transaction_row(10, 0, payload_summary=summary(message_count=1)),
        ])
        with self.make_client(fake) as client:
            items = client.get("/api/transactions").json()["items"]
        self.assertEqual([item["message_count"] for item in items], [7, 1])

    def test_malformed_summary_does_not_expose_unsafe_message_count(self):
        malformed = summary(message_count=7)
        malformed["message_count"] = "7"
        with self.make_client(FakeDatabase([
            transaction_row(10, 0, payload_summary=malformed),
        ])) as client:
            item = client.get("/api/transactions").json()["items"][0]
        self.assertIsNone(item["message_count"])
        self.assertEqual((item["type"], item["operation"]), ("unknown", "Transaction"))


if __name__ == "__main__":
    unittest.main()
