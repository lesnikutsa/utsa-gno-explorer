import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from api.cosmos import (AllEndpointsUnavailable, CosmosAdapter, CosmosNetworkConfig,
                        HistoryUnavailable, InvalidConfiguration,
                        MalformedUpstreamResponse, NodeNotSynced, RequestCache)
from api.cosmos.parsing import (parse_node_status, parse_rest_block, parse_rest_head,
                                parse_rest_node_info, parse_rpc_block, parse_rpc_status)
from api.cosmos.registry import ATOMONE, NETWORKS
from api.cosmos.service import CosmosService, _decimal, consensus_address
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
    def test_atomone_registry_is_immutable_and_has_two_native_assets(self):
        self.assertIs(NETWORKS["atomone-mainnet"], ATOMONE)
        self.assertEqual(ATOMONE.transport.chain_id, "atomone-1")
        self.assertEqual([(item.base, item.symbol, item.exponent) for item in ATOMONE.assets],
                         [("uatone", "ATONE", 6), ("uphoton", "PHOTON", 6)])
        with self.assertRaises(TypeError):
            NETWORKS["other"] = ATOMONE

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
    def test_decimal_normalization_is_bounded_and_exact(self):
        self.assertEqual(_decimal("153847948212982", "amount"), "153847948212982")
        self.assertEqual(_decimal("0.050000000000000000", "fraction"), "0.050000000000000000")
        self.assertEqual(_decimal("00012.3400", "amount"), "12.3400")
        for value in ("1e100000", "1e-100000"):
            with self.subTest(value=value), self.assertRaises(MalformedUpstreamResponse):
                _decimal(value, "amount")

    def test_rest_node_info_validates_identity_and_versions(self):
        payload = {"default_node_info": {"network": "cosmos-test-1"},
                   "application_version": {"name": "atomoned", "version": "1.2.3",
                                           "cosmos_sdk_version": "0.47.0"}}
        self.assertEqual(parse_rest_node_info(payload, expected_chain_id="cosmos-test-1"),
                         {"application_name": "atomoned", "application_version": "1.2.3",
                          "sdk_version": "0.47.0"})
        payload["default_node_info"]["network"] = "wrong"
        with self.assertRaises(Exception):
            parse_rest_node_info(payload, expected_chain_id="cosmos-test-1")

    def test_node_status_accepts_syncing_and_normalizes_tx_index(self):
        for raw, expected in (("on", "on"), ("kv", "on"), ("off", "off"), (None, "unknown")):
            payload = fixture("rpc_status.json")
            payload["result"]["sync_info"]["catching_up"] = True
            payload["result"]["node_info"]["other"] = {"tx_index": raw}
            status = parse_node_status(payload, network_id="stable",
                                       expected_chain_id="cosmos-test-1", source_host="safe")
            self.assertTrue(status.catching_up)
            self.assertEqual(status.tx_index, expected)

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

    def test_timestamp_utc_underflow_and_overflow_are_controlled(self):
        for timestamp in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"):
            payload = fixture("rest_block.json")
            payload["block"]["header"]["time"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(
                MalformedUpstreamResponse, "^invalid timestamp$"
            ) as captured:
                parse_rest_block(payload, network_id="stable", expected_chain_id="cosmos-test-1")
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)
            self.assertNotIn(timestamp, repr(captured.exception))

    def test_rpc_and_rest_reject_falsey_non_list_transactions(self):
        for parser, fixture_name, result_key in (
            (parse_rpc_block, "rpc_block.json", "result"),
            (parse_rest_block, "rest_block.json", None),
        ):
            for value in ({}, "", 0, False):
                payload = fixture(fixture_name)
                root = payload[result_key] if result_key else payload
                root["block"]["data"]["txs"] = value
                with self.subTest(parser=parser.__name__, value=value), self.assertRaises(MalformedUpstreamResponse):
                    parser(payload, network_id="stable", expected_chain_id="cosmos-test-1")
            for value in (None,):
                payload = fixture(fixture_name)
                root = payload[result_key] if result_key else payload
                root["block"]["data"]["txs"] = value
                self.assertEqual(parser(payload, network_id="stable", expected_chain_id="cosmos-test-1").transaction_count, 0)
            payload = fixture(fixture_name)
            root = payload[result_key] if result_key else payload
            del root["block"]["data"]["txs"]
            self.assertEqual(parser(payload, network_id="stable", expected_chain_id="cosmos-test-1").transaction_count, 0)

    def test_malformed_nested_rpc_objects_raise_controlled_error(self):
        for value in ("invalid", [], None):
            payload = fixture("rpc_status.json")
            payload["result"]["node_info"] = value
            with self.subTest(value=value), self.assertRaises(MalformedUpstreamResponse):
                parse_rpc_status(payload, network_id="stable", expected_chain_id="cosmos-test-1", source_host="safe")


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

    async def test_nonstandard_json_constants_are_rejected(self):
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            async def handler(_request, constant=constant):
                return httpx.Response(200, content=b'{"value":' + constant + b'}')
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
                with self.subTest(constant=constant), self.assertRaises(MalformedUpstreamResponse):
                    await transport.get_object("https://safe.example", "/status")

    async def test_protocol_error_drops_secret_exception_chain(self):
        async def handler(_request):
            raise httpx.RemoteProtocolError("SECRET_MARKER")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
            with self.assertRaisesRegex(Exception, "^transport_error$") as captured:
                await transport.get_object("https://safe.example", "/status")
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)
            self.assertNotIn("SECRET_MARKER", repr(captured.exception))

    async def test_invalid_gzip_is_a_sanitized_transport_error(self):
        async def handler(_request):
            return httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"not gzip")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
            with self.assertRaisesRegex(Exception, "^transport_error$") as captured:
                await transport.get_object("https://safe.example", "/status")
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)

    async def test_decoding_error_drops_secret_exception_chain(self):
        async def handler(_request):
            raise httpx.DecodingError("SECRET_DECODING_MARKER")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            transport = JsonTransport(timeout=1, max_response_bytes=1024, client=client)
            with self.assertRaisesRegex(Exception, "^transport_error$") as captured:
                await transport.get_object("https://safe.example", "/status")
            self.assertIsNone(captured.exception.__cause__)
            self.assertIsNone(captured.exception.__context__)
            self.assertNotIn("SECRET_DECODING_MARKER", repr(captured.exception))

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

    async def test_node_status_accepts_syncing_while_chain_head_remains_strict(self):
        async def handler(_request):
            payload = fixture("rpc_status.json")
            payload["result"]["sync_info"]["catching_up"] = True
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(rpc_endpoints=("https://rpc-a.example",)),
                                transport=self.transport(handler))
        self.assertTrue((await adapter.node_status()).catching_up)
        with self.assertRaises(AllEndpointsUnavailable):
            await adapter.chain_head()
        await adapter.aclose()


    async def test_rpc_pruning_error_is_typed_and_does_not_expose_message(self):
        async def handler(request):
            if request.url.path == "/status":
                return httpx.Response(200, json=fixture("rpc_status.json"))
            return httpx.Response(500, json={"error": {"message":
                "height 1 is not available, lowest height is 3133197 SECRET"}})
        adapter = CosmosAdapter(config(rpc_endpoints=("https://rpc-a.example",)),
                                transport=self.transport(handler))
        with self.assertRaises(HistoryUnavailable) as captured:
            await adapter.block(1)
        self.assertEqual(captured.exception.requested_height, 1)
        self.assertEqual(captured.exception.lowest_available_height, 3133197)
        self.assertEqual(str(captured.exception), "history_unavailable")
        self.assertNotIn("SECRET", repr(captured.exception))
        await adapter.aclose()

    async def test_pruned_rpc_fails_over_to_deeper_history(self):
        async def handler(request):
            if request.url.path == "/status":
                return httpx.Response(200, json=fixture("rpc_status.json"))
            if request.url.host == "rpc-a.example":
                return httpx.Response(500, json={"error": {"message":
                    "height 41 is not available, lowest height is 42"}})
            return httpx.Response(200, json=fixture("rpc_block.json"))
        adapter = CosmosAdapter(config(), transport=self.transport(handler))
        self.assertEqual((await adapter.block(41)).height, 41)
        await adapter.aclose()

    async def test_syncing_rpc_serves_local_blocks_and_rejects_ahead_height(self):
        async def handler(request):
            if request.url.path == "/status":
                payload = fixture("rpc_status.json")
                payload["result"]["sync_info"]["catching_up"] = True
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json=fixture("rpc_block.json"))
        adapter = CosmosAdapter(config(rpc_endpoints=("https://rpc-a.example",)),
                                transport=self.transport(handler))
        self.assertEqual((await adapter.block(41)).height, 41)
        with self.assertRaises(NodeNotSynced):
            await adapter.block(43)
        await adapter.aclose()

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

    async def test_selected_read_catching_up_fails_over(self):
        counts = {}
        async def handler(request):
            counts[request.url.host] = counts.get(request.url.host, 0) + 1
            payload = fixture("rpc_status.json")
            if request.url.host == "rpc-a.example" and counts[request.url.host] == 2:
                payload["result"]["sync_info"]["catching_up"] = True
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(), transport=self.transport(handler), clock=FakeClock())
        head = await adapter.chain_head()
        self.assertEqual(head.source_host, "rpc-b.example")
        self.assertEqual(counts, {"rpc-a.example": 2, "rpc-b.example": 2})
        await adapter.aclose()

    async def test_all_selected_reads_becoming_unsuitable_is_aggregate_error(self):
        counts = {}
        async def handler(request):
            counts[request.url.host] = counts.get(request.url.host, 0) + 1
            payload = fixture("rpc_status.json")
            if counts[request.url.host] == 2:
                payload["result"]["sync_info"]["catching_up"] = True
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(), transport=self.transport(handler), clock=FakeClock())
        with self.assertRaisesRegex(AllEndpointsUnavailable, "all validated RPC endpoints failed"):
            await adapter.chain_head()
        await adapter.aclose()

    async def test_selected_read_height_regression_fails_over(self):
        counts = {}
        async def handler(request):
            counts[request.url.host] = counts.get(request.url.host, 0) + 1
            payload = fixture("rpc_status.json")
            if request.url.host == "rpc-a.example" and counts[request.url.host] == 2:
                payload["result"]["sync_info"]["latest_block_height"] = "39"
            return httpx.Response(200, json=payload)
        adapter = CosmosAdapter(config(max_height_lag=2), transport=self.transport(handler), clock=FakeClock())
        head = await adapter.chain_head()
        self.assertEqual((head.source_host, head.latest_height), ("rpc-b.example", 42))
        await adapter.aclose()

    async def test_protocol_secret_is_absent_from_aggregate_error_and_logs(self):
        async def handler(_request):
            raise httpx.RemoteProtocolError("SECRET_MARKER")
        adapter = CosmosAdapter(config(), transport=self.transport(handler), clock=FakeClock())
        with self.assertLogs("api.cosmos.adapter", "INFO") as logs:
            with self.assertRaises(AllEndpointsUnavailable) as captured:
                await adapter.chain_head()
        rendered = "\n".join(logs.output) + repr(captured.exception)
        self.assertNotIn("SECRET_MARKER", rendered)
        self.assertIn("reason=transport_error", rendered)
        await adapter.aclose()

    async def test_decoding_secret_is_absent_from_aggregate_error_and_logs(self):
        async def handler(_request):
            raise httpx.DecodingError("SECRET_DECODING_MARKER")
        adapter = CosmosAdapter(config(), transport=self.transport(handler), clock=FakeClock())
        with self.assertLogs("api.cosmos.adapter", "INFO") as logs:
            with self.assertRaises(AllEndpointsUnavailable) as captured:
                await adapter.chain_head()
        rendered = "\n".join(logs.output) + repr(captured.exception)
        self.assertNotIn("SECRET_DECODING_MARKER", rendered)
        self.assertIn("reason=transport_error", rendered)
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

