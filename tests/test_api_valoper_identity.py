import unittest
from datetime import datetime, timezone
from decimal import Decimal

from api.app import _validator_detail_from_rows, _validators_response_from_rows
from api.database import ACTIVE_VALIDATORS_SQL, VALIDATOR_IDENTITY_SQL
from api.schemas import ValidatorDetailResponse, ValidatorListItem

ADDRESS = "g1" + "2" * 38
OPERATOR = "g1" + "3" * 38
SIGNING_PUBKEY = "gpub1pgfj7ard9eg4da6pv7dy4r3v9g3h8j4qj6c8uw"


def active_row(address=ADDRESS, **profile):
    row = {
        "address": address, "public_key_type": "/tm.PubKeyEd25519",
        "voting_power": Decimal("10"), "proposer_priority": Decimal("-2"),
        "active_blocks_20": 1, "signed_blocks_20": 1, "nil_blocks_20": 0,
        "absent_blocks_20": 0, "invalid_blocks_20": 0, "unknown_blocks_20": 0,
        "active_blocks_100": 1, "signed_blocks_100": 1, "nil_blocks_100": 0,
        "absent_blocks_100": 0, "invalid_blocks_100": 0, "unknown_blocks_100": 0,
        "moniker": None, "operator_address": None, "server_type": None,
        "valoper_source_height": None,
    }
    row.update(profile)
    return row


def detail(profile):
    identity = {
        "address": ADDRESS, "public_key_type": "/tm.PubKeyEd25519", "public_key_value": "key",
        "first_seen_height": 1, "last_seen_height": 2, "moniker": None,
        "operator_address": None, "description": None, "server_type": None,
        "valoper_source_height": None,
    }
    identity.update(profile)
    return _validator_detail_from_rows({
        "identity": identity,
        "current": {"height": 2, "block_exists": True, "voting_power": Decimal("10"),
                    "proposer_priority": Decimal("0"), "total_voting_power": Decimal("10")},
        "history": [{"height": 2, "time_utc": datetime(2026, 1, 1, tzinfo=timezone.utc),
                     "membership_address": ADDRESS, "signature_address": ADDRESS,
                     "signed": True, "vote_status": "commit"}],
    })


class ValoperIdentityTests(unittest.TestCase):
    def test_list_matched_unmatched_preserves_order_power_and_uptime(self):
        rows = [active_row(moniker="Official", operator_address=OPERATOR,
                           server_type="cloud", valoper_source_height=947852,
                           signing_pubkey="hidden", description="hidden", inserted_at="hidden"),
                active_row("g1" + "4" * 38, voting_power=Decimal("5"))]
        response = _validators_response_from_rows({
            "checkpoint": {"height": 2, "network_blocks_20": 1, "network_blocks_100": 1},
            "items": rows,
        })
        data = response.model_dump()
        self.assertEqual([item["address"] for item in data["items"]], [row["address"] for row in rows])
        self.assertEqual(data["total_voting_power"], "15")
        self.assertEqual(data["items"][0]["moniker"], "Official")
        self.assertEqual(data["items"][0]["operator_address"], OPERATOR)
        self.assertEqual(data["items"][0]["server_type"], "cloud")
        self.assertEqual(data["items"][0]["valoper_source_height"], 947852)
        self.assertEqual(data["items"][0]["voting_power"], "10")
        self.assertEqual(data["items"][0]["uptime_20"]["uptime_percent"], 100.0)
        for key in ("moniker", "operator_address", "server_type", "valoper_source_height"):
            self.assertIsNone(data["items"][1][key])
        self.assertTrue({"signing_pubkey", "description", "inserted_at", "updated_at"}.isdisjoint(data["items"][0]))
        self.assertIsInstance(response.items[0], ValidatorListItem)

    def test_detail_matched_and_unmatched_preserve_consensus_state(self):
        matched = detail({"moniker": "Official", "operator_address": OPERATOR,
                          "description": "Profile", "server_type": "data-center",
                          "valoper_source_height": 947852, "signing_pubkey": SIGNING_PUBKEY,
                          "list_position": 1, "updated_at": "hidden"}).model_dump()
        self.assertEqual([matched[k] for k in ("moniker", "operator_address", "description", "server_type", "valoper_source_height")],
                         ["Official", OPERATOR, "Profile", "data-center", 947852])
        self.assertTrue(matched["current"]["active"])
        self.assertEqual(matched["signing_pubkey"], SIGNING_PUBKEY)
        self.assertEqual(matched["uptime_100"]["uptime_percent"], 100.0)
        self.assertEqual(matched["signing_history"]["items"][0]["status"], "commit")
        self.assertTrue({"list_position", "inserted_at", "updated_at"}.isdisjoint(matched))
        unmatched = detail({})
        self.assertIsInstance(unmatched, ValidatorDetailResponse)
        self.assertIsNone(unmatched.signing_pubkey)
        for key in ("moniker", "operator_address", "description", "server_type", "valoper_source_height"):
            self.assertIsNone(getattr(unmatched, key))

    def test_sql_exact_left_join_contract(self):
        active = " ".join(ACTIVE_VALIDATORS_SQL.lower().split())
        identity = " ".join(VALIDATOR_IDENTITY_SQL.lower().split())
        self.assertIn("left join valoper_profiles profile on profile.signing_address = current.signing_address", active)
        self.assertIn("order by current.voting_power desc, current.signing_address asc", active)
        self.assertIn("profile.moniker, profile.operator_address, profile.server_type, profile.source_height", active.split("group by", 1)[1])
        self.assertIn("from validators validator left join valoper_profiles profile", identity)
        self.assertIn("profile.signing_address = validator.signing_address", identity)
        self.assertIn("where validator.signing_address = %s", identity)
        self.assertIn("profile.signing_pubkey", identity)
        self.assertNotIn("profile.signing_pubkey", active)
        for sql in (active, identity):
            self.assertNotIn("valopers_snapshot_state", sql)
            self.assertNotIn("profile.moniker =", sql)
            self.assertNotIn("profile.operator_address =", sql)


if __name__ == "__main__":
    unittest.main()
