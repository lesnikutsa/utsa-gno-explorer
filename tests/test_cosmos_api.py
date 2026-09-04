import copy
import asyncio
import json
from pathlib import Path
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.cosmos.errors import AllEndpointsUnavailable, TransactionNotFound
from api.cosmos import RequestCache
from api.cosmos.registry import ATOMONE, AssetConfig, NetworkDefinition
from api.cosmos.config import CosmosNetworkConfig
from api.cosmos.schemas import MarketHistoryResponse, MarketResponse, OverviewResponse
from api.cosmos.service import CosmosService, consensus_address
import httpx

ATOMONE_FIXTURES = Path(__file__).parent / "fixtures" / "cosmos" / "atomone"


def atomone_fixture(name):
    return json.loads((ATOMONE_FIXTURES / name).read_text())


OVERVIEW = {
    "network": {"network_id": "atomone-mainnet", "family": "cosmos", "display_name": "AtomOne",
        "network_name": "Mainnet", "chain_id": "atomone-1", "operational_state": "healthy",
        "current_local_height": 42, "latest_block_time": "2026-08-29T12:34:56.123456Z",
        "catching_up": False, "tx_index": "on", "node_version": "0.38.0",
        "application_name": "atomoned", "application_version": "1.0.0", "sdk_version": "0.47.0",
        "cometbft_version": "0.38.0", "generated_at": "2026-08-29T12:35:00Z",
        "block_history_state": "unknown", "historical_state": "unknown"},
    "assets_and_supply": {"assets": [
        {"base": "uatone", "display": "atone", "symbol": "ATONE", "exponent": 6, "total_supply": "1000000"},
        {"base": "uphoton", "display": "photon", "symbol": "PHOTON", "exponent": 6, "total_supply": "2000000"}]},
    "staking": {"bonded_tokens": "10", "not_bonded_tokens": "2", "bonded_ratio": "0.833333",
        "active_validator_count": 1, "max_validators": 100, "unbonding_time": "1814400s", "max_entries": 7,
        "historical_entries": 10000, "bond_denom": "uatone", "min_commission_rate": "0.05",
        "max_commission_rate": "0.2", "key_rotation_fee": {"denom": "uatone", "amount": "1000"}},
    "mint": {"current_inflation": "0.1", "inflation_min": "0.07", "inflation_max": "0.2",
        "inflation_rate_change": "0.13", "goal_bonded": "0.67", "blocks_per_year": 6311520},
    "slashing": {"signed_blocks_window": 100, "minimum_signed_per_window": "0.5",
        "allowed_missed_threshold": 50, "downtime_jail_duration": "600s",
        "double_sign_slash_fraction": "0.05", "downtime_slash_fraction": "0.01"},
    "distribution": {"community_tax": "0.02", "withdraw_address_enabled": True,
        "community_pool": {"uatone": "10.5", "uphoton": "2.5"},
        "nakamoto_bonus": {"enabled": True, "step": "0.1", "period_epoch_identifier": "week",
            "minimum_coefficient": "0.5", "maximum_coefficient": "1.5"}},
    "governance": {"minimum_deposit": {"uatone": "100", "uphoton": "0"},
        "maximum_deposit_period": "1209600s", "voting_period": "604800s", "quorum": "0.4", "threshold": "0.5",
        "advanced": {"law_quorum": "0.5", "law_threshold": "0.6", "constitution_amendment_quorum": "0.6",
            "constitution_amendment_threshold": "0.75", "quorum_timeout": "86400s",
            "maximum_voting_period_extension": "86400s", "governor_status_change_period": "604800s",
            "minimum_governor_self_delegation": "1000000",
            "quorum_range": {"min": "0.3", "max": "0.5"},
            "law_quorum_range": {"min": "0.4", "max": "0.6"},
            "constitution_amendment_quorum_range": {"min": "0.5", "max": "0.7"}}},
    "top_active_validators_by_missed_blocks": []}


