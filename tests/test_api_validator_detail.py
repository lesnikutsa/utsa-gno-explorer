import logging
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.database import MissingIndexedBlockError, MissingIndexerStateError

SECRET_URL = "postgresql://api_user:super-secret-password@db.internal:5432/explorer"
ADDRESS = "g15sysd4jcpsw7t0n4ffe2hn8ndfup2ae2vwpves"


def history_row(height, membership=True, signature=True, signed=False, vote_status="absent"):
    return {
        "height": height,
        "time_utc": datetime(2026, 7, 16, 14, 30, height % 60, tzinfo=timezone.utc),
        "membership_address": ADDRESS if membership else None,
        "signature_address": ADDRESS if signature else None,
        "signed": signed,
        "vote_status": vote_status,
    }


def detail_result(*, power=Decimal("10"), total=Decimal("138"), history=None):
    return {
        "identity": {
            "address": ADDRESS,
            "public_key_type": "tendermint/PubKeyEd25519",
            "public_key_value": "base64 consensus public key",
            "first_seen_height": 850000,
            "last_seen_height": 870687,
        },
        "current": {
            "height": 870687,
            "block_exists": True,
            "voting_power": power,
            "proposer_priority": Decimal("-1234") if power is not None else None,
            "total_voting_power": total,
        },
        "history": history if history is not None else [history_row(870687, signed=True)],
    }


class FakeDatabase:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def open(self, config):
        pass

    def close(self):
        pass

    def fetch_validator_detail(self, address):
        if self.error is not None:
            raise self.error
        return self.result


