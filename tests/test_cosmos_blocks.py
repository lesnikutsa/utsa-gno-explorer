from datetime import datetime, timedelta, timezone
from dataclasses import replace
import asyncio
import unittest
import httpx

from api.cosmos.blocks import estimate_eta, parse_blockchain
from api.cosmos.errors import MalformedUpstreamResponse
from api.cosmos.rfc3339 import normalize_rfc3339, parse_rfc3339
from api.cosmos.transport import JsonTransport
from api.cosmos.cache import RequestCache
from api.cosmos.config import CosmosNetworkConfig
from api.cosmos.errors import AllEndpointsUnavailable, HistoryUnavailable
from api.cosmos.registry import ATOMONE, NetworkDefinition
from api.cosmos.service import CosmosService


class _Response:
    status_code = 200
    def __init__(self, delay=0): self.delay = delay; self.closed = False
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): self.closed = True
    async def aiter_bytes(self):
        await asyncio.sleep(self.delay)
        yield b"{}"


class _Client:
    def __init__(self, response): self.response = response
    def stream(self, *_args, **_kwargs): return self.response


class TransportDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_covers_stream_and_closes_response(self):
        response = _Response(delay=.05)
        transport = JsonTransport(timeout=.01, max_response_bytes=1024, client=_Client(response))
        with self.assertRaisesRegex(Exception, "transport_error"):
            await transport.get_object("https://safe.example", "/status")
        self.assertTrue(response.closed)

    async def test_external_cancellation_is_preserved_and_closes_response(self):
        response = _Response(delay=1)
        transport = JsonTransport(timeout=5, max_response_bytes=1024, client=_Client(response))
        task = asyncio.create_task(transport.get_object("https://safe.example", "/status"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(response.closed)


class Rfc3339Tests(unittest.TestCase):
    def test_nanoseconds_and_offsets_are_normalized_on_python_310(self):
        self.assertEqual(normalize_rfc3339("2026-08-30T12:34:56.123456789Z"),
                         "2026-08-30T12:34:56.123456Z")
        self.assertEqual(normalize_rfc3339("2026-08-30T14:34:56.1+02:00"),
                         "2026-08-30T12:34:56.100000Z")
        self.assertEqual(parse_rfc3339("2026-08-30T12:34:56-03:30").tzinfo, timezone.utc)

    def test_invalid_offset_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_rfc3339("2026-08-30T12:34:56+00:60")


class BlockMetadataTests(unittest.TestCase):
    def metadata(self, height, timestamp):
        return {"block_id": {"hash": "AA"}, "header": {"chain_id": "atomone-1",
            "height": str(height), "time": timestamp, "proposer_address": "BB"}, "num_txs": "0"}

    def test_metadata_uses_shared_timestamp_parser(self):
        payload = {"result": {"block_metas": [self.metadata(42, "2026-08-30T12:34:56.123456789Z")]}}
        blocks = parse_blockchain(payload, network_id="atomone-mainnet", expected_chain_id="atomone-1")
        self.assertEqual(blocks[0]["timestamp"], "2026-08-30T12:34:56.123456Z")

    def test_metadata_rejects_wrong_chain(self):
        payload = {"result": {"block_metas": [self.metadata(42, "2026-08-30T12:34:56Z")]}}
        payload["result"]["block_metas"][0]["header"]["chain_id"] = "wrong"
        with self.assertRaises(Exception):
            parse_blockchain(payload, network_id="atomone-mainnet", expected_chain_id="atomone-1")

    def test_eta_trims_outliers_and_anchors_to_last_block(self):
        blocks = []
        base = parse_rfc3339("2026-08-30T00:00:00Z")
        elapsed = 0
        for height in range(1, 102):
            blocks.append({"height": height, "timestamp": (base.replace(tzinfo=timezone.utc)
                .timestamp() + elapsed)})
            elapsed += 1000 if height in {10, 90} else 5
        for block in blocks:
            from datetime import datetime
            block["timestamp"] = datetime.fromtimestamp(block["timestamp"], timezone.utc).isoformat().replace("+00:00", "Z")
        eta = estimate_eta(blocks, 111)
        self.assertIsNotNone(eta)
        self.assertEqual(eta["remaining_blocks"], 10)
        self.assertAlmostEqual(eta["average_block_seconds"], 5)

    def test_eta_requires_twenty_trimmed_intervals(self):
        blocks = [{"height": height, "timestamp": f"2026-08-30T00:00:{height:02d}Z"} for height in range(1, 20)]
        self.assertIsNone(estimate_eta(blocks, 30))


class CheckpointEtaIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = 0.0
        self.head = 2_000
        self.available_spans = {1000, 500, 200, 80}
        self.block_calls = []
        self.now = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)

    def status(self):
        return {"result": {"node_info": {"network": "atomone-1", "version": "1", "other": {}},
            "sync_info": {"latest_block_height": str(self.head),
                "latest_block_time": self.now.isoformat().replace("+00:00", "Z"), "catching_up": False}}}

    def block(self, height):
        timestamp = self.now - timedelta(seconds=(self.head - height) * 6)
        return {"result": {"block_id": {"hash": "AA"}, "block": {"header": {
            "chain_id": "atomone-1", "height": str(height),
            "time": timestamp.isoformat().replace("+00:00", "Z"),
            "proposer_address": "BB"}, "data": {"txs": []}}}}

    async def handler(self, request):
        if request.url.path == "/status":
            return httpx.Response(200, json=self.status())
        if request.url.path == "/block":
            height = int(request.url.params["height"])
            self.block_calls.append(height)
            span = self.head - height
            if span and span not in self.available_spans:
                return httpx.Response(200, json={"error": {"data":
                    f"height {height} is not available, lowest height is {self.head - max(self.available_spans)}"}})
            return httpx.Response(200, json=self.block(height))
        return httpx.Response(500, json={"error": "unexpected"})

    async def make_service(self):
        cache = RequestCache(clock=lambda: self.clock)
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler), trust_env=False)
        self.addAsyncCleanup(client.aclose)
        return CosmosService(ATOMONE, client=client, cache=cache, wall_clock=lambda: self.now)

    async def assert_span(self, available_spans, expected_span):
        self.available_spans = set(available_spans)
        service = await self.make_service()
        result = await service.block_lookup(self.head + 10)
        self.assertEqual(result["state"], "future")
        self.assertEqual(result["eta"]["sample_intervals"], expected_span)
        self.assertEqual(result["eta"]["average_block_seconds"], 6)
        self.assertEqual(result["eta"]["remaining_blocks"], 10)
        self.assertEqual(self.block_calls, [self.head] + [self.head - span for span in (1000, 500, 200, 80)
            if span >= expected_span])

    async def test_uses_1000_block_checkpoint_when_available(self):
        await self.assert_span({1000, 500, 200, 80}, 1000)

    async def test_falls_back_to_500_block_checkpoint(self):
        await self.assert_span({500, 200, 80}, 500)

    async def test_falls_back_to_200_block_checkpoint(self):
        await self.assert_span({200, 80}, 200)

    async def test_falls_back_to_80_block_checkpoint(self):
        await self.assert_span({80}, 80)

    async def test_all_checkpoints_unavailable_is_graceful(self):
        self.available_spans = set()
        service = await self.make_service()
        result = await service.block_lookup(self.head + 10)
        self.assertEqual(result["state"], "future")
        self.assertIsNone(result["eta"])
        self.assertEqual(result["eta_unavailable_reason"], "insufficient_history")
        self.assertEqual(len(self.block_calls), 5)
        await service.block_lookup(self.head + 20)
        self.assertEqual(len(self.block_calls), 5)

    async def test_cache_reuse_and_expiry(self):
        service = await self.make_service()
        first = await service.block_lookup(self.head + 10)
        calls = list(self.block_calls)
        second = await service.block_lookup(self.head + 20)
        self.assertEqual(self.block_calls, calls)
        self.assertEqual(second["eta"]["remaining_blocks"], 20)
        self.clock += 301
        await service.block_lookup(self.head + 30)
        self.assertGreater(len(self.block_calls), len(calls))
        self.assertEqual(first["eta"]["sample_intervals"], 1000)

    async def test_very_distant_target_uses_cached_average(self):
        service = await self.make_service()
        result = await service.block_lookup(self.head + 100_000_000)
        self.assertEqual(result["eta"]["remaining_blocks"], 100_000_000)
        expected = self.now + timedelta(seconds=600_000_000)
        self.assertEqual(parse_rfc3339(result["eta"]["estimated_at"]), expected)

    async def test_current_or_past_target_keeps_available_behavior(self):
        service = await self.make_service()
        result = await service.block_lookup(self.head)
        self.assertEqual(result["state"], "available")
        self.assertIsNone(result["eta"])


class ConflictingHeightIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def definition(self):
        return NetworkDefinition(
            transport=CosmosNetworkConfig(network_id="height-test", chain_id="height-1",
                rpc_endpoints=("https://a.example", "https://b.example"),
                rest_endpoints=("https://rest.example",), cache_ttl=2, probe_ttl=2),
            family="cosmos", display_name="Height Test", network_name="Testnet",
            account_prefix="test", validator_operator_prefix="testvaloper",
            validator_consensus_prefix="testvalcons", coin_type=118,
            assets=ATOMONE.assets, coingecko_id="height-test")

    def status(self, height, catching_up):
        return {"result": {"node_info": {"network": "height-1", "version": "1", "other": {}},
            "sync_info": {"latest_block_height": str(height), "latest_block_time": "2026-08-30T00:00:00Z",
                          "catching_up": catching_up}}}

    def block(self, height):
        return {"result": {"block_id": {"hash": "AA"}, "block": {"header": {
            "chain_id": "height-1", "height": str(height), "time": "2026-08-30T00:00:00Z",
            "proposer_address": "BB"}, "data": {"txs": []}}}}

    async def test_syncing_endpoint_observation_prevents_false_future(self):
        async def handler(request):
            if request.url.path == "/status":
                return httpx.Response(200, json=self.status(100, False) if request.url.host == "a.example" else self.status(150, True))
            if request.url.path == "/block" and request.url.host == "b.example":
                return httpx.Response(200, json=self.block(120))
            return httpx.Response(503, json={"error": "temporary"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CosmosService(self.definition(), client=client, cache=RequestCache())
            result = await service.block_lookup(120)
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["local_height"], 150)
        self.assertIsNone(result["eta"])

    async def test_mixed_pruning_and_upstream_error_is_not_history_unavailable(self):
        async def handler(request):
            if request.url.path == "/status":
                return httpx.Response(200, json=self.status(150, request.url.host == "b.example"))
            if request.url.host == "a.example":
                return httpx.Response(200, json={"error": {"data": "height 120 is not available, lowest height is 130"}})
            return httpx.Response(503, json={"error": "temporary"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = CosmosService(self.definition(), client=client, cache=RequestCache())
            with self.assertRaises(AllEndpointsUnavailable):
                await service.block_lookup(120)


class ObservedBlockCacheIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = 0.0
        self.block_calls = 0
        self.fail_remaining = 0
        self.block_gate = None

    def status(self):
        return {"result": {"node_info": {"network": "atomone-1", "version": "1", "other": {}},
            "sync_info": {"latest_block_height": "200", "latest_block_time": "2026-08-30T00:00:00Z",
                          "catching_up": False}}}

    def block(self):
        return {"result": {"block_id": {"hash": "AA"}, "block": {"header": {
            "chain_id": "atomone-1", "height": "150", "time": "2026-08-30T00:00:00Z",
            "proposer_address": "BB"}, "data": {"txs": []}}}}

    async def handler(self, request):
        if request.url.path == "/status":
            return httpx.Response(200, json=self.status())
        if request.url.path == "/block":
            self.block_calls += 1
            if self.block_gate is not None:
                await self.block_gate.wait()
            if self.fail_remaining:
                self.fail_remaining -= 1
                return httpx.Response(503, json={"error": "temporary"})
            return httpx.Response(200, json=self.block())
        return httpx.Response(500, json={"error": "unexpected"})

    async def service(self, client, cache, definition=ATOMONE):
        return CosmosService(definition, client=client, cache=cache)

    async def test_parallel_hits_ttl_expiry_and_network_isolation(self):
        cache = RequestCache(clock=lambda: self.clock)
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            service = await self.service(client, cache)
            results = await asyncio.gather(*(service.block_lookup(150) for _ in range(3)))
            self.assertTrue(all(result["state"] == "available" for result in results))
            self.assertEqual(self.block_calls, 1)
            await service.block_lookup(150)
            self.assertEqual(self.block_calls, 1)
            self.clock += 3
            await service.block_lookup(150)
            self.assertEqual(self.block_calls, 2)
            isolated_definition = replace(
                ATOMONE, transport=replace(ATOMONE.transport, network_id="atomone-isolated"))
            isolated = await self.service(client, cache, isolated_definition)
            await isolated.block_lookup(150)
            self.assertEqual(self.block_calls, 3)

    async def test_error_and_cancellation_do_not_poison_singleflight(self):
        cache = RequestCache(clock=lambda: self.clock)
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            service = await self.service(client, cache)
            self.fail_remaining = len(ATOMONE.transport.rpc_endpoints)
            with self.assertRaises(AllEndpointsUnavailable):
                await service.block_lookup(150)
            self.assertFalse(cache._inflight)
            self.assertEqual((await service.block_lookup(150))["state"], "available")
            self.clock += 3
            self.block_gate = asyncio.Event()
            calls_before_cancel = self.block_calls
            task = asyncio.create_task(service.block_lookup(150))
            while self.block_calls == calls_before_cancel:
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(cache._inflight)
            self.block_gate.set()
            self.block_gate = None
            self.assertEqual((await service.block_lookup(150))["state"], "available")
