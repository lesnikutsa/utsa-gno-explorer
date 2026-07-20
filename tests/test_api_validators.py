import logging
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import MissingIndexedBlockError, MissingIndexerStateError

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"


def validator(address, voting_power, priority, active_20=3, signed_20=2, **overrides):
    row = {
        "address": address,
        "public_key_type": "tendermint/PubKeyEd25519",
        "voting_power": Decimal(voting_power),
        "proposer_priority": None if priority is None else Decimal(priority),
        "active_blocks_20": active_20,
        "signed_blocks_20": signed_20,
        "nil_blocks_20": 0,
        "absent_blocks_20": 0,
        "invalid_blocks_20": 0,
        "unknown_blocks_20": active_20 - signed_20,
        "active_blocks_100": 3,
        "signed_blocks_100": 2,
        "nil_blocks_100": 0,
        "absent_blocks_100": 1,
        "invalid_blocks_100": 0,
        "unknown_blocks_100": 0,
        "public_key_value": "forbidden",
        "moniker": None,
        "operator_address": None,
        "server_type": None,
        "valoper_source_height": None,
    }
    row.update(overrides)
    return row


class FakeDatabase:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_active_validators(self):
        if self.error is not None:
            raise self.error
        return self.result


class ApiValidatorsTests(unittest.TestCase):
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

    def result(self, items):
        return {
            "checkpoint": {"height": 870394, "network_blocks_20": 3, "network_blocks_100": 3},
            "items": items,
        }

    def test_successful_response_serializes_values_uptime_and_safe_fields(self):
        rows = [
            validator("g1a", "3", "-1234", active_20=3, signed_20=2, moniker="Official", operator_address="g1operator", server_type="cloud", valoper_source_height=947852),
            validator("g1b", "1", None, active_20=0, signed_20=0),
        ]
        with self.make_client(FakeDatabase(self.result(rows))) as client:
            response = client.get("/api/validators")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["height"], 870394)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["total_voting_power"], "4")
        self.assertEqual(data["items"][0]["voting_power"], "3")
        self.assertEqual(data["items"][0]["percent"], 75.0)
        self.assertEqual(data["items"][0]["proposer_priority"], "-1234")
        self.assertIsNone(data["items"][1]["proposer_priority"])
        self.assertEqual(data["items"][0]["uptime_20"]["network_blocks"], 3)
        self.assertEqual(data["items"][0]["uptime_20"]["uptime_percent"], 66.67)
        self.assertEqual(data["items"][1]["uptime_20"]["uptime_percent"], 0.0)
        self.assertEqual(data["items"][0]["uptime_100"]["uptime_percent"], 66.67)
        self.assertEqual(data["items"][0]["uptime_100"]["absent_blocks"], 1)
        self.assertEqual(data["items"][0]["uptime_20"]["unknown_blocks"], 1)
        self.assertNotIn("public_key_value", response.text)
        self.assertEqual(data["items"][0]["moniker"], "Official")
        self.assertEqual(data["items"][0]["operator_address"], "g1operator")
        self.assertEqual(data["items"][0]["server_type"], "cloud")
        self.assertEqual(data["items"][0]["valoper_source_height"], 947852)
        self.assertIsNone(data["items"][1]["moniker"])

    def test_zero_power_and_empty_set(self):
        with self.make_client(FakeDatabase(self.result([validator("g1zero", "0", None)]))) as client:
            data = client.get("/api/validators").json()
        self.assertEqual(data["total_voting_power"], "0")
        self.assertEqual(data["items"][0]["percent"], 0.0)
        with self.make_client(FakeDatabase(self.result([]))) as client:
            data = client.get("/api/validators").json()
        self.assertEqual(data, {"height": 870394, "total": 0, "total_voting_power": "0", "items": []})

    def test_database_consistency_errors_return_safe_503(self):
        for error in (MissingIndexerStateError(), MissingIndexedBlockError(), RuntimeError(SECRET_URL)):
            with self.subTest(error=type(error).__name__):
                logger = logging.getLogger("api.app")
                with self.assertLogs(logger, level="ERROR") as captured:
                    with self.make_client(FakeDatabase(error=error)) as client:
                        response = client.get("/api/validators")
                combined = response.text + "\n".join(captured.output)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
                self.assertNotIn(SECRET_URL, combined)
                self.assertNotIn("super-secret-password", combined)
                self.assertNotIn("db.internal", combined)

    def test_database_query_orders_by_power_then_address(self):
        from api.database import ACTIVE_VALIDATORS_SQL

        self.assertIn("ORDER BY current.voting_power DESC, current.signing_address ASC", ACTIVE_VALIDATORS_SQL)


if __name__ == "__main__":
    unittest.main()
