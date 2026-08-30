import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.cosmos.errors import AllEndpointsUnavailable


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
        "max_commission_rate": "0.2", "key_rotation_fee": "1000"},
    "mint": {"current_inflation": "0.1", "inflation_min": "0.07", "inflation_max": "0.2",
        "inflation_rate_change": "0.13", "goal_bonded": "0.67", "blocks_per_year": 6311520},
    "slashing": {"signed_blocks_window": 100, "minimum_signed_per_window": "0.5",
        "allowed_missed_threshold": 50, "downtime_jail_duration": "600s",
        "double_sign_slash_fraction": "0.05", "downtime_slash_fraction": "0.01"},
    "distribution": {"community_tax": "0.02", "withdraw_address_enabled": True,
        "community_pool": {"uatone": "10.5", "uphoton": "2.5"},
        "nakamoto_bonus": {"enabled": True, "step": "0.1", "period": "86400s",
            "minimum_coefficient": "0.5", "maximum_coefficient": "1.5"}},
    "governance": {"minimum_deposit": {"uatone": "100", "uphoton": "0"},
        "maximum_deposit_period": "1209600s", "voting_period": "604800s", "quorum": "0.4", "threshold": "0.5",
        "advanced": {"law_quorum": "0.5", "law_threshold": "0.6", "constitution_amendment_quorum": "0.6",
            "constitution_amendment_threshold": "0.75", "quorum_timeout": "86400s",
            "maximum_voting_period_extension": "86400s", "governor_status_change_period": "604800s",
            "minimum_governor_self_delegation": "1000000", "quorum_ranges": ["0.3", "0.5"]}},
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

    def test_market_exact_contract(self):
        market = {"network_id": "atomone-mainnet", "currency": "USD", "price": "1.25",
                  "market_cap": "1000000", "change_24h": "-2.5",
                  "source_last_updated_at": "2026-08-29T12:35:00Z"}
        with TestClient(self.module.app) as client:
            service = client.app.state.cosmos_services["atomone-mainnet"]
            service.market = AsyncMock(return_value=market)
            self.assertEqual(client.get("/api/networks/atomone-mainnet/market").json(), market)
