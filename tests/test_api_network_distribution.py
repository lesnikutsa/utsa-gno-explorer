import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.config import ApiConfig
from api.database import MissingIndexerStateError
from api.schemas import NetworkDistributionCountry, NetworkDistributionProvider, NetworkDistributionRegion

SECRET = "postgresql://user:secret@private/db"


def snapshot(**overrides):
    row = {
        "chain_id": "topaz-1", "source_kind": "tendermint_net_info",
        "scanned_at": datetime(2026, 7, 24, 10, 19, 29, 573347, tzinfo=timezone.utc),
        "rpc_sources_total": 3, "rpc_sources_ok": 3, "visible_node_ids": 64,
        "unique_public_ips": 64, "geolocated_node_ids": 64, "geolocated_public_ips": 64,
        "node_id_ip_conflicts": 0, "region_count": 1, "country_count": 1, "provider_count": 1,
        "regions": [{"name": "Europe", "count": 43}],
        "countries": [{"code": "FI", "name": "Finland", "count": 17}],
        "providers": [{"asn": 24940, "name": "Hetzner Online GmbH", "count": 21}],
    }
    row.update(overrides)
    return row


class FakeDatabase:
    def __init__(self, row=None, error=None): self.row, self.error = row, error
    def open(self, config): pass
    def close(self): pass
    def fetch_network_distribution(self):
        if self.error: raise self.error
        return self.row


class NetworkDistributionApiTests(unittest.TestCase):
    def client(self, fake):
        from api import app as module
        patches = [patch.object(module, "database", fake), patch.object(module, "load_config", return_value=ApiConfig(database_url=SECRET))]
        for item in patches: item.start(); self.addCleanup(item.stop)
        return TestClient(module.app)

    def test_success_contract_rounding_coverage_and_exclusions(self):
        with self.client(FakeDatabase(snapshot())) as client:
            response = client.get("/api/network/distribution")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"chain_id", "source_kind", "updated_at", "rpc_sources", "visible_node_ids", "unique_public_ips", "geolocated_node_ids", "geolocated_public_ips", "geolocation_coverage_percent", "node_id_ip_conflicts", "region_count", "country_count", "provider_count", "region_covered_public_ips", "country_covered_public_ips", "provider_covered_public_ips", "region_coverage_percent", "country_coverage_percent", "provider_coverage_percent", "regions", "countries", "providers"})
        self.assertEqual(data["updated_at"], "2026-07-24T10:19:29.573347Z")
        self.assertEqual(data["regions"][0]["share_percent"], 67.19)
        self.assertEqual(data["countries"][0]["share_percent"], 26.56)
        self.assertEqual(data["providers"][0]["share_percent"], 32.81)
        self.assertEqual(data["provider_coverage_percent"], 32.81)
        self.assertEqual(data["geolocation_coverage_percent"], 100.0)
        forbidden = {"id", "inserted_at", "ip", "node_id", "rpc_url", "sources"}
        self.assertTrue(forbidden.isdisjoint(data))

    def test_round_half_up_and_zero_denominator(self):
        row = snapshot(unique_public_ips=6, geolocated_public_ips=6, geolocated_node_ids=6,
                       visible_node_ids=6, regions=[{"name": "A", "count": 1}],
                       countries=[{"code": "US", "name": "US", "count": 0}],
                       providers=[{"asn": None, "name": "Provider", "count": 0}])
        with self.client(FakeDatabase(row)) as client: data = client.get("/api/network/distribution").json()
        self.assertEqual(data["regions"][0]["share_percent"], 16.67)
        zero = snapshot(unique_public_ips=0, geolocated_public_ips=0, geolocated_node_ids=0,
                        visible_node_ids=0, regions=[], countries=[], providers=[],
                        region_count=0, country_count=0, provider_count=0)
        with self.client(FakeDatabase(zero)) as client: data = client.get("/api/network/distribution").json()
        self.assertEqual(data["geolocation_coverage_percent"], 0.0)
        self.assertEqual(data["provider_coverage_percent"], 0.0)

    def test_missing_snapshot_is_404(self):
        with self.client(FakeDatabase(snapshot(scanned_at=None))) as client: response = client.get("/api/network/distribution")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Network distribution snapshot not found"})

    def test_missing_state_and_database_failure_are_sanitized_503(self):
        for error in (MissingIndexerStateError("missing"), RuntimeError(SECRET)):
            with self.subTest(error=type(error).__name__), self.client(FakeDatabase(error=error)) as client:
                response = client.get("/api/network/distribution")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": "Explorer database is unavailable"})
            self.assertNotIn(SECRET, response.text)

    def test_malformed_aggregates_are_sanitized_and_safely_logged(self):
        cases = [
            {"regions": {}}, {"countries": "bad"}, {"providers": ["bad"]},
            {"region_count": 2},
            {"countries": [{"code": "FI", "name": "Finland", "count": 8}, {"code": "FI", "name": "duplicate", "count": 9}], "country_count": 2},
            {"providers": [{"asn": None, "name": " ACME  Corp ", "count": 1}, {"asn": None, "name": "acme corp", "count": 1}], "provider_count": 2},
            {"regions": [{"name": "Europe", "count": 65}]},
        ]
        logger = logging.getLogger("api.app")
        for changes in cases:
            with self.subTest(changes=changes), self.assertLogs(logger, level="ERROR") as logs:
                with self.client(FakeDatabase(snapshot(**changes))) as client: response = client.get("/api/network/distribution")
            combined = response.text + " ".join(logs.output)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("ACME", combined); self.assertNotIn(SECRET, combined)
            self.assertNotIn("Traceback", combined)

    def test_schema_constraints(self):
        NetworkDistributionProvider(asn=None, name="Provider", count=0, share_percent=0)
        for model, kwargs in [
            (NetworkDistributionRegion, {"name": "", "count": 0, "share_percent": 0}),
            (NetworkDistributionCountry, {"code": "fi", "name": "Finland", "count": 0, "share_percent": 0}),
            (NetworkDistributionProvider, {"asn": 0, "name": "Provider", "count": 0, "share_percent": 0}),
            (NetworkDistributionRegion, {"name": "Europe", "count": -1, "share_percent": 0}),
            (NetworkDistributionRegion, {"name": "Europe", "count": 0, "share_percent": 101}),
        ]:
            with self.subTest(model=model.__name__), self.assertRaises(ValidationError): model(**kwargs)


if __name__ == "__main__": unittest.main()
