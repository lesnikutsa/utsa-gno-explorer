import base64
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from api.cosmos.account_detail import load_account_snapshot
from api.cosmos.registry import ATOMONE
from api.cosmos.service import consensus_address, reencode_bech32_address


ACCOUNT = consensus_address({"key": base64.b64encode(bytes(range(32))).decode()}, "atone")
OPERATOR = reencode_bech32_address(ACCOUNT, "atone", "atonevaloper")


class FakeCache:
    async def get_or_load(self, _key, _ttl, loader):
        return await loader()


class FakeService:
    def __init__(self, payloads):
        self.definition = ATOMONE
        self._payloads = payloads
        self._wall_clock = lambda: datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)
        self._rest = AsyncMock(side_effect=self._rest_value)
        self.cache = FakeCache()
        self._all_validators = AsyncMock(return_value=[{
            "operator_address": OPERATOR,
            "status": "BOND_STATUS_BONDED",
            "jailed": False,
            "description": {"moniker": "UTSA", "identity": ""},
        }])

    async def _rest_value(self, name, _path):
        value = self._payloads[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def _avatar(self, _identity):
        return None


def payloads():
    return {
        "account_auth": {"account": {"@type": "/cosmos.auth.v1beta1.BaseAccount", "address": ACCOUNT,
            "pub_key": {"@type": "/cosmos.crypto.secp256k1.PubKey", "key": base64.b64encode(b"key").decode()},
            "account_number": "12", "sequence": "7"}},
        "account_balances": {"balances": [
            {"denom": "uatone", "amount": "12500000"}, {"denom": "uphoton", "amount": "4200000"}],
            "pagination": {"next_key": None}},
        "account_delegations": {"delegation_responses": [{
            "delegation": {"delegator_address": ACCOUNT, "validator_address": OPERATOR,
                           "shares": "8000000.000000000000000000"},
            "balance": {"denom": "uatone", "amount": "8000000"}}],
            "pagination": {"next_key": None}},
        "account_unbonding": {"unbonding_responses": [{
            "delegator_address": ACCOUNT, "validator_address": OPERATOR,
            "entries": [{"creation_height": "100", "completion_time": "2026-09-05T18:00:00Z",
                         "initial_balance": "500000", "balance": "450000"}]}],
            "pagination": {"next_key": None}},
        "account_rewards": {"rewards": [{"validator_address": OPERATOR, "reward": [
            {"denom": "uatone", "amount": "42170000.125000000000000000"},
            {"denom": "uphoton", "amount": "10.500000000000000000"}]}],
            "total": [{"denom": "uatone", "amount": "42170000.125000000000000000"},
                      {"denom": "uphoton", "amount": "10.500000000000000000"}]},
        "account_withdraw_address": {"withdraw_address": ACCOUNT},
        "account_staking_params": {"params": {"bond_denom": "uatone"}},
    }


class CosmosAccountDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_multi_asset_account_snapshot(self):
        service = FakeService(payloads())
        result = await load_account_snapshot(service, ACCOUNT)

        self.assertTrue(result["exists"])
        self.assertEqual((result["account_number"], result["sequence"]), (12, 7))
        self.assertEqual(result["balances"], [
            {"denom": "uatone", "amount": "12500000"},
            {"denom": "uphoton", "amount": "4200000"},
        ])
        self.assertFalse(result["balances_truncated"])
        self.assertEqual(result["bond_denom"], "uatone")
        self.assertEqual(result["delegated_total"], [{"denom": "uatone", "amount": "8000000"}])
        self.assertEqual(result["delegations"][0]["validator"]["moniker"], "UTSA")
        self.assertEqual(result["delegations"][0]["rewards"][0]["amount"], "42170000.125")
        self.assertEqual(result["rewards_total"][1], {"denom": "uphoton", "amount": "10.5"})
        self.assertEqual(result["rewards_by_validator"][0]["validator"]["moniker"], "UTSA")
        self.assertEqual(result["unbonding"][0]["denom"], "uatone")
        self.assertEqual(result["unbonding"][0]["entries"][0]["remaining_seconds"], 86400)
        self.assertEqual(result["withdraw_address"], ACCOUNT)
        self.assertEqual(result["validator_relation"]["operator_address"], OPERATOR)
        self.assertEqual(set(result["states"].values()), {"available"})

    async def test_optional_sections_degrade_without_hiding_balances(self):
        values = payloads()
        values["account_rewards"] = RuntimeError("unsupported")
        values["account_unbonding"] = RuntimeError("unsupported")
        service = FakeService(values)
        result = await load_account_snapshot(service, ACCOUNT)

        self.assertEqual(result["states"]["rewards"], "unavailable")
        self.assertEqual(result["states"]["unbonding"], "unavailable")
        self.assertEqual(result["rewards_total"], [])
        self.assertEqual(result["rewards_by_validator"], [])
        self.assertEqual(result["unbonding"], [])
        self.assertEqual(result["balances"][0]["denom"], "uatone")

    async def test_empty_valid_account_is_not_an_error(self):
        values = payloads()
        values["account_auth"] = RuntimeError("not found")
        values["account_balances"] = {"balances": [], "pagination": {"next_key": None}}
        values["account_delegations"] = {"delegation_responses": [], "pagination": {"next_key": None}}
        values["account_unbonding"] = {"unbonding_responses": [], "pagination": {"next_key": None}}
        values["account_rewards"] = {"rewards": [], "total": []}
        service = FakeService(values)
        result = await load_account_snapshot(service, ACCOUNT)

        self.assertFalse(result["exists"])
        self.assertIsNone(result["account_number"])
        self.assertEqual(result["states"]["auth"], "unavailable")

    async def test_marks_bounded_bank_page_as_truncated(self):
        values = payloads()
        values["account_balances"]["pagination"]["next_key"] = "next"
        service = FakeService(values)
        result = await load_account_snapshot(service, ACCOUNT)
        self.assertTrue(result["balances_truncated"])

    async def test_rejects_invalid_account_prefix(self):
        service = FakeService(payloads())
        with self.assertRaises(ValueError):
            await load_account_snapshot(service, "cosmos1invalid")


if __name__ == "__main__":
    unittest.main()
