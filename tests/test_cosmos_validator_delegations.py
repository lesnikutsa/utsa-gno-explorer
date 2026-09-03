import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.cosmos import RequestCache
from api.cosmos.errors import AllEndpointsUnavailable, InvalidValidatorAddress, MalformedUpstreamResponse
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService


OPERATOR = "atonevaloper1validator"
DELEGATOR = "atone1delegator"


def delegation_payload(*, next_key="bmV4dA==", total="2", denom="uatone"):
    pagination = {}
    if next_key is not None:
        pagination["next_key"] = next_key
    if total is not None:
        pagination["total"] = total
    return {
        "delegation_responses": [
            {"delegation": {"delegator_address": DELEGATOR,
                            "validator_address": OPERATOR,
                            "shares": "123.450000"},
             "balance": {"denom": denom, "amount": "201201000000"}},
            {"delegation": {"delegator_address": "atone1second",
                            "validator_address": OPERATOR,
                            "shares": "7"},
             "balance": {"denom": "ibc/UNKNOWN", "amount": "42"}},
        ],
        "pagination": pagination,
    }


class FakeDatabase:
    def open(self, _config):
        pass

    def close(self):
        pass


class CosmosValidatorDelegationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient()
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())

    async def asyncTearDown(self):
        await self.client.aclose()

    def stub_rest(self, payload):
        self.service._rest = AsyncMock(
            side_effect=lambda _name, _path, validator=None: validator(payload))

    async def test_normalizes_multiple_rows_known_and_unknown_denoms_and_pagination(self):
        self.stub_rest(delegation_payload())
        with patch("api.cosmos.service.valid_bech32_address", return_value=True):
            result = await self.service.validator_delegations(OPERATOR, 10)
        self.assertEqual(result["items"][0], {
            "delegator_address": DELEGATOR, "validator_address": OPERATOR,
            "shares": "123.450000", "balance": {"denom": "uatone", "amount": "201201000000"}})
        self.assertEqual(result["items"][1]["balance"], {"denom": "ibc/UNKNOWN", "amount": "42"})
        self.assertEqual(result["next_key"], "bmV4dA==")
        self.assertEqual(result["total"], 2)
        path = self.service._rest.await_args.args[1]
        self.assertIn(f"/validators/{OPERATOR}/delegations?", path)
        self.assertIn("pagination.limit=10", path)
        self.assertIn("pagination.count_total=true", path)

    async def test_cursor_page_and_absent_optional_pagination_values(self):
        self.stub_rest(delegation_payload(next_key=None, total=None))
        with patch("api.cosmos.service.valid_bech32_address", return_value=True):
            result = await self.service.validator_delegations(OPERATOR, 10, "bmV4dA==")
        self.assertIsNone(result["next_key"])
        self.assertIsNone(result["total"])
        path = self.service._rest.await_args.args[1]
        self.assertIn("pagination.key=bmV4dA%3D%3D", path)
        self.assertIn("pagination.count_total=false", path)

    async def test_cache_is_request_driven_and_has_no_database_dependency(self):
        self.stub_rest(delegation_payload(next_key=None))
        with patch("api.cosmos.service.valid_bech32_address", return_value=True), \
                patch("api.database.get_validator_delegations", create=True) as database_call:
            await self.service.validator_delegations(OPERATOR)
            await self.service.validator_delegations(OPERATOR)
        self.service._rest.assert_awaited_once()
        database_call.assert_not_called()

    async def test_rejects_invalid_inputs_and_malformed_upstream(self):
        with self.assertRaises(InvalidValidatorAddress):
            await self.service.validator_delegations("wrong1address")
        with patch("api.cosmos.service.valid_bech32_address", return_value=True):
            for limit in (0, 21):
                with self.assertRaises(ValueError):
                    await self.service.validator_delegations(OPERATOR, limit)
            with self.assertRaises(ValueError):
                await self.service.validator_delegations(OPERATOR, pagination_key="not base64")
            for payload in ({}, {"delegation_responses": "bad"},
                            {"delegation_responses": [{"delegation": {}, "balance": {}}]}):
                self.stub_rest(payload)
                with self.assertRaises((MalformedUpstreamResponse, ValueError)):
                    await self.service.validator_delegations(OPERATOR)


class CosmosValidatorDelegationRouteTests(unittest.TestCase):
    def setUp(self):
        from api import app as module
        self.module = module
        self.patches = [patch.object(module, "database", FakeDatabase()),
                        patch.object(module, "load_config", return_value=ApiConfig("postgresql://test"))]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_route_contract_bounds_unknown_network_and_failure_sanitization(self):
        payload = {"items": [], "next_key": None, "total": None}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.validator_delegations = AsyncMock(return_value=payload)
            response = client.get(f"/api/networks/atomone-mainnet/validators/{OPERATOR}/delegations")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"items": []})
            service.validator_delegations.assert_awaited_once_with(OPERATOR, 10, None)
            self.assertEqual(client.get(f"/api/networks/unknown/validators/{OPERATOR}/delegations").status_code, 404)
            for limit in (0, 21):
                self.assertEqual(client.get(f"/api/networks/atomone-mainnet/validators/{OPERATOR}/delegations?limit={limit}").status_code, 422)
            service.validator_delegations = AsyncMock(side_effect=AllEndpointsUnavailable("SECRET_UPSTREAM"))
            failed = client.get(f"/api/networks/atomone-mainnet/validators/{OPERATOR}/delegations")
            self.assertEqual(failed.status_code, 503)
            self.assertNotIn("SECRET_UPSTREAM", failed.text)

    def test_invalid_operator_is_reported_safely(self):
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.validator_delegations = AsyncMock(side_effect=InvalidValidatorAddress("secret"))
            response = client.get("/api/networks/atomone-mainnet/validators/wrong/delegations")
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("secret", response.text)