class FakeDatabase:
    def open(self, _config): pass
    def close(self): pass


class CosmosRouteTests(unittest.TestCase):
    def setUp(self):
        from api import app as module
        self.module = module
        self.patches = [patch.object(module, "database", FakeDatabase()),
                        patch.object(module, "load_config", return_value=ApiConfig("postgresql://test"))]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_overview_contract_healthy_syncing_partial_and_unknown(self):
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.overview = AsyncMock(return_value=copy.deepcopy(OVERVIEW))
            response = client.get("/api/networks/atomone-mainnet/overview")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("utsa.tech", response.text)
            syncing = copy.deepcopy(OVERVIEW)
            syncing["network"].update(operational_state="syncing", catching_up=True)
            service.overview = AsyncMock(return_value=syncing)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/overview").json()["network"]["operational_state"], "syncing")
            partial = copy.deepcopy(OVERVIEW)
            partial["network"]["operational_state"] = "degraded"
            partial["governance"] = {"error": {"code": "section_unavailable"}}
            service.overview = AsyncMock(return_value=partial)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/overview").status_code, 200)
            self.assertEqual(client.get("/api/networks/unknown/overview").status_code, 404)

    def test_controlled_chain_and_market_failures(self):
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.overview = AsyncMock(side_effect=AllEndpointsUnavailable("secret upstream"))
            response = client.get("/api/networks/atomone-mainnet/overview")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret upstream", response.text)
            service.market = AsyncMock(side_effect=RuntimeError("secret market"))
            response = client.get("/api/networks/atomone-mainnet/market")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret market", response.text)

    def test_unknown_validators_network_preserves_not_found(self):
        with TestClient(self.module.app) as client:
            response = client.get("/api/networks/unknown/validators")
            self.assertEqual(response.status_code, 404)

    def test_market_exact_contract(self):
        market = {"network_id": "atomone-mainnet", "currency": "USD", "price": "1.25",
                  "market_cap": "1000000", "change_24h": "-2.5",
                  "change_7d": None, "change_30d": None,
                  "source_last_updated_at": "2026-08-29T12:35:00Z"}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.market = AsyncMock(return_value=market)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/market").json(), market)

    def test_market_history_contract_is_bounded_and_failures_are_sanitized(self):
        history = {"network_id": "atomone-mainnet", "currency": "USD", "points": [
            {"timestamp": 1788000000000, "price": "1.2"},
            {"timestamp": 1788000300000, "price": "1.3"}]}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.market_history = AsyncMock(return_value=history)
            response = client.get("/api/networks/atomone-mainnet/market/history")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), history)
            service.market_history = AsyncMock(side_effect=RuntimeError("SECRET_MARKET_HISTORY"))
            response = client.get("/api/networks/atomone-mainnet/market/history")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("SECRET_MARKET_HISTORY", response.text)

    def test_blocks_and_lookup_contracts_and_validation(self):
        block = {"height": 42, "hash": "AA", "timestamp": "2026-08-29T12:34:56.123456Z",
                 "proposer": "BB", "transaction_count": 0}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.blocks = AsyncMock(return_value={"source": "rpc_metadata", "blocks": [block]})
            response = client.get("/api/networks/atomone-mainnet/blocks?limit=10")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["blocks"], [block])
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks?limit=0").status_code, 422)
            self.assertEqual(client.get("/api/networks/unknown/blocks").status_code, 404)
            for state in ("available", "future", "node_not_synced", "history_unavailable"):
                payload = {"state": state, "local_height": 42, "source": "rpc",
                           "block": block if state == "available" else None, "eta": None,
                           "eta_unavailable_reason": "insufficient_history" if state == "future" else None}
                service.block_lookup = AsyncMock(return_value=payload)
                lookup = client.get("/api/networks/atomone-mainnet/blocks/42")
                self.assertEqual(lookup.status_code, 200, lookup.text)
                self.assertEqual(lookup.json()["state"], state)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/blocks/0").status_code, 422)

    def test_transaction_hash_lookup_contract_and_errors(self):
        tx_hash = "ab" * 32
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.transaction_lookup = AsyncMock(return_value={
                "height": 42, "index": 3, "tx_hash": tx_hash.upper()})
            response = client.get(f"/api/networks/atomone-mainnet/transactions/{tx_hash}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"height": 42, "index": 3, "tx_hash": tx_hash.upper()})
            self.assertEqual(client.get("/api/networks/atomone-mainnet/transactions/not-a-hash").status_code, 422)
            service.transaction_lookup = AsyncMock(side_effect=TransactionNotFound("missing"))
            self.assertEqual(client.get(f"/api/networks/atomone-mainnet/transactions/{tx_hash}").status_code, 404)
            service.transaction_lookup = AsyncMock(side_effect=AllEndpointsUnavailable("index disabled"))
            self.assertEqual(client.get(f"/api/networks/atomone-mainnet/transactions/{tx_hash}").status_code, 503)

    def test_block_routes_sanitize_upstream_failures(self):
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.blocks = AsyncMock(side_effect=RuntimeError("SECRET_RPC_URL"))
            response = client.get("/api/networks/atomone-mainnet/blocks")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("SECRET_RPC_URL", response.text)


class CosmosUpstreamIntegrationTests(unittest.TestCase):
    def handler(self, *, malformed_mint=False, negative_market=False, counters=None):
        base = atomone_fixture("base.json")
        staking = atomone_fixture("staking_params.json")
        distribution = atomone_fixture("distribution_params.json")
        governance = atomone_fixture("governance_params.json")
        validators = atomone_fixture("validators.json")
        address_a = consensus_address(validators["validators"][0]["consensus_pubkey"], "atonevalcons")
        address_b = consensus_address(validators["validators"][1]["consensus_pubkey"], "atonevalcons")
        async def handle(request):
            if counters is not None:
                counters[str(request.url)] = counters.get(str(request.url), 0) + 1
            path = request.url.path
            if path == "/status":
                return httpx.Response(200, json={"result":{"node_info":{"network":"atomone-1","version":"0.38.0","other":{"tx_index":"on"}},"sync_info":{"latest_block_height":"42","latest_block_time":"2026-08-29T12:34:56Z","catching_up":False}}})
            if path == "/cosmos/base/tendermint/v1beta1/blocks/latest":
                return httpx.Response(200, json={"block_id":{"hash":"AA"},"block":{"header":{"chain_id":"atomone-1","height":"42","time":"2026-08-29T12:34:56Z","proposer_address":"AA"},"data":{"txs":[]}}})
            if path == "/cosmos/base/tendermint/v1beta1/node_info": return httpx.Response(200, json=base["node_info"])
            if path == "/cosmos/bank/v1beta1/supply/by_denom":
                denom = request.url.params["denom"]
                amount = "153847948212982" if denom == "uatone" else "2000000000"
                return httpx.Response(200, json={"amount":{"denom":denom,"amount":amount}})
            if path == "/cosmos/staking/v1beta1/pool": return httpx.Response(200, json=base["staking_pool"])
            if path == "/cosmos/staking/v1beta1/params": return httpx.Response(200, json=staking)
            if path == "/cosmos/staking/v1beta1/validators": return httpx.Response(200, json=validators)
            if path == "/cosmos/mint/v1beta1/inflation":
                payload = copy.deepcopy(base["mint_inflation"])
                if malformed_mint: payload["inflation"] = "1e100000"
                return httpx.Response(200, json=payload)
            if path == "/cosmos/mint/v1beta1/params": return httpx.Response(200, json=base["mint_params"])
            if path == "/cosmos/slashing/v1beta1/params": return httpx.Response(200, json=base["slashing"])
            if path == "/cosmos/slashing/v1beta1/signing_infos":
                return httpx.Response(200, json={"info":[
                    {"address":address_a,"start_height":"1","index_offset":"2","jailed_until":"1970-01-01T00:00:00Z","tombstoned":False,"missed_blocks_counter":"5"},
                    {"address":address_b,"start_height":"1","index_offset":"3","jailed_until":"1970-01-01T00:00:00Z","tombstoned":False,"missed_blocks_counter":"4"}],"pagination":{"next_key":None,"total":"140"}})
            if path == "/cosmos/distribution/v1beta1/params": return httpx.Response(200, json=distribution)
            if path == "/cosmos/distribution/v1beta1/community_pool": return httpx.Response(200, json=base["community_pool"])
            if path == "/cosmos/gov/v1/params/voting": return httpx.Response(200, json=governance)
            if path == "/api/v3/coins/atomone":
                return httpx.Response(200, json={
                    "id": "atomone",
                    "last_updated": "2026-08-29T12:35:00Z",
                    "market_data": {
                        "current_price": {"usd": -1.2 if negative_market else 1.2},
                        "market_cap": {"usd": 1000},
                        "price_change_percentage_24h": -2.5,
                        "price_change_percentage_7d": 3.25,
                        "price_change_percentage_30d": -4.5}})
            if path == "/api/v3/coins/atomone/market_chart":
                return httpx.Response(200, json={"prices": [[1788000000000 + index * 300000, 1 + index / 1000] for index in range(120)]})
            return httpx.Response(501, json={"error":"wrong route"})
        return handle

    def make_service(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        return client, CosmosService(ATOMONE, client=client, cache=RequestCache())

    def test_realistic_upstream_to_service_to_route_and_cache(self):
        from api import app as module
        counters = {}
        upstream, service = self.make_service(self.handler(counters=counters))
        fake = FakeDatabase()
        with patch.object(module, "database", fake), patch.object(module, "load_config", return_value=ApiConfig("postgresql://test")), TestClient(module.app) as client:
            client.app.state.cosmos_services["atomone-mainnet"] = service
            first = client.get("/api/networks/atomone-mainnet/overview")
            second = client.get("/api/networks/atomone-mainnet/overview")
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertEqual(Decimal(body["staking"]["bonded_ratio"]).quantize(Decimal("0.000001")), Decimal("0.395072"))
        self.assertEqual(body["staking"]["active_validator_count"], 2)
        self.assertEqual(body["staking"]["key_rotation_fee"], {"denom":"uatone","amount":"1000000"})
        self.assertTrue(body["network"]["rpc_pool"])
        rpc = body["network"]["rpc_pool"][0]
        self.assertEqual(set(rpc), {"host", "latency_ms", "height", "state", "selected"})
        self.assertNotIn("https://", rpc["host"])
        self.assertNotIn("@", rpc["host"])
        self.assertEqual(body["distribution"]["nakamoto_bonus"]["period_epoch_identifier"], "week")
        self.assertEqual(body["governance"]["advanced"]["quorum_range"], {"min":"0.300000000000000000","max":"0.500000000000000000"})
        self.assertEqual([item["moniker"] for item in body["top_active_validators_by_missed_blocks"]],
                         ["Silk Nodes", "atonevaloper1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"])
        second_body = second.json()
        body["network"].pop("generated_at")
        second_body["network"].pop("generated_at")
        self.assertEqual(body, second_body)
        supply_calls = sum(count for url, count in counters.items() if "/supply/by_denom" in url)
        self.assertEqual(supply_calls, 2)
        self.assertFalse(any("/atomone/" in url for url in counters))
        asyncio.run(upstream.aclose())

    def test_malformed_optional_section_is_isolated(self):
        upstream, service = self.make_service(self.handler(malformed_mint=True))
        result = asyncio.run(service.overview())
        self.assertEqual(result["network"]["operational_state"], "degraded")
        self.assertEqual(result["mint"], {"error":{"code":"section_unavailable"}})
        self.assertIn("assets", result["assets_and_supply"])
        asyncio.run(upstream.aclose())

    def test_negative_market_price_is_controlled_503(self):
        from api import app as module
        upstream, service = self.make_service(self.handler(negative_market=True))
        with patch.object(module, "database", FakeDatabase()), patch.object(
                module, "load_config", return_value=ApiConfig("postgresql://test")), TestClient(module.app) as client:
            client.app.state.cosmos_services["atomone-mainnet"] = service
            response = client.get("/api/networks/atomone-mainnet/market")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail":"Market data is temporarily unavailable"})
        asyncio.run(upstream.aclose())

    def test_market_history_is_validated_downsampled_and_cached(self):
        counters = {}
        upstream, service = self.make_service(self.handler(counters=counters))
        first = asyncio.run(service.market_history())
        second = asyncio.run(service.market_history())
        self.assertEqual(first, second)
        self.assertEqual(len(first["points"]), 96)
        self.assertEqual(first["points"][0]["timestamp"], 1788000000000)
        self.assertEqual(first["points"][-1]["timestamp"], 1788000000000 + 119 * 300000)
        self.assertEqual(sum(count for url, count in counters.items() if "/market_chart" in url), 1)
        self.assertEqual(MarketHistoryResponse.model_validate(first).network_id, "atomone-mainnet")
        asyncio.run(upstream.aclose())

    def test_validator_identity_enrichment_uses_consensus_key_and_falls_back(self):
        validators = atomone_fixture("validators.json")["validators"]
        identities = CosmosService._validator_identities(validators)
        self.assertEqual(len(identities), 1)
        identity = next(iter(identities.values()))
        self.assertEqual(identity["proposer_moniker"], "Silk Nodes")
        self.assertTrue(identity["proposer_operator_address"].startswith("atonevaloper"))
        with_identity = copy.deepcopy(validators[0])
        with_identity["description"]["identity"] = "9E7A59BBDC93CC32"
        enriched = next(iter(CosmosService._validator_identities([with_identity]).values()))
        self.assertEqual(enriched["proposer_identity"], "9E7A59BBDC93CC32")
        self.assertEqual(CosmosService._validator_identities([{"bad": "validator"}]), {})

    def test_generic_public_models_accept_one_asset_without_atomone_extensions(self):
        definition = NetworkDefinition(
            transport=CosmosNetworkConfig(network_id="cosmos-test", chain_id="cosmos-test-1",
                rpc_endpoints=("https://rpc.example",), rest_endpoints=("https://rest.example",)),
            family="cosmos", display_name="Cosmos Test", network_name="Testnet",
            account_prefix="test", validator_operator_prefix="testvaloper",
            validator_consensus_prefix="testvalcons", coin_type=118,
            assets=(AssetConfig("utest", "test", "TEST", 3),), coingecko_id="cosmos-test")
        generic = copy.deepcopy(OVERVIEW)
        generic["network"].update(network_id="cosmos-test", display_name="Cosmos Test", chain_id="cosmos-test-1")
        generic["assets_and_supply"] = {"assets":[{"base":"utest","display":"test","symbol":"TEST","exponent":3,"total_supply":"10"}]}
        generic["staking"]["bond_denom"] = "utest"
        generic["staking"]["key_rotation_fee"] = {"denom":"utest","amount":"1"}
        generic["distribution"]["community_pool"] = {"utest":"0"}
        generic["distribution"]["nakamoto_bonus"] = None
        generic["governance"]["minimum_deposit"] = {"utest":"1"}
        generic["governance"]["advanced"] = None
        self.assertEqual(OverviewResponse.model_validate(generic).network.network_id, "cosmos-test")
        self.assertEqual(len(definition.assets), 1)
        self.assertEqual(MarketResponse.model_validate({"network_id":"cosmos-test","currency":"USD","price":"1",
            "market_cap":"2","change_24h":"-1","source_last_updated_at":"2026-08-29T12:35:00Z"}).network_id, "cosmos-test")
