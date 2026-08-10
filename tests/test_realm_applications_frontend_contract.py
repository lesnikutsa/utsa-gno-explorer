import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RealmApplicationsFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_api_client_uses_bounded_window_endpoint(self):
        client = self.read("frontend/src/services/api.js")
        self.assertIn("export const getTopRealmApplications", client)
        script = """
          globalThis.fetch = async (url, options) => ({ok: true, json: async () => ({url, signal: Boolean(options.signal)})});
          const { getTopRealmApplications } = await import('./frontend/src/services/api.js');
          const controller = new AbortController();
          console.log(JSON.stringify(await getTopRealmApplications({limit: 3, window: '7d', signal: controller.signal})));
        """
        result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT,
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), {"url": "/api/realm-applications/top?limit=3&window=7d", "signal": True})

    def test_default_and_selector_windows(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("export const APPLICATIONS_LIMIT = 3", hook)
        self.assertIn("DEFAULT_APPLICATION_WINDOW = '24h'", hook)
        self.assertIn("APPLICATION_WINDOWS = ['24h', '7d', '30d']", hook)
        for label in ("'24h': '24H'", "'7d': '7D'", "'30d': '30D'"):
            self.assertIn(label, page)

    def test_selected_window_and_background_refresh(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        self.assertIn("window: selectedWindow", hook)
        self.assertIn("window: currentWindow.current", hook)
        self.assertIn("setItems([])", hook)
        self.assertIn("selectWindow", hook)
        self.assertIn("new AbortController()", hook)
        self.assertIn("id !== requestId.current", hook)
        self.assertNotIn("scope: 'curated'", hook)
        self.assertNotIn("getTopRealmNamespaces", hook)

    def test_optional_metadata_and_unknown_namespace_fallback(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("item.application === null", hook)
        self.assertIn("item.application.display_name : item.namespace_key", page)
        self.assertIn("item.application.category : 'Namespace'", page)
        self.assertNotIn("response.items.filter((item) => item.application", hook)

    def test_period_metrics_and_safe_unavailable_state(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        for fragment in ("Direct Calls (", "Success (", "called in", "Last activity",
                         "Complete activity history is not available for this period.", "windowUnavailable"):
            self.assertIn(fragment, page)
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        self.assertIn("requestError?.status === 409", hook)

    def test_coverage_disables_unavailable_windows(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("source?.available_windows", page)
        self.assertIn("!availableWindows.includes(value)", page)

    def test_responsive_balanced_three_card_layout(self):
        styles = self.read("frontend/src/styles/app.css")
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", styles)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", styles)
        self.assertIn(".realms-application-card__identity h3", styles)
        title_rule = styles[styles.index(".realms-application-card__identity h3"):]
        self.assertIn("overflow-wrap: anywhere", title_rule.split("}", 1)[0])

    def test_catalog_state_remains_independent(self):
        app = self.read("frontend/src/App.jsx")
        self.assertIn("const realmApplications = useRealmApplications()", app)
        self.assertIn("refreshApplications: realmApplications.refreshInBackground", app)
        self.assertIn("realmApplications={realmApplications}", app)


if __name__ == "__main__":
    unittest.main()
