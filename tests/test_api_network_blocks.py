import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import MissingIndexedBlockError, MissingIndexerStateError

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
BLOCK_HASH = "A" * 64
LOWER_HASH = "b" * 64
BASE64_HASH = "YWJjZA=="
BLOCK_TIME = datetime(2026, 7, 16, 13, 59, 50, tzinfo=timezone.utc)
RPC_CHECK_TIME = datetime(2026, 7, 16, 13, 59, 51, tzinfo=timezone.utc)


class FakeDatabase:
    def __init__(self):
        self.network_row = network_row()
        self.network_error = None
        self.blocks_rows = []
        self.blocks_error = None
        self.hash_rows = {}
        self.hash_error = None
        self.last_blocks_call = None
        self.last_hash_call = None
        self.open_count = 0
        self.close_count = 0

    def open(self, config):
        self.open_count += 1

    def close(self):
        self.close_count += 1

    def fetch_network_overview(self):
        if self.network_error is not None:
            raise self.network_error
        return self.network_row

    def fetch_blocks(self, *, limit, before_height):
        self.last_blocks_call = {"limit": limit, "before_height": before_height}
        if self.blocks_error is not None:
            raise self.blocks_error
        rows = sorted(self.blocks_rows, key=lambda row: row["height"], reverse=True)
        if before_height is not None:
            rows = [row for row in rows if row["height"] < before_height]
        return rows[: limit + 1]

    def fetch_block_by_hash(self, *, normalized_hex, block_hash_base64):
        self.last_hash_call = {
            "normalized_hex": normalized_hex,
            "block_hash_base64": block_hash_base64,
        }
        if self.hash_error is not None:
            raise self.hash_error
        key = normalized_hex if normalized_hex is not None else block_hash_base64
        return self.hash_rows.get(key)


def block_row(height=869383, block_hash_hex=BLOCK_HASH, **overrides):
    row = {
        "height": height,
        "block_hash_hex": block_hash_hex,
        "block_hash_base64": BASE64_HASH,
        "time_utc": BLOCK_TIME,
        "proposer_address": "g1proposer",
        "proposer_moniker": "UTSA",
        "tx_count": 0,
        "raw_block_response": {"secret": SECRET_URL},
        "inserted_at": BLOCK_TIME,
        "updated_at": BLOCK_TIME,
    }
    row.update(overrides)
    return row


def network_row(**overrides):
    row = {
        "chain_id": "test-13",
        "indexed_height": 869383,
        "finalized_tip_height": 869383,
        "block_height": 869383,
        "block_hash_hex": BLOCK_HASH,
        "time_utc": BLOCK_TIME,
        "proposer_address": "g1proposer",
        "proposer_moniker": "UTSA",
        "tx_count": 0,
        "validator_active_count": 20,
        "validator_total_voting_power": "123456789",
        "rpc_url": "https://example-rpc",
        "rpc_healthy": True,
        "rpc_catching_up": False,
        "rpc_observed_height": 869384,
        "rpc_lag": 0,
        "rpc_last_checked_at": RPC_CHECK_TIME,
    }
    row.update(overrides)
    return row


