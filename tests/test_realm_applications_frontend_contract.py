import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RealmApplicationsFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_api_client_url_defaults_encoding_and_signal(self):
        client = self.read("frontend/src/services/api.js")
        self.assertIn("export const getTopRealmNamespaces", client)
        script = """
          globalThis.fetch = async (url, options) => ({
            ok: true,
            json: async () => ({ url, hasSignal: Boolean(options.signal) }),
          });
          const { getRealms, getTopRealmNamespaces } = await import('./frontend/src/services/api.js');
          const controller = new AbortController();
          const values = await Promise.all([
            getTopRealmNamespaces({ limit: 3, scope: 'curated', signal: controller.signal }),
            getTopRealmNamespaces(),
            getTopRealmNamespaces({ limit: '5 & more', scope: 'curated apps' }),
            getRealms({ limit: 25, kind: 'all' }),
          ]);
          console.log(JSON.stringify(values));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        explicit, defaults, encoded, realms = json.loads(result.stdout)
        self.assertEqual(explicit, {"url": "/api/realm-namespaces/top?limit=3&scope=curated", "hasSignal": True})
        self.assertEqual(defaults["url"], "/api/realm-namespaces/top?limit=3&scope=curated")
        self.assertEqual(encoded["url"], "/api/realm-namespaces/top?limit=5+%26+more&scope=curated+apps")
        self.assertEqual(realms["url"], "/api/realms?limit=25&kind=all")

    def test_hook_concurrency_errors_retry_and_defensive_filtering(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        for fragment in (
            "export const APPLICATIONS_LIMIT = 3",
            "import { getTopRealmNamespaces }",
            "new AbortController()",
            "id !== requestId.current",
            "mounted.current",
            "controller.current?.abort()",
            "requestError?.status === 404",
            "setSnapshotMissing(true)",
            "setError(true)",
            "scope: 'curated'",
            "retry: load",
            "Array.isArray(response.items)",
            "response.items.filter(isValidItem)",
            ".slice(0, APPLICATIONS_LIMIT)",
        ):
            self.assertIn(fragment, hook)
        self.assertNotIn("healthState", hook)
        self.assertNotIn("titleCase", hook)

    def test_app_wiring_keeps_catalog_health_independent(self):
        app = self.read("frontend/src/App.jsx")
        self.assertIn("import { useRealmApplications }", app)
        self.assertIn("const realmApplications = useRealmApplications()", app)
        self.assertIn("realmApplications={realmApplications}", app)
        self.assertIn("healthState={realmsPage.healthState}", app)
        self.assertNotIn("healthState={realmApplications", app)

    def test_presentation_and_independent_states(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        for fragment in (
            "Applications",
            "Curated Realm namespaces ranked by indexed direct calls",
            "Indexed direct-call metrics. Historical indexing starts at #",
            "live activity continues.",
            "source?.activity_from_height",
            "Direct Calls",
            "Called Realms",
            "Success Rate",
            "Last Activity",
            "Namespace:",
            "Loading applications…",
            "Applications are currently unavailable.",
            "Application ranking is not available yet.",
            "No curated applications are available yet.",
            "formatSuccessRate(item.success_rate)",
            "relativeTime(item.last_activity_at)",
            '<StatusBadge tone="neutral">',
            "<article",
            "<dl",
            "<dt>",
            "<dd>",
            'type="button" onClick={retry}',
            "item.application.display_name",
            "<RealmApplications applications={realmApplications} />",
            "onClick={loadOlder}",
        ):
            self.assertIn(fragment, page)
        applications_end = page.index("export function Realms")
        self.assertIn("error &&", page[:applications_end])
        self.assertIn("onClick={retry}", page[applications_end:])
        for forbidden in (
            "Verified", "Unverified", "Trending", "Popular", "All time",
            "Lifetime", "Since genesis", "dangerouslySetInnerHTML", "titleCase", '"GnoSwap"',
            "Activity metrics cover blocks", "source?.activity_through_height",
        ):
            self.assertNotIn(forbidden, page)

    def test_scoped_responsive_css(self):
        styles = self.read("frontend/src/styles/app.css")
        section = styles[styles.index("/* Realms catalog */"):styles.index("/* Account detail */")]
        for fragment in (
            ".realms-applications",
            ".realms-applications__grid",
            ".realms-application-card",
            "repeat(auto-fill, minmax(300px, 340px))",
            "justify-content: start",
            "padding: 11px 12px",
            "linear-gradient(135deg, var(--color-accent-soft), var(--color-card))",
            "color: var(--color-text-bright)",
            "overflow-wrap: anywhere",
            "@media (max-width: 760px)",
            ".realms-page__table td::before",
        ):
            self.assertIn(fragment, section)
        for selector in ("h3 {", "dl {", "article {"):
            lines = [line.strip() for line in section.splitlines() if selector in line]
            self.assertTrue(all(line.startswith(".realms-") for line in lines))
        application_lines = [line for line in section.splitlines() if "realms-application" in line]
        self.assertFalse(any("#" in line for line in application_lines))
        grid_width = re.search(r"repeat\(auto-fill, minmax\(\d+px, (\d+)px\)\)", section)
        self.assertIsNotNone(grid_width)
        self.assertGreaterEqual(int(grid_width.group(1)), 330)
        self.assertLessEqual(int(grid_width.group(1)), 340)
        mobile_760 = section[section.index("@media (max-width: 760px)"):section.index("@media (max-width: 480px)")]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", mobile_760)
        self.assertIn(".realms-application-card__primary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr))", section)
        self.assertIn(".realms-application-card__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr))", section)
        mobile_480 = section[section.index("@media (max-width: 480px)"):]
        self.assertNotIn(".realms-application-card__metrics", mobile_480)

    def test_does_not_fill_missing_curated_results(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        page = self.read("frontend/src/pages/Realms.jsx")
        combined = hook + page
        self.assertNotIn("getRealms", combined)
        self.assertNotIn("placeholder application", combined.lower())
        self.assertNotIn("namespace_key.split", combined)
        self.assertNotIn("Array(APPLICATIONS_LIMIT)", combined)


if __name__ == "__main__":
    unittest.main()
