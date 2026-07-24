import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FrontendNetworkDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (ROOT / "frontend/src/services/api.js").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useExplorerData.js").read_text()
        cls.overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.panel = (ROOT / "frontend/src/components/NetworkDistributionPanel.jsx").read_text()

    def test_api_service_uses_shared_request(self):
        self.assertIn("export const getNetworkDistribution", self.api)
        self.assertIn("request('/network/distribution')", self.api)
        for source in (self.overview, self.panel):
            self.assertNotRegex(source, r"fetch\(|axios")

    def test_hook_uses_existing_slow_poll_and_preserves_stale_data(self):
        for value in ("getNetworkDistribution", "distribution: null", "distribution: false", "distribution.status === 'fulfilled' ? distribution.value : current.distribution", "distribution: distribution.status === 'rejected'"):
            self.assertIn(value, self.hook)
        self.assertIn("SLOW_POLL_MS = 15_000", self.hook)
        self.assertEqual(self.hook.count("window.setTimeout("), 2)
        health_logic = self.hook.split("let healthState", 1)[1]
        self.assertNotIn("errors.distribution", health_logic)

    def test_component_content_and_independent_expansion(self):
        for value in ("Visible Peers", "Countries", "Providers", "Observed Network Distribution", "Regions", "Providers / ASN Organizations", "Show all", "Show top 10", "DISTRIBUTION_TOP_LIMIT = 10", "showAllCountries", "showAllProviders", "/assets/network-map.png?v=1", "mascotSrc"):
            self.assertIn(value, self.panel)
        self.assertNotIn("Coming soon", self.panel)
        self.assertNotIn("Total Peers", self.panel)

    def test_country_flag_helper(self):
        helper = ROOT / "frontend/src/utils/countryFlag.js"
        script = f'''import {{ countryFlag as f }} from {json.dumps(helper.as_uri())};\nconsole.log(JSON.stringify([f('FI'), f('DE'), f('US'), f('fi'), f('USA'), f('1A'), f(null), f(undefined)]));'''
        result = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["🇫🇮", "🇩🇪", "🇺🇸", "", "", "", "", ""])

    def test_privacy_and_accessibility(self):
        source = self.panel + self.hook
        for forbidden in ("peer_arrays", ".node_id", "rpc_url", "coordinates", "source-detail", "geo-cache"):
            self.assertNotIn(forbidden, source.lower())
        for required in ('aria-expanded', 'aria-controls', '<time dateTime=', 'aria-hidden="true"'):
            self.assertIn(required, self.panel)

    def test_dependencies_and_routes_unchanged(self):
        package = json.loads((ROOT / "frontend/package.json").read_text())
        dependencies = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
        self.assertFalse(any(token in dependency.lower() for dependency in dependencies for token in ("chart", "leaflet", "maplibre", "react-router")))
        jsx = "\n".join(path.read_text() for path in (ROOT / "frontend/src").rglob("*.jsx"))
        self.assertNotIn('path="/network"', jsx)
        self.assertFalse((ROOT / "frontend/src/pages/Network.jsx").exists())


if __name__ == "__main__":
    unittest.main()