class ApiNetworkBlocksTests(unittest.TestCase):
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

    def test_network_successful_response_with_selected_rpc(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            response = client.get("/api/network")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "chain_id": "test-13",
                "rpc_height": 869384,
                "finalized_tip_height": 869383,
                "indexed_height": 869383,
                "indexer_lag": 0,
                "latest_block": {
                    "height": 869383,
                    "block_hash": BLOCK_HASH,
                    "time": "2026-07-16T13:59:50Z",
                    "proposer_address": "g1proposer",
                    "proposer_moniker": "UTSA",
                    "tx_count": 0,
                },
                "validators": {
                    "height": 869383,
                    "active_count": 20,
                    "total_voting_power": "123456789",
                },
                "selected_rpc": {
                    "url": "https://example-rpc",
                    "healthy": True,
                    "catching_up": False,
                    "observed_height": 869384,
                    "lag": 0,
                    "last_checked_at": "2026-07-16T13:59:51Z",
                },
            },
        )

    def test_network_voting_power_is_string_and_zero_validator_rows_are_zero(self):
        fake_database = FakeDatabase()
        fake_database.network_row = network_row(
            validator_active_count=0,
            validator_total_voting_power="0",
        )
        with self.make_client(fake_database) as client:
            data = client.get("/api/network").json()
        self.assertEqual(data["validators"]["active_count"], 0)
        self.assertEqual(data["validators"]["total_voting_power"], "0")
        self.assertIsInstance(data["validators"]["total_voting_power"], str)

    def test_network_selected_rpc_null_when_no_selected_endpoint_exists(self):
        fake_database = FakeDatabase()
        fake_database.network_row = network_row(
            rpc_url=None,
            rpc_healthy=None,
            rpc_catching_up=None,
            rpc_observed_height=None,
            rpc_lag=None,
            rpc_last_checked_at=None,
        )
        with self.make_client(fake_database) as client:
            data = client.get("/api/network").json()
        self.assertIsNone(data["selected_rpc"])
        self.assertIsNone(data["rpc_height"])

    def test_network_rpc_height_null_when_selected_rpc_has_no_observed_height(self):
        fake_database = FakeDatabase()
        fake_database.network_row = network_row(rpc_observed_height=None)
        with self.make_client(fake_database) as client:
            data = client.get("/api/network").json()
        self.assertIsNone(data["rpc_height"])
        self.assertIsNone(data["selected_rpc"]["observed_height"])

    def test_network_indexer_lag_calculation_and_null_tip(self):
        fake_database = FakeDatabase()
        fake_database.network_row = network_row(indexed_height=100, finalized_tip_height=111, block_height=100)
        with self.make_client(fake_database) as client:
            self.assertEqual(client.get("/api/network").json()["indexer_lag"], 11)
        fake_database.network_row = network_row(finalized_tip_height=None)
        with self.make_client(fake_database) as client:
            self.assertIsNone(client.get("/api/network").json()["indexer_lag"])

    def test_network_503_when_default_indexer_state_is_missing(self):
        fake_database = FakeDatabase()
        fake_database.network_error = MissingIndexerStateError("missing")
        with self.make_client(fake_database) as client:
            response = client.get("/api/network")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})

    def test_network_503_when_indexed_block_row_is_missing(self):
        fake_database = FakeDatabase()
        fake_database.network_error = MissingIndexedBlockError("missing")
        with self.make_client(fake_database) as client:
            response = client.get("/api/network")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})

    def test_network_503_on_query_exception_without_secrets_in_response_or_logs(self):
        fake_database = FakeDatabase()
        fake_database.network_error = RuntimeError(f"boom {SECRET_URL}")
        logger = logging.getLogger("api.app")
        with self.assertLogs(logger, level="ERROR") as captured:
            with self.make_client(fake_database) as client:
                response = client.get("/api/network")
        combined = response.text + "\n" + "\n".join(captured.output)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(SECRET_URL, combined)
        self.assertNotIn("super-secret-password", combined)
        self.assertNotIn("db.internal", combined)
        self.assertNotIn("api_user", combined)

    def test_blocks_default_limit_and_descending_order(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [block_row(height=1), block_row(height=3), block_row(height=2)]
        with self.make_client(fake_database) as client:
            response = client.get("/api/blocks")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["pagination"], {"limit": 20, "next_before_height": None})
        self.assertEqual([item["height"] for item in data["items"]], [3, 2, 1])
        self.assertEqual(fake_database.last_blocks_call, {"limit": 20, "before_height": None})

    def test_blocks_custom_valid_limit(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [block_row(height=3), block_row(height=2), block_row(height=1)]
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks?limit=2").json()
        self.assertEqual(data["pagination"]["limit"], 2)
        self.assertEqual([item["height"] for item in data["items"]], [3, 2])

    def test_blocks_invalid_limits_return_422(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            self.assertEqual(client.get("/api/blocks?limit=0").status_code, 422)
            self.assertEqual(client.get("/api/blocks?limit=101").status_code, 422)

    def test_blocks_before_height_is_exclusive(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [block_row(height=5), block_row(height=4), block_row(height=3)]
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks?before_height=5&limit=10").json()
        self.assertEqual([item["height"] for item in data["items"]], [4, 3])
        self.assertEqual(fake_database.last_blocks_call, {"limit": 10, "before_height": 5})

    def test_blocks_next_before_height_only_when_extra_row_exists(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [block_row(height=5), block_row(height=4), block_row(height=3)]
        with self.make_client(fake_database) as client:
            first_page = client.get("/api/blocks?limit=2").json()
            last_page = client.get("/api/blocks?before_height=4&limit=2").json()
        self.assertEqual(first_page["pagination"]["next_before_height"], 4)
        self.assertIsNone(last_page["pagination"]["next_before_height"])

    def test_blocks_empty_page(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks").json()
        self.assertEqual(data["items"], [])
        self.assertIsNone(data["pagination"]["next_before_height"])

    def test_blocks_exact_uppercase_hex_search(self):
        fake_database = FakeDatabase()
        fake_database.hash_rows[BLOCK_HASH] = block_row(block_hash_hex=BLOCK_HASH)
        with self.make_client(fake_database) as client:
            data = client.get(f"/api/blocks?hash={BLOCK_HASH}").json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(fake_database.last_hash_call["normalized_hex"], BLOCK_HASH)
        self.assertIsNone(data["pagination"]["next_before_height"])

    def test_blocks_lowercase_and_prefixed_hex_normalization(self):
        fake_database = FakeDatabase()
        normalized = LOWER_HASH.upper()
        fake_database.hash_rows[normalized] = block_row(block_hash_hex=normalized)
        with self.make_client(fake_database) as client:
            client.get(f"/api/blocks?hash={LOWER_HASH}")
            self.assertEqual(fake_database.last_hash_call["normalized_hex"], normalized)
            client.get(f"/api/blocks?hash=0x{LOWER_HASH}")
            self.assertEqual(fake_database.last_hash_call["normalized_hex"], normalized)
            client.get(f"/api/blocks?hash=0X{LOWER_HASH}")
            self.assertEqual(fake_database.last_hash_call["normalized_hex"], normalized)

    def test_blocks_exact_base64_search(self):
        fake_database = FakeDatabase()
        fake_database.hash_rows[BASE64_HASH] = block_row()
        with self.make_client(fake_database) as client:
            data = client.get(f"/api/blocks?hash={BASE64_HASH}").json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(fake_database.last_hash_call["block_hash_base64"], BASE64_HASH)

    def test_blocks_no_matching_hash_returns_empty_list(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks?hash=not-found").json()
        self.assertEqual(data["items"], [])
        self.assertIsNone(data["pagination"]["next_before_height"])

    def test_blocks_before_height_plus_hash_returns_422(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            response = client.get(f"/api/blocks?before_height=10&hash={BLOCK_HASH}")
        self.assertEqual(response.status_code, 422)

    def test_blocks_empty_whitespace_and_overly_long_hash_return_422(self):
        fake_database = FakeDatabase()
        with self.make_client(fake_database) as client:
            self.assertEqual(client.get("/api/blocks?hash=").status_code, 422)
            self.assertEqual(client.get("/api/blocks?hash=%20%20%20").status_code, 422)
            self.assertEqual(client.get("/api/blocks?hash=" + "a" * 201).status_code, 422)

    def test_blocks_503_on_query_exception(self):
        fake_database = FakeDatabase()
        fake_database.blocks_error = RuntimeError("boom")
        with self.make_client(fake_database) as client:
            response = client.get("/api/blocks")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})

    def test_block_proposer_moniker_preserves_match_and_fallbacks(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [
            block_row(height=3, proposer_moniker="UTSA"),
            block_row(height=2, proposer_moniker=None),
            block_row(height=1, proposer_address=None, proposer_moniker=None),
        ]
        with self.make_client(fake_database) as client:
            items = client.get("/api/blocks").json()["items"]
        self.assertEqual(items[0]["proposer_moniker"], "UTSA")
        self.assertEqual(items[0]["proposer_address"], "g1proposer")
        self.assertIsNone(items[1]["proposer_moniker"])
        self.assertIsNone(items[2]["proposer_moniker"])
        self.assertIsNone(items[2]["proposer_address"])

    def test_blocks_raw_database_fields_are_not_included(self):
        fake_database = FakeDatabase()
        fake_database.blocks_rows = [block_row()]
        with self.make_client(fake_database) as client:
            data = client.get("/api/blocks").json()
        item_text = str(data["items"][0])
        self.assertNotIn("block_hash_base64", item_text)
        self.assertNotIn("raw_block_response", item_text)
        self.assertNotIn("inserted_at", item_text)
        self.assertNotIn("updated_at", item_text)
        self.assertNotIn(SECRET_URL, item_text)


if __name__ == "__main__":
    unittest.main()
