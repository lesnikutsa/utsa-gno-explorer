from datetime import datetime, timedelta, timezone
import asyncio
import unittest

import httpx

from api.cosmos import RequestCache
from api.cosmos.registry import ATOMONE
from api.cosmos.service import CosmosService
from api.cosmos.validators import aggregate_commit, category, miss_metrics, nearest_snapshot


def test_categories_keep_jailed_separate():
    assert category({"status": "BOND_STATUS_BONDED", "jailed": False}) == "active"
    assert category({"status": "BOND_STATUS_UNBONDED", "jailed": False}) == "inactive"
    assert category({"status": "BOND_STATUS_BONDED", "jailed": True}) == "jailed"


def test_slashing_budget_signed_percent_and_eta():
    value = miss_metrics(443, 10000, "0.05", 5.5)
    assert value == {"signed_percent": 95.57, "allowed_misses": 9500,
                     "remaining_budget": 9057, "jail_eta_seconds": 49814}
    assert miss_metrics(443, 10000, "0.05", None)["jail_eta_seconds"] is None


def test_commit_aggregation_is_block_centric_and_unknown_safe():
    strip = {}
    active = {"AA", "BB"}
    aggregate_commit(strip, active, {"signatures": [{"validator_address": "aa", "block_id_flag": 2}]})
    aggregate_commit(strip, active, None)
    assert strip == {"AA": ["signed", "unknown"], "BB": ["unknown", "unknown"]}
    assert "CC" not in strip  # inactive validators never receive false misses


def test_snapshot_requires_complete_24_hour_history():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert nearest_snapshot([(now - timedelta(hours=23), {"v": 1})], now) is None
    assert nearest_snapshot([(now - timedelta(hours=24, minutes=5), {"v": 2})], now) == {"v": 2}


def test_explicit_miss_and_joined_later_are_conservative():
    strip = {}
    aggregate_commit(strip, {"AA", "NEW"}, {"signatures": [
        {"validator_address": "AA", "block_id_flag": 1},
    ]})
    assert strip == {"AA": ["missed"], "NEW": ["unknown"]}


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
