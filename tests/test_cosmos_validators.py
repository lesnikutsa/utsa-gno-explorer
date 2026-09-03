import asyncio
import base64
from datetime import timedelta
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

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


def test_commit_aggregation_is_set_based_and_order_independent():
    strip = {}
    signatures = {"signatures": [
        {"validator_address": "AA", "block_id_flag": 2},
        {"validator_address": "", "block_id_flag": 1},
        {"validator_address": "DD", "block_id_flag": 3},
        {"validator_address": "BB", "block_id_flag": 2},
    ]}
    aggregate_commit(strip, {"AA", "BB", "CC", "DD", "NEW"}, signatures,
                     ["CC", "AA", "DD", "BB"], 10157219, "2026-09-01T07:54:32Z")
    assert {address: strip[address][0]["status"] for address in ("AA", "BB", "CC", "DD", "NEW")} == {
        "AA": "commit", "BB": "commit", "CC": "absent", "DD": "nil", "NEW": "unknown"}


def test_two_addressless_absences_are_set_difference_misses():
    strip = {}
    aggregate_commit(strip, {"AA", "BB", "CC", "DD"}, {"signatures": [
        {"validator_address": "AA", "block_id_flag": 2},
        {"validator_address": "", "block_id_flag": 1},
        {"validator_address": "DD", "block_id_flag": 3},
        {"validator_address": "", "block_id_flag": 1},
    ]}, ["AA", "BB", "CC", "DD"], 9, None)
    assert {address: strip[address][0]["status"] for address in ("AA", "BB", "CC", "DD")} == {
        "AA": "commit", "BB": "absent", "CC": "absent", "DD": "nil"}


def test_nil_precommits_are_participation_not_downtime():
    strip = {}
    for height, flag in enumerate((2, 2, 3, 2, 2), 100):
        aggregate_commit(strip, {"AA"}, {"signatures": [
            {"validator_address": "AA", "block_id_flag": flag}
        ]}, ["AA"], height, None)
    assert [point["status"] for point in strip["AA"]] == ["commit", "commit", "nil", "commit", "commit"]
    assert "absent" not in [point["status"] for point in strip["AA"]]


def test_absent_is_missed_and_unknown_flag_is_unknown():
    strip = {}
    for height, flag in enumerate((2, 1, 2, 99), 200):
        aggregate_commit(strip, {"BB"}, {"signatures": [
            {"validator_address": "" if flag == 1 else "BB", "block_id_flag": flag}
        ]}, ["BB"], height, None)
    assert [point["status"] for point in strip["BB"]] == ["commit", "absent", "commit", "unknown"]


def test_signature_count_mismatch_is_unknown_not_guessed():
    strip = {}
    aggregate_commit(strip, {"AA", "BB"}, {"signatures": [
        {"validator_address": "AA", "block_id_flag": 2}
    ]}, ["AA", "BB"], 41, None)
    assert [strip[address][0]["status"] for address in ("AA", "BB")] == ["unknown", "unknown"]


def test_duplicate_or_foreign_participant_makes_block_unknown():
    for signatures in (
        [
            {"validator_address": "AA", "block_id_flag": 2},
            {"validator_address": "AA", "block_id_flag": 3},
        ],
        [
            {"validator_address": "AA", "block_id_flag": 2},
            {"validator_address": "CC", "block_id_flag": 3},
        ],
    ):
        strip = {}
        aggregate_commit(strip, {"AA", "BB"}, {"signatures": signatures},
                         ["AA", "BB"], 42, None)
        assert [strip[address][0]["status"] for address in ("AA", "BB")] == ["unknown", "unknown"]


def test_unverifiable_commit_is_unknown_with_height():
    strip = {}
    aggregate_commit(strip, {"AA"}, None, None, 42, None)
    assert strip == {"AA": [{"height": 42, "status": "unknown", "time": None}]}


def test_target_height_and_approximate_power_delta():
    assert target_height_24h(100_000, 6.0) == 85_600
    assert target_height_24h(100_000, None) is None
    assert approximate_token_delta(1_000_000, 100, 90) == 100_000
    assert approximate_token_delta(1_000_000, 0, 90) is None


def test_aggregate_bonded_delta_survives_membership_churn():
    # Aggregate totals do not require identical validator membership.
    assert approximate_token_delta(1_000_000, 200, 150) == 250_000


def test_signing_height_range_caps_large_idle_gap():
    from api.cosmos.validators import signing_height_range
    assert list(signing_height_range(100, 100_000)) == list(range(99_950, 100_000))
    assert list(signing_height_range(100, 103)) == [101, 102]
    assert list(signing_height_range(0, 101)) == list(range(51, 101))


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
            self.assertEqual(service._avatar("9E7A59BBDC93CC32"),
                             "https://s3.amazonaws.com/keybase_processed_uploads/test.jpg")
            self.assertEqual(calls, 1)
            self.assertFalse(service._avatar_tasks)

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

    async def test_repeated_block_proposer_reuses_cached_avatar(self):
        key = b"validator-consensus-key-000000"
        proposer = hashlib.sha256(key).digest()[:20].hex().upper()
        validator = {"consensus_pubkey": {"key": base64.b64encode(key).decode()},
            "operator_address": "atonevaloper1validator", "description": {
                "moniker": "Validator", "identity": "9E7A59BBDC93CC32"}}
        blocks = [{"height": height, "hash": f"HASH{height}",
                   "timestamp": "2026-09-01T00:00:00Z", "proposer": proposer,
                   "transaction_count": 0} for height in (10, 9)]
        avatar = "https://s3.amazonaws.com/keybase_processed_uploads/test.jpg"
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _request: httpx.Response(500))) as client:
            service = CosmosService(ATOMONE, client=client, cache=RequestCache())
            service.adapter.node_status = AsyncMock(return_value=SimpleNamespace(local_height=10))
            service._bonded_validators = AsyncMock(return_value=[validator])
            service._avatars["9E7A59BBDC93CC32"] = (service._wall_clock() + timedelta(hours=24), avatar)
            with patch("api.cosmos.service.metadata", new=AsyncMock(return_value=blocks)):
                result = await service.blocks(2)
            self.assertEqual([item["proposer_avatar_url"] for item in result["blocks"]], [avatar, avatar])
            self.assertFalse(service._avatar_tasks)


class ValidatorSetCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _request: httpx.Response(500)))
        self.service = CosmosService(ATOMONE, client=self.client, cache=RequestCache())

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_validator_hash_cache_fetches_once_per_distinct_set(self):
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

    async def test_current_subjective_commit_is_skipped_then_canonical_last_commit_is_used(self):
        addresses = [f"{index:040X}" for index in range(100)]
        self.service._signing_height = 100
        self.service._signing_blocks[101] = {"header": {
            "height": "101", "validators_hash": "HASH101", "time": "2026-09-01T00:00:00Z"},
            "last_commit": None}
        self.service.adapter._cached_candidates = AsyncMock(
            return_value=[SimpleNamespace(endpoint="https://rpc.example")])
        subjective = [{"validator_address": address, "block_id_flag": 2} for address in addresses[:70]]
        subjective += [{"validator_address": "", "block_id_flag": 1} for _ in range(30)]
        canonical = [{"validator_address": address, "block_id_flag": 2} for address in addresses]

        async def get_object(_endpoint, path):
            if path == "/commit?height=101":
                return {"result": {"canonical": False, "signed_header": {"commit": {
                    "height": "101", "signatures": subjective}}}}
            assert path == "/block?height=102"
            return {"result": {"block": {"header": {"height": "102"}, "last_commit": {
                "height": "101", "round": "0", "signatures": canonical}}}}

        self.service.transport.get_object = AsyncMock(side_effect=get_object)
        self.service._validator_set_for_hash = AsyncMock(return_value=addresses)
        await self.service._warm_signing(set(addresses), 101)
        assert self.service.transport.get_object.await_count == 0
        assert self.service._signing_strip == {}
        await self.service._warm_signing(set(addresses), 102)
        assert [call.args[1] for call in self.service.transport.get_object.await_args_list] == [
            "/block?height=102"]
        assert all(self.service._signing_strip[address] == [{
            "height": 101, "status": "commit", "time": "2026-09-01T00:00:00Z"}]
                   for address in addresses)
        assert self.service._signing_height == 101

    async def test_canonical_last_commit_preserves_one_real_absence_at_previous_height(self):
        addresses = ["AA", "BB", "CC"]
        self.service._signing_height = 100
        self.service._signing_blocks[101] = {"header": {
            "height": "101", "validators_hash": "HASH101", "time": "2026-09-01T00:00:00Z"},
            "last_commit": None}
        self.service.adapter._cached_candidates = AsyncMock(
            return_value=[SimpleNamespace(endpoint="https://rpc.example")])
        self.service.transport.get_object = AsyncMock(return_value={"result": {"block": {
            "header": {"height": "102"}, "last_commit": {"height": "101", "round": "0",
                "signatures": [{"validator_address": "AA", "block_id_flag": 2},
                               {"validator_address": "", "block_id_flag": 1},
                               {"validator_address": "CC", "block_id_flag": 3}]}}}})
        self.service._validator_set_for_hash = AsyncMock(return_value=addresses)
        await self.service._warm_signing(set(addresses), 102)
        assert {address: self.service._signing_strip[address][0]["status"] for address in addresses} == {
            "AA": "commit", "BB": "absent", "CC": "nil"}
        assert all(self.service._signing_strip[address][0]["height"] == 101 for address in addresses)

    async def test_signing_warmup_uses_remaining_healthy_rpc_before_marking_unknown(self):
        self.service._signing_height = 100
        self.service._signing_blocks[101] = {"header": {
            "height": "101", "validators_hash": "HASH101", "time": "2026-09-01T00:00:00Z"},
            "last_commit": None}
        self.service.adapter._cached_candidates = AsyncMock(return_value=[
            SimpleNamespace(endpoint="https://failed.example"),
            SimpleNamespace(endpoint="https://healthy.example"),
        ])

        async def get_object(endpoint, _path):
            if endpoint == "https://failed.example":
                raise RuntimeError("endpoint unavailable")
            return {"result": {"block": {"header": {"height": "102"}, "last_commit": {
                "height": "101", "signatures": [{"validator_address": "AA", "block_id_flag": 2}]}}}}

        self.service.transport.get_object = AsyncMock(side_effect=get_object)
        self.service._validator_set_for_hash = AsyncMock(return_value=["AA"])
        await self.service._warm_signing({"AA"}, 102)
        assert self.service._signing_strip["AA"][0]["status"] == "commit"
        assert [call.args[0] for call in self.service.transport.get_object.await_args_list] == [
            "https://failed.example", "https://healthy.example"]
