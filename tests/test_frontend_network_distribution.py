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
        cls.validators = (ROOT / "frontend/src/pages/Validators.jsx").read_text()
        cls.css = (ROOT / "frontend/src/styles/app.css").read_text()
        cls.theme = (ROOT / "frontend/src/styles/theme.css").read_text()
        cls.main = (ROOT / "frontend/src/main.jsx").read_text()
        cls.formatter = ROOT / "frontend/src/utils/networkDistributionFormat.js"

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
        self.assertIn('className="distribution-ranking__position power-rank">#{index + 1}</span>', self.panel)
        self.assertIn('className="power-rank">#{row.powerRank}</span>', self.validators)
        self.assertIn('.power-rank {', self.css)

    def test_rpc_summary_is_dynamic_and_pluralized(self):
        self.assertIn("snapshot?.rpc_sources?.total === 1 ? 'RPC source' : 'RPC sources'", self.panel)
        self.assertIn("${sourcesOk}/${sourcesTotal} ${rpcSourceLabel}", self.panel)
        self.assertIn("Based on unique public IPs", self.panel)

    def test_country_flag_helper(self):
        helper = ROOT / "frontend/src/utils/countryFlag.js"
        script = f'''import {{ countryFlag as f }} from {json.dumps(helper.as_uri())};\nconsole.log(JSON.stringify([f('FI'), f('DE'), f('US'), f('fi'), f('USA'), f('1A'), f(null), f(undefined)]));'''
        result = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["fi fi-fi", "fi fi-de", "fi fi-us", "", "", "", "", ""])

    def test_flags_are_bundled_classes_without_remote_loading(self):
        helper = (ROOT / "frontend/src/utils/countryFlag.js").read_text()
        package = json.loads((ROOT / "frontend/package.json").read_text())
        self.assertEqual(package["dependencies"]["flag-icons"], "7.5.0")
        self.assertIn("flag-icons/css/flag-icons.min.css", self.main)
        self.assertIn('className={`distribution-ranking__flag ${flag}`}', self.panel)
        self.assertIn('aria-hidden="true"', self.panel)
        self.assertIn("item.name", self.panel)
        for source in (helper, self.panel, self.main):
            self.assertNotRegex(source, r"flagcdn|cdn\.|https?://|fetch\(")
        self.assertNotIn("String.fromCodePoint", helper)

    def test_toggle_style_remains_quiet(self):
        toggle = self.css.split(".distribution__toggle {", 1)[1].split("}", 1)[0]
        self.assertIn("var(--color-text-secondary)", toggle)
        self.assertIn("rgba(9,24,39,.32)", toggle)
        self.assertNotRegex(toggle, r"(?<!-)width:\s*100%")
        self.assertIn("width: fit-content", toggle)
        self.assertIn("min-width: 100px", toggle)
        self.assertIn("margin: 7px auto 0", toggle)
        self.assertIn("min-height: 22px", toggle)
        self.assertIn("font-family: var(--font-ui)", toggle)
        self.assertIn("font-size: 10px", toggle)
        self.assertIn("font-weight: 400", toggle)
        self.assertIn("line-height: 1.2", toggle)
        self.assertNotIn("var(--font-sans)", toggle)
        self.assertRegex(self.theme, r"--font-ui\s*:")
        self.assertIn("padding: 3px 10px", toggle)
        self.assertIn("text-align: center", toggle)
        self.assertNotIn("var(--color-accent)", toggle)

    def test_distribution_formatters(self):
        script = f'''
import {{ formatDistributionCount as count, formatDistributionPercent as percent, formatDistributionAsn as asn, validDistributionTimestamp as timestamp }} from {json.dumps(self.formatter.as_uri())};
console.log(JSON.stringify({{
  counts: [count(0), count(64), count(1234), count(null), count(undefined), count(''), count('64'), count(false), count(NaN), count(Infinity), count(-1), count(1.5)],
  percentages: [percent(0), percent(90.5), percent(98.44), percent(100), percent(null), percent(''), percent('98.44'), percent(-1), percent(100.01), percent(Infinity)],
  asns: [asn(24940), asn(51167), asn(1), asn(0), asn(-1), asn(1.5), asn(null), asn('24940'), asn(Infinity)],
  timestamps: [timestamp('2026-07-24T10:19:29.573347Z'), timestamp('invalid'), timestamp(''), timestamp(null), timestamp([]), timestamp({{}})],
}}));
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
        values = json.loads(result.stdout)
        self.assertEqual(values["counts"], ["0", "64", "1,234", "—", "—", "—", "—", "—", "—", "—", "—", "—"])
        self.assertEqual(values["percentages"], ["0%", "90.5%", "98.44%", "100%", "—", "—", "—", "—", "—", "—"])
        self.assertEqual(values["asns"], ["AS24940", "AS51167", "AS1", "", "", "", "", "", ""])
        self.assertNotIn(",", values["asns"][0])
        self.assertEqual(values["timestamps"], ["2026-07-24T10:19:29.573347Z", "", "", "", "", ""])

    def test_incomplete_snapshot_and_empty_list_contracts(self):
        for required in ("!Array.isArray(distribution)", "hasUsableSnapshot", "snapshot?.visible_node_ids", "No country distribution available.", "No provider distribution available."):
            self.assertIn(required, self.panel)
        self.assertIn("const asn = kind === 'provider' ? formatDistributionAsn(item?.asn) : ''", self.panel)
        self.assertIn("{asn && <span", self.panel)

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
