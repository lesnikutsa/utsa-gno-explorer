"""API integration coverage for Cosmos block state, failover, and caching."""

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from fastapi.testclient import TestClient
import httpx

from api.config import ApiConfig
from api.cosmos.cache import RequestCache
from api.cosmos.config import CosmosNetworkConfig
from api.cosmos.registry import AssetConfig, NetworkDefinition
from api.cosmos.service import CosmosService


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class FakeDatabase:
    def open(self, _config): pass
    def close(self): pass
    def fetch_blocks(self, *, limit, before_height): return []


def definition(endpoints=("https://a.example",)):
    return NetworkDefinition(
        transport=CosmosNetworkConfig(network_id="atomone-mainnet", chain_id="atomone-1",
                                      rpc_endpoints=endpoints, rest_endpoints=("https://rest.example",),
                                      probe_ttl=2, cache_ttl=2),
        family="cosmos", display_name="AtomOne", network_name="Mainnet",
        account_prefix="atone", validator_operator_prefix="atonevaloper",
        validator_consensus_prefix="atonevalcons", coin_type=118,
        assets=(AssetConfig("uatone", "atone", "ATONE", 6),), coingecko_id="atomone")


def status(height, catching_up=False):
    return {"result": {"node_info": {"network": "atomone-1"}, "sync_info": {
        "latest_block_height": str(height), "latest_block_time": NOW.isoformat(),
        "catching_up": catching_up}}}


def meta(height, txs="0", chain_id="atomone-1"):
    timestamp = NOW - timedelta(seconds=(210 - height) * 5)
    return {"block_id": {"hash": f"{height:064X}"}, "header": {
        "chain_id": chain_id, "height": str(height), "time": timestamp.isoformat(),
        "proposer_address": "AA" * 20}, "num_txs": txs}


def full_block(height):
    item = meta(height)
    return {"result": {"block_id": item["block_id"], "block": {"header": item["header"],
            "data": {"txs": []}}}}


class Upstream:
    def __init__(self, nodes, malformed_txs=None):
        self.nodes = nodes
        self.malformed_txs = malformed_txs
        self.calls = Counter()

    def __call__(self, request):
        host = request.url.host
        path = request.url.path
        self.calls[(host, path)] += 1
        node = self.nodes[host]
        if path == "/status":
            return httpx.Response(200, json=status(node["height"], node.get("catching_up", False)))
        if path == "/blockchain":
            query = parse_qs(request.url.query.decode())
            minimum, maximum = int(query["minHeight"][0]), int(query["maxHeight"][0])
            available = [height for height in range(maximum, minimum - 1, -1)
                         if node["lowest"] <= height <= node["height"]]
            if not available:
                return httpx.Response(200, json={"error": {"data":
                    f"height {maximum} is not available, lowest height is {node['lowest']}"}})
            return httpx.Response(200, json={"result": {"block_metas": [
                meta(height, self.malformed_txs if height == maximum and self.malformed_txs is not None else "0")
                for height in available[:20]]}})
        if path == "/block":
            height = int(request.url.params["height"])
            if node["lowest"] <= height <= node["height"]:
                return httpx.Response(200, json=full_block(height))
            return httpx.Response(200, json={"error": {"data":
                f"height {height} is not available, lowest height is {node['lowest']}"}})
        return httpx.Response(404)


