import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import httpx

from api.cosmos import (AllEndpointsUnavailable, CosmosAdapter, CosmosNetworkConfig,
                        InvalidConfiguration, MalformedUpstreamResponse, RequestCache)
from api.cosmos.parsing import parse_rest_block, parse_rest_head, parse_rpc_status
from api.cosmos.transport import JsonTransport

FIXTURES = Path(__file__).parent / "fixtures" / "cosmos"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def config(**changes):
    values = dict(network_id="cosmos-test", chain_id="cosmos-test-1",
                  rpc_endpoints=("https://rpc-a.example", "https://rpc-b.example"),
                  rest_endpoints=("https://rest-a.example", "https://rest-b.example"),
                  request_timeout=1.0, max_height_lag=2, probe_ttl=0, cache_ttl=0)
    values.update(changes)
    return CosmosNetworkConfig(**values)


class FakeClock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value
    def advance(self, amount): self.value += amount


class ConfigTests(unittest.TestCase):
    def test_valid_config_is_immutable_and_deduplicates_in_first_seen_order(self):
        item = config(rpc_endpoints=("HTTPS://RPC-A.EXAMPLE/", "https://rpc-a.example", "https://rpc-b.example"))
        self.assertEqual(item.rpc_endpoints, ("https://rpc-a.example", "https://rpc-b.example"))
        with self.assertRaises(Exception): item.network_id = "changed"

    def test_rejects_invalid_identity_and_endpoint_lists(self):
        bad = [dict(network_id="Bad ID"), dict(chain_id=""), dict(rpc_endpoints=()),
               dict(rest_endpoints=()), dict(request_timeout=31), dict(max_height_lag=-1)]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(InvalidConfiguration): config(**change)

    def test_rejects_unsafe_urls(self):
        urls = ("ftp://host.example", "https://user:secret@host.example", "https://host.example/a",
                "https://host.example?token=x", "https://host.example/#fragment", "https://host.example\n")
        urls += ("https://bad host.example", "https://-bad.example", "https://host.example:")
        for url in urls:
            with self.subTest(url=url), self.assertRaises(InvalidConfiguration): config(rpc_endpoints=(url,))


