import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendNetworkPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = (ROOT / "frontend/src/config/networkProfile.js").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useNetworkPage.js").read_text()
        cls.page = (ROOT / "frontend/src/pages/Network.jsx").read_text()
        cls.app = (ROOT / "frontend/src/App.jsx").read_text()
        cls.sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
        cls.overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.css = (ROOT / "frontend/src/styles/app.css").read_text()

    def test_public_profile_is_reusable(self):
        self.assertIn("import.meta.env", self.profile)
        for name in ("VITE_PROJECT_NAME", "VITE_NETWORK_NAME", "VITE_PROJECT_DESCRIPTION", "VITE_PROJECT_WEBSITE", "VITE_PROJECT_DOCUMENTATION", "VITE_PROJECT_GITHUB"):
            self.assertIn(name, self.profile)
        self.assertIn(".trim()", self.profile)
        self.assertIn("Object.freeze", self.profile)
        self.assertIn("'Gno.land'", self.profile)
        self.assertIn("'Topaz'", self.profile)
        self.assertNotIn("Gno.land", self.page)
        self.assertNotIn("Topaz", self.page)

    def test_hook_fetches_only_summary_sources_and_polls_safely(self):
        self.assertIn("import { getHealth, getNetwork } from '../services/api'", self.hook)
        self.assertIn("NETWORK_PAGE_POLL_MS = 15_000", self.hook)
        self.assertIn("Promise.allSettled([getHealth(), getNetwork()])", self.hook)
        self.assertIn("if (inFlight.current) return", self.hook)
        self.assertIn(": current.health", self.hook)
        self.assertIn(": current.network", self.hook)
        self.assertIn("mounted.current", self.hook)
        self.assertIn("window.clearTimeout(timer.current)", self.hook)

    def test_route_and_sidebar(self):
        self.assertIn("import { Network }", self.app)
        self.assertIn("import { useNetworkPage }", self.app)
        self.assertIn("path === '/network' || path === '/network/'", self.app)
        self.assertIn("<Network networkPage={networkPage} />", self.app)
        self.assertIn("href: '/network'", self.sidebar)
        self.assertNotIn("Peers & Map", self.sidebar)
        self.assertNotIn("is-disabled", self.sidebar)
        self.assertIn("networkProfile.projectName", self.sidebar)

    def test_page_uses_real_fields_and_honest_foundations(self):
        for text in ("Network Summary", "latest_block", "active_count", "chain_id", "selected_rpc", "Development Activity", "Peers &amp; Distribution", "/assets/network-map.png?v=1"):
            self.assertIn(text, self.page)
        self.assertIn('target="_blank" rel="noopener noreferrer"', self.page)
        for forbidden in ("0 commits", "0 contributors", "decentralization score", "fetch(", "/net_info", "IP address"):
            self.assertNotIn(forbidden, self.page)

    def test_overview_is_a_compact_entry_point(self):
        self.assertIn('href="/network"', self.overview)
        self.assertIn("Explore Network", self.overview)
        self.assertNotIn("Coming soon", self.overview)
        for metric in ("Total Peers", "Countries", "Decentralization</span>"):
            self.assertNotIn(metric, self.overview)
        self.assertIn("/assets/network-map.png?v=1", self.overview)
        self.assertIn("network-mascot", (ROOT / "frontend/src/App.jsx").read_text())

    def test_styles_and_dependencies(self):
        for class_name in ("network-page__header", "network-summary-grid", "network-page__empty-state", "network-map-foundation", "network-preview__cta"):
            self.assertIn(class_name, self.css)
        self.assertIn("@media", self.css)
        package = (ROOT / "frontend/package.json").read_text().lower()
        for dependency in ("google maps", "maplibre", "leaflet", "react-router"):
            self.assertNotIn(dependency, package)


if __name__ == "__main__":
    unittest.main()