class CosmosBlocksApiTests(unittest.TestCase):
    def setUp(self):
        from api import app as module
        self.module = module
        self.patches = [patch.object(module, "database", FakeDatabase()),
                        patch.object(module, "load_config", return_value=ApiConfig("postgresql://test"))]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def install(self, client, upstream, endpoints=None, cache=None):
        http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        service = CosmosService(definition(endpoints or tuple(f"https://{host}" for host in upstream.nodes)),
                                client=http, cache=cache or RequestCache(), now=lambda: NOW)
        client.app.state.cosmos_services["atomone-mainnet"] = service
        return service, http

    def test_partial_history_can_estimate_or_report_insufficient_sample(self):
        for lowest, expected_eta, reason in ((160, True, None), (191, False, "insufficient_sample")):
            with self.subTest(lowest=lowest), TestClient(self.module.app) as client:
                upstream = Upstream({"a.example": {"height": 200, "lowest": lowest}})
                self.install(client, upstream)
                body = client.get("/api/networks/atomone-mainnet/blocks/201").json()
                self.assertEqual(body["state"], "future")
                self.assertEqual(body["eta"] is not None, expected_eta)
                self.assertEqual(body["eta_unavailable_reason"], reason)
                self.assertLessEqual(upstream.calls[("a.example", "/blockchain")], 6)

    def test_cached_repeated_list_and_eta_samples(self):
        upstream = Upstream({"a.example": {"height": 200, "lowest": 1}})
        with TestClient(self.module.app) as client:
            service, _ = self.install(client, upstream)
            for _ in range(3):
                self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks").status_code, 200)
            self.assertEqual(upstream.calls[("a.example", "/status")], 1)
            self.assertEqual(upstream.calls[("a.example", "/blockchain")], 1)
            first = client.get("/api/networks/atomone-mainnet/blocks/201")
            calls = upstream.calls[("a.example", "/blockchain")]
            second = client.get("/api/networks/atomone-mainnet/blocks/202")
            self.assertEqual((first.status_code, second.status_code), (200, 200))
            self.assertEqual(upstream.calls[("a.example", "/blockchain")], calls)

    def test_parallel_singleflight_ttl_expiry_new_head_and_legacy_isolation(self):
        clock = [0.0]
        cache = RequestCache(clock=lambda: clock[0])
        upstream = Upstream({"a.example": {"height": 200, "lowest": 1}})
        async def exercise():
            http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
            service = CosmosService(definition(), client=http, cache=cache, now=lambda: NOW)
            await asyncio.gather(*(service.recent_blocks(10) for _ in range(3)))
            self.assertEqual(upstream.calls[("a.example", "/status")], 1)
            self.assertEqual(upstream.calls[("a.example", "/blockchain")], 1)
            clock[0] = 3
            upstream.nodes["a.example"]["height"] = 201
            result = await service.recent_blocks(10)
            self.assertEqual(result["source"]["observed_height"], 201)
            self.assertEqual(upstream.calls[("a.example", "/status")], 2)
            self.assertEqual(upstream.calls[("a.example", "/blockchain")], 2)
            await http.aclose()
        asyncio.run(exercise())
        with TestClient(self.module.app) as client:
            before = sum(upstream.calls.values())
            self.assertEqual(client.get("/api/blocks").status_code, 200)
            self.assertEqual(sum(upstream.calls.values()), before)

    def test_observed_ahead_prevents_false_future_and_stale_archive_is_used(self):
        nodes = {"a.example": {"height": 200, "lowest": 190},
                 "b.example": {"height": 210, "lowest": 205, "catching_up": True},
                 "archive.example": {"height": 150, "lowest": 1}}
        upstream = Upstream(nodes)
        with TestClient(self.module.app) as client:
            self.install(client, upstream)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks/205").json()["state"], "available")
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks/100").json()["state"], "available")
            self.assertEqual(upstream.calls[("archive.example", "/block")], 1)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks/211").json()["state"], "node_not_synced")

    def test_malformed_metadata_is_controlled_and_parameters_are_typed(self):
        upstream = Upstream({"a.example": {"height": 200, "lowest": 1}}, malformed_txs="2147483648")
        with TestClient(self.module.app) as client:
            self.install(client, upstream)
            response = client.get("/api/networks/atomone-mainnet/blocks")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("2147483648", response.text)
            self.assertEqual(client.get("/api/networks/unknown/blocks").status_code, 404)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks?limit=21").status_code, 422)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks/0").status_code, 422)