class ParsingTests(unittest.TestCase):
    def test_rpc_status_and_rest_identity_are_normalized(self):
        rpc = parse_rpc_status(fixture("rpc_status.json"), network_id="stable", expected_chain_id="cosmos-test-1", source_host="rpc.example")
        rest = parse_rest_head(fixture("rest_block.json"), network_id="stable", expected_chain_id="cosmos-test-1", source_host="rest.example")
        self.assertEqual((rpc.latest_height, rpc.latest_block_time, rpc.catching_up), (42, "2026-08-29T12:34:56.123456Z", False))
        self.assertEqual((rest.chain_id, rest.latest_height), ("cosmos-test-1", 42))

    def test_wrong_chain_catching_up_and_bad_scalar_rejected(self):
        cases = []
        wrong = fixture("rpc_status.json"); wrong["result"]["node_info"]["network"] = "other"; cases.append(wrong)
        catching = fixture("rpc_status.json"); catching["result"]["sync_info"]["catching_up"] = "false"; cases.append(catching)
        for value in (True, "1.0", "0", "-1", 0, -1):
            payload = fixture("rpc_status.json"); payload["result"]["sync_info"]["latest_block_height"] = value; cases.append(payload)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(Exception):
                parse_rpc_status(payload, network_id="stable", expected_chain_id="cosmos-test-1", source_host="safe")

    def test_block_rejects_bad_timestamp_hash_and_proposer(self):
        paths = (("block", "header", "time"), ("block_id", "hash"), ("block", "header", "proposer_address"))
        for path in paths:
            payload = fixture("rest_block.json")
            target = payload
            for part in path[:-1]: target = target[part]
            target[path[-1]] = "not-valid!"
            with self.subTest(path=path), self.assertRaises(MalformedUpstreamResponse):
                parse_rest_block(payload, network_id="stable", expected_chain_id="cosmos-test-1")


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_shape_size_status_and_malformed_json(self):
        responses = [httpx.Response(200, content=b"[]"), httpx.Response(200, content=b"x" * 1025),
                     httpx.Response(503, json={}), httpx.Response(200, content=b"{")]
        for response in responses:
            async def handler(_request, response=response): return response
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
            with self.subTest(response=response), self.assertRaises(Exception): await transport.get_object("https://safe.example", "/status")
            await client.aclose()

    async def test_timeout_and_connection_errors_are_sanitized(self):
        for error in (httpx.ReadTimeout("secret"), httpx.ConnectError("secret")):
            async def handler(request, error=error): raise error
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
                with self.assertRaisesRegex(Exception, "transport_error"):
                    await transport.get_object("https://safe.example", "/status")

    async def test_owned_client_is_closed(self):
        transport = JsonTransport(timeout=1, max_response_bytes=1024,
                                  transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})))
        client = transport._client
        await transport.aclose()
        self.assertTrue(client.is_closed)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_hit_expiry_eviction_and_copy_isolation(self):
        clock = FakeClock(); cache = RequestCache(max_entries=2, clock=clock); calls = 0
        async def load():
            nonlocal calls; calls += 1; return {"values": [calls]}
        first = await cache.get_or_load(("n", "head", ()), 5, load)
        first["values"].append(99)
        self.assertEqual(await cache.get_or_load(("n", "head", ()), 5, load), {"values": [1]})
        clock.advance(6)
        self.assertEqual(await cache.get_or_load(("n", "head", ()), 5, load), {"values": [2]})
        await cache.get_or_load(("n", "a", ()), 5, load); await cache.get_or_load(("n", "b", ()), 5, load)
        self.assertNotIn(("n", "head", ()), cache._entries)

    async def test_errors_not_cached_and_singleflight_failure_cleans_up(self):
        cache = RequestCache(); calls = 0; ready = asyncio.Event()
        async def fail():
            nonlocal calls; calls += 1; ready.set(); await asyncio.sleep(0); raise RuntimeError("safe")
        results = await asyncio.gather(cache.get_or_load(("n", "x", ()), 5, fail),
                                       cache.get_or_load(("n", "x", ()), 5, fail), return_exceptions=True)
        self.assertEqual(calls, 1); self.assertTrue(all(isinstance(item, RuntimeError) for item in results)); self.assertFalse(cache._inflight)
        with self.assertRaises(RuntimeError): await cache.get_or_load(("n", "x", ()), 5, fail)
        self.assertEqual(calls, 2)

    async def test_singleflight_success(self):
        cache = RequestCache(); calls = 0
        async def load():
            nonlocal calls; calls += 1; await asyncio.sleep(0.01); return ("ok",)
        self.assertEqual(await asyncio.gather(*(cache.get_or_load(("n", "x", ()), 5, load) for _ in range(10))), [("ok",)] * 10)
        self.assertEqual(calls, 1)

    def test_creates_no_threads_or_timers(self):
        before = tuple(threading.enumerate())
        RequestCache(clock=FakeClock())
        self.assertEqual(tuple(threading.enumerate()), before)
        with patch("threading.Timer", side_effect=AssertionError("timer created")): RequestCache()


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, handler): return httpx.MockTransport(handler)

    async def test_ranking_stale_and_catching_up_exclusion_and_rpc_failover(self):
        calls = []
        async def handler(request):
            calls.append((request.url.host, request.url.path, request.url.query))
            if request.url.path == "/status":
                payload = fixture("rpc_status.json")
                if request.url.host == "rpc-a.example": payload["result"]["sync_info"]["latest_block_height"] = "30"
                return httpx.Response(200, json=payload)
            if request.url.host == "rpc-a.example": return httpx.Response(500)
            return httpx.Response(200, json=fixture("rpc_block.json"))
        adapter = CosmosAdapter(config(max_height_lag=20), transport=self.transport(handler), clock=FakeClock())
        result = await adapter.block(41)
        self.assertEqual(result.height, 41)
        self.assertEqual([host for host, path, _ in calls if path == "/block"], ["rpc-a.example", "rpc-b.example"])
        await adapter.aclose()

    async def test_stale_and_catching_up_are_not_candidates(self):
        async def handler(request):
            payload = fixture("rpc_status.json")
            if request.url.host == "rpc-a.example": payload["result"]["sync_info"]["latest_block_height"] = "1"
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(max_height_lag=2), transport=self.transport(handler))
        candidates = await adapter._candidates("rpc")
        self.assertEqual([item.endpoint for item in candidates], ["https://rpc-b.example"])
        await adapter.aclose()

        async def catching_handler(request):
            payload = fixture("rpc_status.json")
            if request.url.host == "rpc-a.example": payload["result"]["sync_info"]["catching_up"] = True
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(), transport=self.transport(catching_handler))
        candidates = await adapter._candidates("rpc")
        self.assertEqual([item.endpoint for item in candidates], ["https://rpc-b.example"])
        await adapter.aclose()

    async def test_rest_failover_remains_in_rest_pool(self):
        seen = []
        async def handler(request):
            seen.append(request.url.host)
            if request.url.path.endswith("/42") and request.url.host == "rest-a.example": return httpx.Response(500)
            return httpx.Response(200, json=fixture("rest_block.json"))
        adapter = CosmosAdapter(config(), transport=self.transport(handler))
        result = await adapter.block(42, source="rest")
        self.assertEqual(result.transaction_count, 0)
        self.assertFalse(any(host.startswith("rpc") for host in seen))
        await adapter.aclose()

    async def test_wrong_chain_and_all_unavailable(self):
        async def handler(_request):
            payload = fixture("rpc_status.json"); payload["result"]["node_info"]["network"] = "wrong"
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(), transport=self.transport(handler))
        with self.assertRaises(AllEndpointsUnavailable): await adapter.chain_head()
        await adapter.aclose()

    async def test_cache_hit_avoids_network(self):
        calls = 0
        async def handler(_request):
            nonlocal calls; calls += 1; return httpx.Response(200, json=fixture("rpc_status.json"))
        adapter = CosmosAdapter(config(probe_ttl=10, cache_ttl=10), transport=self.transport(handler))
        self.assertEqual(await adapter.chain_head(), await adapter.chain_head())
        self.assertEqual(calls, 3)  # Two probes and one selected read.
        await adapter.aclose()

    async def test_deterministic_latency_tie_uses_config_order(self):
        async def handler(_request): return httpx.Response(200, json=fixture("rpc_status.json"))
        adapter = CosmosAdapter(config(), transport=self.transport(handler), clock=FakeClock())
        candidates = await adapter._candidates("rpc")
        self.assertEqual([item.endpoint for item in candidates], list(config().rpc_endpoints))
        await adapter.aclose()