class ApiValidatorDetailTests(unittest.TestCase):
    def make_client(self, database):
        from api import app as app_module

        patches = [
            patch.object(app_module, "database", database),
            patch.object(app_module, "load_config", return_value=ApiConfig(database_url=SECRET_URL)),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        return TestClient(app_module.app)

    def get(self, result=None, error=None, address=ADDRESS):
        with self.make_client(FakeDatabase(result, error)) as client:
            return client.get(f"/api/validators/{address}")

    def test_active_validator_identity_and_current_values(self):
        response = self.get(detail_result())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["address"], ADDRESS)
        self.assertEqual(data["public_key_type"], "tendermint/PubKeyEd25519")
        self.assertEqual(data["public_key_value"], "base64 consensus public key")
        self.assertEqual((data["first_seen_height"], data["last_seen_height"]), (850000, 870687))
        self.assertEqual(data["current"], {
            "active": True, "height": 870687, "voting_power": "10",
            "voting_power_percent": 7.25, "proposer_priority": "-1234",
        })

    def test_inactive_historical_validator_has_empty_current_fields(self):
        data = self.get(detail_result(power=None)).json()
        self.assertEqual(data["current"], {
            "active": False, "height": 870687, "voting_power": None,
            "voting_power_percent": 0.0, "proposer_priority": None,
        })

    def test_zero_total_power_has_zero_percent(self):
        data = self.get(detail_result(total=Decimal(0))).json()
        self.assertEqual(data["current"]["voting_power_percent"], 0.0)

    def test_history_classification_precedence_order_gaps_and_envelope(self):
        rows = [
            history_row(10, membership=False, signature=False, signed=True, vote_status="nil"),
            history_row(12, signature=False),
            history_row(15, signed=True, vote_status="invalid"),
            history_row(18, vote_status="nil"),
            history_row(21, vote_status="absent"),
            history_row(25, vote_status="invalid"),
            history_row(30, vote_status="unexpected"),
        ]
        data = self.get(detail_result(history=rows)).json()["signing_history"]
        self.assertEqual([item["height"] for item in data["items"]], [10, 12, 15, 18, 21, 25, 30])
        self.assertEqual([item["status"] for item in data["items"]],
                         ["not_active", "unknown", "commit", "nil", "absent", "invalid", "unknown"])
        self.assertEqual((data["network_blocks"], data["start_height"], data["end_height"]), (7, 10, 30))
        self.assertTrue(all(item["time"].endswith("Z") for item in data["items"]))

    def test_uptime_windows_membership_unknown_rounding_and_invariant(self):
        rows = []
        for height in range(1, 26):
            if height <= 5:
                rows.append(history_row(height, signed=True))
            elif height == 6:
                rows.append(history_row(height, membership=False, signature=False))
            elif height == 7:
                rows.append(history_row(height, signature=False))
            else:
                rows.append(history_row(height, signed=(height % 3 == 0)))
        data = self.get(detail_result(history=rows)).json()
        self.assertEqual(data["uptime_20"]["network_blocks"], 20)
        self.assertEqual(data["uptime_100"]["network_blocks"], 25)
        self.assertEqual(data["uptime_20"]["active_blocks"], 19)
        self.assertEqual(data["uptime_20"]["unknown_blocks"], 1)
        self.assertEqual(data["uptime_20"]["uptime_percent"], 31.58)
        for name in ("uptime_20", "uptime_100"):
            uptime = data[name]
            classified = sum(uptime[key] for key in (
                "signed_blocks", "nil_blocks", "absent_blocks", "invalid_blocks", "unknown_blocks"
            ))
            self.assertEqual(uptime["active_blocks"], classified)

    def test_zero_active_blocks(self):
        rows = [history_row(height, membership=False, signature=False) for height in (4, 8)]
        uptime = self.get(detail_result(history=rows)).json()["uptime_100"]
        self.assertEqual(uptime["active_blocks"], 0)
        self.assertEqual(uptime["uptime_percent"], 0.0)

    def test_empty_history_is_defensive(self):
        history = self.get(detail_result(history=[])).json()["signing_history"]
        self.assertEqual(history, {"network_blocks": 0, "start_height": None, "end_height": None, "items": []})

    def test_unknown_exact_address_returns_404(self):
        response = self.get(None)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Validator not found"})

    def test_path_length_validation(self):
        response = self.get(detail_result(), address="x" * 129)
        self.assertEqual(response.status_code, 422)
        with self.make_client(FakeDatabase(detail_result())) as client:
            empty_equivalent = client.get("/api/validators/")
        self.assertNotEqual(empty_equivalent.status_code, 200)

    def test_consistency_and_query_errors_are_safe(self):
        for error in (MissingIndexerStateError(), MissingIndexedBlockError(), RuntimeError(SECRET_URL)):
            with self.subTest(error=type(error).__name__):
                with self.assertLogs(logging.getLogger("api.app"), level="ERROR") as captured:
                    response = self.get(error=error)
                combined = response.text + "\n".join(captured.output)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
                for secret in (SECRET_URL, "super-secret-password", "db.internal"):
                    self.assertNotIn(secret, combined)

    def test_forbidden_fields_are_not_exposed(self):
        result = detail_result()
        result["identity"].update({"moniker": "secret", "inserted_at": "secret", "operator_address": "secret"})
        result["history"][0].update({"signature_base64": "secret", "raw_precommit": "secret"})
        text = self.get(result).text
        for field in ("moniker", "inserted_at", "operator_address", "signature_base64", "raw_precommit", "vote_status", "signed"):
            self.assertNotIn(field, text)

    def test_sql_is_bounded_parameterized_and_chronological(self):
        from api.database import VALIDATOR_CURRENT_SQL, VALIDATOR_HISTORY_SQL, VALIDATOR_IDENTITY_SQL

        self.assertIn("WHERE signing_address = %s", VALIDATOR_IDENTITY_SQL)
        self.assertIn("s.last_finalized_height", VALIDATOR_CURRENT_SQL)
        self.assertIn("LIMIT 100", VALIDATOR_HISTORY_SQL)
        self.assertIn("ORDER BY recent.height ASC", VALIDATOR_HISTORY_SQL)
        self.assertNotIn("max(", VALIDATOR_HISTORY_SQL.lower())


if __name__ == "__main__":
    unittest.main()
