import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.cosmos import RequestCache
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService


def validator(operator_address, moniker):
    return {"operator_address": operator_address, "description": {"moniker": moniker}}


class FakeDatabase:
    def open(self, _config):
        pass

    def close(self):
        pass


class CosmosValidatorSearchServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient()
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())
        prefix = ATOMONE.validator_operator_prefix + "1"
        self.rows = [
            validator(prefix + "exact", "Other"),
            validator(prefix + "alpha", "UTSA"),
            validator(prefix + "bravo", "utsa"),
            validator(prefix + "charlie", "UTSA Labs"),
            validator(prefix + "delta", "The UTSA Node"),
            validator(prefix + "echo", "UTSA Alpha"),
            validator(prefix + "foxtrot", "UTSA Beta"),
            validator(prefix + "golf", "UTSA Gamma"),
            validator("differentvaloper1ignored", "UTSA Foreign"),
        ]
        self.service._all_validators = AsyncMock(return_value=self.rows)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_matching_ranking_order_and_schema(self):
        operator = self.rows[0]["operator_address"]
        exact_operator = await self.service.search_validators(operator)
        self.assertEqual(exact_operator, {"items": [{"moniker": "Other", "operator_address": operator}]})

        results = (await self.service.search_validators("utsa"))["items"]
        self.assertEqual([item["moniker"] for item in results[:2]], ["UTSA", "utsa"])
        self.assertEqual([item["moniker"] for item in results[2:]],
                         ["UTSA Alpha", "UTSA Beta", "UTSA Gamma", "UTSA Labs"])
        self.assertEqual(set(results[0]), {"moniker", "operator_address"})

        substring = await self.service.search_validators("tsa n")
        self.assertEqual([item["moniker"] for item in substring["items"]], ["The UTSA Node"])

    async def test_limit_bounds_cache_and_network_prefix_isolation(self):
        results = await self.service.search_validators("utsa", limit=3)
        self.assertEqual(len(results["items"]), 3)
        await self.service.search_validators("UTSA", limit=2)
        self.service._all_validators.assert_awaited_once()
        self.assertNotIn("UTSA Foreign", [item["moniker"] for item in results["items"]])
        for query in ("", " spaced ", "x" * 129):
            with self.assertRaises(ValueError):
                await self.service.search_validators(query)
        for limit in (0, 7):
            with self.assertRaises(ValueError):
                await self.service.search_validators("utsa", limit)


class CosmosValidatorSearchRouteTests(unittest.TestCase):
    def setUp(self):
        from api import app as module
        self.module = module
        self.patches = [
            patch.object(module, "database", FakeDatabase()),
            patch.object(module, "load_config", return_value=ApiConfig("postgresql://test")),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_route_contract_bounds_invalid_network_and_service_isolation(self):
        payload = {"items": [{"moniker": "UTSA", "operator_address": "atonevaloper1validator"}]}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.search_validators = AsyncMock(return_value=payload)
            with patch.object(self.module.database, "search_validators", create=True) as gno_search:
                response = client.get("/api/networks/atomone-mainnet/search/validators?q=UTSA&limit=6")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), payload)
                service.search_validators.assert_awaited_once_with("UTSA", 6)
                gno_search.assert_not_called()
            self.assertEqual(client.get("/api/networks/unknown/search/validators?q=UTSA").status_code, 404)
            for path in (
                "/api/networks/atomone-mainnet/search/validators",
                "/api/networks/atomone-mainnet/search/validators?q=%20UTSA%20",
                f"/api/networks/atomone-mainnet/search/validators?q={'x' * 129}",
                "/api/networks/atomone-mainnet/search/validators?q=UTSA&limit=0",
                "/api/networks/atomone-mainnet/search/validators?q=UTSA&limit=7",
            ):
                self.assertEqual(client.get(path).status_code, 422, path)

    def test_route_sanitizes_failures(self):
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.search_validators = AsyncMock(side_effect=RuntimeError("SECRET_UPSTREAM"))
            response = client.get("/api/networks/atomone-mainnet/search/validators?q=UTSA")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("SECRET_UPSTREAM", response.text)
