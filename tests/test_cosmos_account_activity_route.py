import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.cosmos.account_routes import router
from api.cosmos.errors import AllEndpointsUnavailable


NETWORK = "atomone-mainnet"
ADDRESS = "atone1test"


class CosmosAccountActivityRouteTests(unittest.TestCase):
    def app(self):
        app = FastAPI()
        app.include_router(router)
        app.state.cosmos_services = {NETWORK: object()}
        return app

    def response(self):
        return {"state": "available", "items": [], "page": 1, "page_size": 10, "has_more": False}

    def test_success_uses_network_scoped_service_and_query(self):
        with patch("api.cosmos.account_routes.load_account_activity", new=AsyncMock(return_value=self.response())) as load:
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}/activity?limit=7&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["page_size"], 10)
        self.assertEqual(load.await_args.args[1:], (ADDRESS, 7, 2))

    def test_invalid_and_upstream_failures_are_safe(self):
        with patch("api.cosmos.account_routes.load_account_activity", new=AsyncMock(side_effect=ValueError("bad"))):
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}/activity")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid account activity request")

        with patch("api.cosmos.account_routes.load_account_activity", new=AsyncMock(side_effect=AllEndpointsUnavailable("secret"))):
            with TestClient(self.app()) as client:
                response = client.get(f"/api/networks/{NETWORK}/accounts/{ADDRESS}/activity")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)

    def test_main_api_app_mounts_activity_route(self):
        from api.app import app as main_app

        url = main_app.url_path_for(
            "get_cosmos_account_activity",
            network_id=NETWORK,
            address=ADDRESS,
        )
        self.assertEqual(str(url), f"/api/networks/{NETWORK}/accounts/{ADDRESS}/activity")


if __name__ == "__main__":
    unittest.main()
