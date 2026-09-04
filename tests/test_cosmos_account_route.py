import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.cosmos.account_routes import router
from api.cosmos.errors import AllEndpointsUnavailable


NETWORK = "atomone-mainnet"
ADDRESS = "atone1test"


class CosmosAccountRouteTests(unittest.TestCase):
    def app(self):
        app = FastAPI()
        app.include_router(router)
        app.state.cosmos_services = {NETWORK: object()}
        return app

    def snapshot(self):
        return {
            "network_id": NETWORK,
            "address": ADDRESS,
            "exists": True,
            "account_type": "/cosmos.auth.v1beta1.BaseAccount",
            "account_number": 1,
            "sequence": 2,
            "public_key": None,
            "bond_denom": "uatone",
            "balances": [{"denom": "uatone", "amount": "10"}],
            "balances_truncated": False,
            "delegated_total": [],
            "rewards_total": [],
            "rewards_by_validator": [],
            "delegations": [],
            "delegations_truncated": False,
            "unbonding": [],
            "unbonding_truncated": False,
            "withdraw_address": None,
            "validator_relation": None,
            "states": {name: "available" for name in (
                "auth", "bank", "staking", "unbonding", "rewards", "withdraw_address")},
        }

    def test_success_uses_network_scoped_service(self):
        with patch("api.cosmos.account_routes.load_account_snapshot", new=AsyncMock(return_value=self.snapshot())) as load:
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balances"][0]["denom"], "uatone")
        self.assertEqual(load.await_args.args[1], ADDRESS)

    def test_unknown_network_is_404(self):
        with TestClient(self.app()) as client:
            response = client.get(f"/api/networks/unknown-network/accounts/{ADDRESS}")
        self.assertEqual(response.status_code, 404)

    def test_invalid_address_is_400(self):
        with patch("api.cosmos.account_routes.load_account_snapshot", new=AsyncMock(side_effect=ValueError("invalid"))):
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid account address")

    def test_upstream_failure_is_safe_503(self):
        with patch("api.cosmos.account_routes.load_account_snapshot", new=AsyncMock(side_effect=AllEndpointsUnavailable("secret"))):
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Account data is temporarily unavailable")
        self.assertNotIn("secret", response.text)


if __name__ == "__main__":
    unittest.main()
