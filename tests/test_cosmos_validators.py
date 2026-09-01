import asyncio
import unittest
from unittest.mock import AsyncMock

import httpx

from api.cosmos import RequestCache
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService
from api.cosmos.validators import (aggregate_commit, approximate_token_delta, category,
    miss_metrics, target_height_24h)


def test_categories_keep_jailed_separate():
    assert category({"status": "BOND_STATUS_BONDED", "jailed": False}) == "active"
    assert category({"status": "BOND_STATUS_UNBONDED", "jailed": False}) == "inactive"
    assert category({"status": "BOND_STATUS_BONDED", "jailed": True}) == "jailed"


def test_slashing_budget_signed_percent_and_eta():
    value = miss_metrics(443, 10000, "0.05", 5.5)
    assert value == {"signed_percent": 95.57, "allowed_misses": 9500,
                     "remaining_budget": 9057, "jail_eta_seconds": 49814}
    assert miss_metrics(443, 10000, "0.05", None)["jail_eta_seconds"] is None


def test_commit_aggregation_uses_historical_membership_and_block_context():
    strip = {}
    signatures = {"signatures": [
        {"block_id_flag": 2}, {"block_id_flag": 1}, {"block_id_flag": 3},
    ]}
    aggregate_commit(strip, {"AA", "BB", "CC", "NEW"}, signatures,
                     ["AA", "BB", "CC"], 10157219, "2026-09-01T07:54:32Z")
    assert strip["AA"] == [{"height": 10157219, "status": "signed", "time": "2026-09-01T07:54:32Z"}]
    assert strip["BB"][0]["status"] == "missed"
    assert strip["CC"][0]["status"] == "missed"
    assert strip["NEW"][0]["status"] == "unknown"


def test_unverifiable_commit_is_unknown_with_height():
    strip = {}
    aggregate_commit(strip, {"AA"}, None, None, 42, None)
    assert strip == {"AA": [{"height": 42, "status": "unknown", "time": None}]}


def test_target_height_and_approximate_power_delta():
    assert target_height_24h(100_000, 6.0) == 85_600
    assert target_height_24h(100_000, None) is None
    assert approximate_token_delta(1_000_000, 100, 90) == 100_000
    assert approximate_token_delta(1_000_000, 0, 90) is None


def test_signing_height_range_caps_large_idle_gap():
    from api.cosmos.validators import signing_height_range
    assert list(signing_height_range(100, 100_000)) == list(range(99_951, 100_001))
    assert list(signing_height_range(100, 103)) == [101, 102, 103]


class AvatarCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_client_caches_valid_keybase_avatar(self):
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            self.assertEqual(request.url.params["key_suffix"], "9E7A59BBDC93CC32")
            return httpx.Response(200, json={"them": [{"pictures": {"primary": {
                "url": "https://s3.amazonaws.com/keybase_processed_uploads/test.jpg"
            }}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CosmosService(ATOMONE, client=client, cache=RequestCache())
            self.assertIs(service._client, client)
            await service._load_avatar("9E7A59BBDC93CC32")
            self.assertEqual(service._avatar("9E7A59BBDC93CC32"),
                             "https://s3.amazonaws.com/keybase_processed_uploads/test.jpg")
            self.assertEqual(calls, 1)

    async def test_keybase_failure_is_negative_cached_and_nonfatal(self):
        calls = 0
        async def handler(_request):
            nonlocal calls
            calls += 1
            return httpx.Response(503, json={"error": "unavailable"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CosmosService(ATOMONE, client=client, cache=RequestCache())
            await service._load_avatar("9E7A59BBDC93CC32")
            self.assertIsNone(service._avatar("9E7A59BBDC93CC32"))
            self.assertEqual(calls, 1)

    async def test_programming_error_is_not_negative_cached_and_task_is_cleaned(self):
        class BrokenClient:
            async def get(self, *_args, **_kwargs):
                raise AttributeError("client integration bug")
        service = CosmosService(ATOMONE, client=BrokenClient(), cache=RequestCache())
        service._avatar_tasks["IDENTITY"] = asyncio.current_task()
        with self.assertRaisesRegex(AttributeError, "integration bug"):
            await service._load_avatar("IDENTITY")
        self.assertNotIn("IDENTITY", service._avatars)
        self.assertNotIn("IDENTITY", service._avatar_tasks)

    async def test_only_eight_cold_avatar_tasks_are_started(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"them": []}))) as client:
            service = CosmosService(ATOMONE, client=client, cache=RequestCache())
            gate = asyncio.Event()
            async def blocked(_identity):
                await gate.wait()
            service._load_avatar = blocked
            for index in range(20):
                self.assertIsNone(service._avatar(f"IDENTITY{index}"))
            self.assertEqual(len(service._avatar_tasks), 8)
            gate.set()
            await asyncio.gather(*service._avatar_tasks.values())


class ValidatorSetCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(500)))
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_same_validators_hash_fetches_once_and_distinct_hash_fetches_once_each(self):
        self.service._rpc_validator_set = AsyncMock(return_value=[{"address": "AA", "voting_power": 10}])
        assert await self.service._validator_set_for_hash("HASH-A", 10) == ["AA"]
        assert await self.service._validator_set_for_hash("HASH-A", 11) == ["AA"]
        assert await self.service._validator_set_for_hash("HASH-B", 12) == ["AA"]
        assert self.service._rpc_validator_set.await_count == 2

    async def test_24h_power_result_cache_prevents_repeated_rpc_queries(self):
        self.service._rpc_validator_set = AsyncMock(side_effect=[
            [{"address": "AA", "voting_power": 100}],
            [{"address": "AA", "voting_power": 90}],
        ])
        first = await self.service._power_change_24h(100_000, 6.0)
        second = await self.service._power_change_24h(100_001, 6.0)
        assert first == second
        assert first["historical"]["AA"] == 90
        assert self.service._rpc_validator_set.await_count == 2

    async def test_unavailable_historical_set_returns_none(self):
        self.service._rpc_validator_set = AsyncMock(side_effect=RuntimeError("pruned"))
        assert await self.service._power_change_24h(100_000, 6.0) is None
