import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from api.cosmos import RequestCache
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService


class TransactionEndpointPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient()
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())
        self.fast = SimpleNamespace(endpoint="https://fast.example")
        self.good = SimpleNamespace(endpoint="https://good.example")
        self.service.adapter._cached_candidates = AsyncMock(return_value=(self.fast, self.good))
        self.service.adapter._clock = lambda: 100.0

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_event_search_prefers_later_nonempty_over_fast_false_empty(self):
        empty = {"txs": [], "tx_responses": [], "pagination": {"total": "0"}}
        found = {"txs": [{"body": {"messages": []}}],
                 "tx_responses": [{"txhash": "A" * 64}],
                 "pagination": {"total": "1"}}

        async def get_object(endpoint, _path, **_kwargs):
            return empty if endpoint == self.fast.endpoint else found

        self.service.transport.get_object = AsyncMock(side_effect=get_object)
        result = await self.service._validator_event_search("message.sender='atone1x'", 10)
        self.assertIs(result, found)
        self.assertIn(("tx_search", self.fast.endpoint), self.service._tx_operation_suspect_until)
        ordered = await self.service._operation_candidates("rest", "tx_search")
        self.assertEqual([candidate.endpoint for candidate in ordered],
                         [self.good.endpoint, self.fast.endpoint])

    async def test_event_search_all_empty_keeps_valid_empty_result(self):
        empty = {"txs": [], "tx_responses": [], "pagination": {"total": "0"}}
        self.service.transport.get_object = AsyncMock(return_value=empty)
        result = await self.service._validator_event_search("message.sender='atone1empty'", 10)
        self.assertEqual(result, empty)
        self.assertFalse(self.service._tx_operation_suspect_until)

    async def test_legacy_capability_is_remembered_per_endpoint(self):
        empty = {"txs": [], "tx_responses": []}
        calls = []

        async def get_object(endpoint, path, **_kwargs):
            calls.append((endpoint, path))
            if endpoint == self.fast.endpoint and "?query=" in path:
                return {"code": 3, "message": "unknown field query"}
            return empty

        self.service.transport.get_object = AsyncMock(side_effect=get_object)
        await self.service._validator_event_search("message.sender='atone1first'", 10)
        await self.service._validator_event_search("message.sender='atone1second'", 10)
        fast_paths = [path for endpoint, path in calls if endpoint == self.fast.endpoint]
        self.assertIn("?query=", fast_paths[0])
        self.assertIn("?events=", fast_paths[1])
        self.assertIn("?events=", fast_paths[2])
        self.assertEqual(self.service._tx_search_mode[self.fast.endpoint], "legacy")


if __name__ == "__main__":
    unittest.main()
