import copy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from api.config import ApiConfig
from api.cosmos.errors import InvalidConfiguration
from api.cosmos.registry import ATOMONE, load_network_file, load_networks, public_networks
from unittest.mock import patch


CONFIG_PATH = Path(__file__).parents[1] / "networks" / "atomone-mainnet" / "network.json"


class CosmosRegistryTests(unittest.TestCase):
    def test_atomone_canonical_config_and_endpoint_order(self):
        self.assertEqual(ATOMONE.transport.rpc_endpoints, (
            "https://m-atomone.rpc.utsa.tech",
            "https://atomone-mainnet-rpc.itrocket.net",
        ))
        self.assertEqual(ATOMONE.transport.rest_endpoints, (
            "https://m-atomone.api.utsa.tech",
            "https://atomone-mainnet-api.itrocket.net",
        ))
        self.assertEqual(ATOMONE.logo_url,
            "https://raw.githubusercontent.com/lesnikutsa/explorer/master/public/logos/Atomone.png")

    def test_public_registry_omits_transport_and_market_configuration(self):
        public = public_networks()
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]["id"], "atomone-mainnet")
        self.assertNotIn("rpc_endpoints", public[0])
        self.assertNotIn("rest_endpoints", public[0])
        self.assertNotIn("coingecko_id", public[0])
        self.assertEqual(public[0]["capabilities"], ["overview", "blocks", "validators", "network-parameters"])

    def test_loader_rejects_unknown_fields_insecure_logo_and_directory_mismatch(self):
        original = json.loads(CONFIG_PATH.read_text())
        cases = []
        unknown = copy.deepcopy(original); unknown["unexpected"] = True; cases.append(unknown)
        logo = copy.deepcopy(original); logo["logo_url"] = "http://example.test/logo.png"; cases.append(logo)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, payload in enumerate(cases):
                path = root / f"invalid-{index}.json"
                path.write_text(json.dumps(payload))
                with self.subTest(index=index), self.assertRaises(InvalidConfiguration):
                    load_network_file(path)
            wrong = root / "wrong-name"; wrong.mkdir()
            (wrong / "network.json").write_text(json.dumps(original))
            with self.assertRaises(InvalidConfiguration):
                load_networks(root)


class _Database:
    def open(self, _config): pass
    def close(self): pass


class PublicRegistryRouteTests(unittest.TestCase):
    def test_public_route_has_safe_validated_metadata(self):
        from api import app as module
        with patch.object(module, "database", _Database()), patch.object(
                module, "load_config", return_value=ApiConfig("postgresql://test")), TestClient(module.app) as client:
            response = client.get("/api/networks")
        self.assertEqual(response.status_code, 200)
        network = response.json()["networks"][0]
        self.assertEqual(network["id"], "atomone-mainnet")
        self.assertTrue(network["logo_url"].startswith("https://"))
        self.assertFalse(any("endpoint" in key for key in network))