class ValidatorRankingTests(unittest.IsolatedAsyncioTestCase):
    async def test_slashing_uses_sdk_round_int64_semantics(self):
        service = object.__new__(CosmosService)
        for window, minimum, expected in ((10, "0.25", 8), (10, "0.35", 6),
                                           (10, "0.21", 8), (10000, "0.05", 9500)):
            async def rest(_name, _path, window=window, minimum=minimum):
                return {"params": {"signed_blocks_window": str(window), "min_signed_per_window": minimum,
                    "downtime_jail_duration": "600s", "slash_fraction_double_sign": "0.05",
                    "slash_fraction_downtime": "0.01"}}
            service._rest = rest
            with self.subTest(window=window, minimum=minimum):
                result = await service._slashing()
                self.assertEqual(result["allowed_missed_threshold"], expected)

    async def test_active_only_deterministic_top_missed(self):
        key_a = {"key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}
        key_b = {"key": "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="}
        address_a = consensus_address(key_a, "atonevalcons")
        address_b = consensus_address(key_b, "atonevalcons")
        service = object.__new__(CosmosService)
        service.definition = SimpleNamespace(validator_consensus_prefix="atonevalcons")
        validators = [
            {"status": "BOND_STATUS_BONDED", "consensus_pubkey": key_a,
             "description": {"moniker": "A"}, "operator_address": "atonevaloper1a", "jailed": False},
            {"status": "BOND_STATUS_BONDED", "consensus_pubkey": key_b,
             "description": {"moniker": "B"}, "operator_address": "atonevaloper1b", "jailed": True},
        ]
        infos = [
            {"address": address_b, "missed_blocks_counter": "4", "start_height": "1",
             "index_offset": "2", "tombstoned": False},
            {"address": address_a, "missed_blocks_counter": "4", "start_height": "1",
             "index_offset": "3", "tombstoned": False},
            {"address": "atonevalcons1inactive", "missed_blocks_counter": "100",
             "start_height": "1", "index_offset": "1", "tombstoned": False},
        ]
        async def paginate(_name, path, _field):
            return validators if "validators" in path else infos
        service._paginate = paginate
        result = await service._top_missed(10, validators)
        self.assertEqual([item["operator_address"] for item in result],
                         ["atonevaloper1a", "atonevaloper1b"])
        self.assertEqual([item["remaining_misses_before_threshold"] for item in result], [6, 6])
