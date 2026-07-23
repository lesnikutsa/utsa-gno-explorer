import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendNetworkProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile_path = ROOT / "frontend/src/config/networkProfile.js"
        cls.profile = cls.profile_path.read_text()
        cls.sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
        cls.logo = (ROOT / "frontend/src/components/UtsaLogo.jsx").read_text()
        cls.overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.app = (ROOT / "frontend/src/App.jsx").read_text()

    def test_profile_uses_public_vite_values_with_fallbacks(self):
        self.assertTrue(self.profile_path.is_file())
        self.assertIn("import.meta.env", self.profile)
        self.assertNotIn("process.env", self.profile)
        for name in (
            "VITE_PROJECT_NAME", "VITE_NETWORK_NAME", "VITE_PROJECT_DESCRIPTION",
            "VITE_PROJECT_WEBSITE", "VITE_PROJECT_DOCUMENTATION", "VITE_PROJECT_GITHUB",
        ):
            self.assertIn(f"import.meta.env.{name}", self.profile)
        self.assertIn("typeof value === 'string'", self.profile)
        self.assertIn("value.trim() ? value.trim() : fallback", self.profile)
        self.assertIn("'Gno.land'", self.profile)
        self.assertIn("'Topaz'", self.profile)
        self.assertEqual(self.profile.count("Object.freeze("), 2)
        self.assertIn("export const networkProfile", self.profile)
        self.assertIn("export default networkProfile", self.profile)

    def test_sidebar_contains_only_complete_navigation(self):
        self.assertIn("networkProfile", self.sidebar)
        items = re.findall(r"\{ label: '([^']+)', Icon: \w+, href: '([^']+)' \}", self.sidebar)
        self.assertEqual(items, [("Overview", "/"), ("Blocks", "/blocks"), ("Validators", "/validators")])
        self.assertNotIn("NetworkIcon", self.sidebar)
        self.assertNotIn("MapIcon", self.sidebar)
        self.assertNotIn("is-disabled", self.sidebar)
        self.assertIn("`${networkProfile.projectName} · ${chainId}`", self.sidebar)
        self.assertIn("chainId ?", self.sidebar)

    def test_brand_uses_profile_and_preserves_logo(self):
        self.assertIn("networkProfile", self.logo)
        self.assertIn("{networkProfile.projectName} Explorer", self.logo)
        self.assertIn("`UTSA ${networkProfile.projectName} Explorer`", self.logo)
        self.assertIn("'/assets/utsa-logo.png'", self.logo)
        self.assertIn('<div className="brand__asset" aria-hidden="true">', self.logo)

    def test_overview_preserves_map_preview_and_profiles_footer(self):
        for text in ("Peers & Decentralization Map", "Coming soon", "Total Peers", "Countries", "Decentralization"):
            self.assertIn(text, self.overview)
        self.assertIn('/assets/network-map.png?v=1', self.overview)
        self.assertIn("network-preview__mascot", self.overview)
        self.assertIn("{networkProfile.projectName} Explorer by UTSA", self.overview)
        self.assertNotIn("Explore Network", self.overview)
        self.assertNotIn('href="/network"', self.overview)

    def test_app_updates_existing_metadata_without_network_route(self):
        self.assertIn("import { networkProfile }", self.app)
        self.assertIn("useEffect(() => {", self.app)
        self.assertLess(self.app.index("useEffect(() => {"), self.app.index("if (path ==="))
        self.assertIn("document.title = `${networkProfile.projectName} Explorer`", self.app)
        self.assertIn("document.querySelector('meta[name=\"description\"]')", self.app)
        self.assertIn("descriptionMeta.setAttribute('content', networkProfile.description)", self.app)
        self.assertNotIn("'/network'", self.app)
        self.assertNotIn("NetworkPage", self.app)
        self.assertNotIn("useNetworkPage", self.app)

    def test_experimental_files_dependencies_and_css_are_out_of_scope(self):
        self.assertFalse((ROOT / "frontend/src/pages/Network.jsx").exists())
        self.assertFalse((ROOT / "frontend/src/hooks/useNetworkPage.js").exists())
        package = (ROOT / "frontend/package.json").read_text().lower()
        for dependency in ("react-router", "leaflet", "maplibre"):
            self.assertNotIn(dependency, package)


if __name__ == "__main__":
    unittest.main()
