import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAverageBlockTimeTests(unittest.TestCase):
    def test_formatter_outputs(self):
        helper = ROOT / "frontend/src/utils/blockTime.js"
        self.assertTrue(helper.is_file())
        script = f"""
import {{ formatAverageBlockTime as f }} from {json.dumps(helper.as_uri())};
console.log(JSON.stringify([f(null), f(undefined), f('3'), f(NaN), f(Infinity), f(0), f(-1), f(3.1842), f(12.44), f(59.96), f(60), f(65), f(119.6), f(125.4)]));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ["—", "—", "—", "—", "—", "—", "—", "3.18s", "12.4s", "60.0s", "1m 00s", "1m 05s", "2m 00s", "2m 05s"])

    def test_overview_preserves_panel_and_uses_api_metric(self):
        source = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        for text in ("formatAverageBlockTime", "average_block_time_seconds", "average_block_time_sample_size", "Avg Block Time", "Total Peers", "Countries", "Peers & Decentralization Map", "Coming soon", "/assets/network-map.png", "mascotSrc", "Average across", "indexed blocks", "intervals"):
            self.assertIn(text, source)
        self.assertNotIn("<span>Decentralization</span>", source)
        self.assertNotRegex(source, r"fetch\(|axios")
        self.assertNotRegex(source, r"time_utc\s*-")

    def test_update_highlight_contract(self):
        source = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        css = (ROOT / "frontend/src/styles/app.css").read_text()
        self.assertIn("previousAverageBlockTime.current !== averageBlockTime", source)
        self.assertIn("previousAverageBlockTime.current !== null", source)
        self.assertIn("window.setTimeout", source)
        self.assertIn("}, 800)", source)
        self.assertGreaterEqual(source.count("window.clearTimeout(averageBlockTimeTimer.current)"), 2)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(".network-preview__metric-value--updating", css)

    def test_scope_has_no_new_dependencies_or_network_route(self):
        package = json.loads((ROOT / "frontend/package.json").read_text())
        dependencies = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
        self.assertFalse(any("chart" in item.lower() or "map" in item.lower() for item in dependencies))
        source = "\n".join(path.read_text() for path in (ROOT / "frontend/src").rglob("*.jsx"))
        self.assertNotIn('path="/network"', source)


if __name__ == "__main__":
    unittest.main()
