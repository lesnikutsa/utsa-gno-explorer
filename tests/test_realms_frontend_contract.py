import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RealmsFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_route_and_navigation(self):
        app = self.read("frontend/src/App.jsx")
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        self.assertIn("path === '/realms' || path === '/realms/'", app)
        self.assertIn("<Realms realmsPage={realmsPage} realmApplications={realmApplications} />", app)
        self.assertLess(sidebar.index("label: 'Transactions'"), sidebar.index("label: 'Realms'"))
        self.assertLess(sidebar.index("label: 'Realms'"), sidebar.index("label: 'Validators'"))
        self.assertIn("return pathname === href || pathname.startsWith(`${href}/`)", sidebar)
        self.assertEqual(sidebar.count("aria-current="), 1)

    def test_api_query_contract(self):
        client = self.read("frontend/src/services/api.js")
        for fragment in ("export const getRealms", "new URLSearchParams()", "q.trim()", "const hasCompleteCursor", "query.set('before_activity_height'", "query.set('before_path'", "{ signal }"):
            self.assertIn(fragment, client)
        script = """
          globalThis.fetch = async (url, options) => ({ ok: true, json: async () => ({ url, aborted: options.signal?.aborted ?? null }) });
          const { getRealms } = await import('./frontend/src/services/api.js');
          const controller = new AbortController();
          const values = await Promise.all([
            getRealms({ limit: 25, kind: 'all', q: '   ', beforeActivityHeight: 9 }),
            getRealms({ q: '  gno.land/r/demo & more  ', beforeActivityHeight: 9, beforePath: 'gno.land/r/a', signal: controller.signal })
          ]);
          console.log(JSON.stringify(values));
        """
        result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT, check=True, capture_output=True, text=True)
        values = json.loads(result.stdout)
        self.assertEqual(values[0]["url"], "/api/realms?limit=25&kind=all")
        self.assertIn("q=gno.land%2Fr%2Fdemo+%26+more", values[1]["url"])
        self.assertIn("before_activity_height=9&before_path=gno.land%2Fr%2Fa", values[1]["url"])
        self.assertFalse(values[1]["aborted"])

    def test_hook_state_pagination_concurrency_retry_and_errors(self):
        hook = self.read("frontend/src/hooks/useRealmsPage.js")
        for fragment in ("export const PAGE_SIZE = 25", "setCursorHistory(history)", "setPageIndex(0)", "setAppliedSearch(nextSearch)", "id !== requestId.current", "controller.current?.abort()", "failedRequest.current = attemptedRequest", "loadPage(failedRequest.current)"):
            self.assertIn(fragment, hook)
        error_handling = hook[hook.index("if (requestError?.status === 404)"):hook.index("} finally {")]
        snapshot_branch, generic_branch = error_handling.split("} else {")
        self.assertIn("setSnapshotMissing(true)", snapshot_branch)
        self.assertIn("setHealthState('healthy')", snapshot_branch)
        self.assertNotIn("setError(true)", snapshot_branch)
        self.assertIn("setError(true)", generic_branch)
        self.assertIn("setHealthState('error')", generic_branch)
        self.assertNotIn("MAX_CURSOR_HISTORY", hook)
        self.assertIn("[...cursorHistory.slice(0, pageIndex + 1), nextCursor]", hook)

    def test_presentation_contract(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        labels = ["label: 'Path'", "label: 'Type'", "label: 'Direct Calls'", "label: 'Success Rate'", "label: 'Last Activity'", "label: 'Visibility'"]
        self.assertEqual(page.count("label: '"), 6)
        self.assertEqual([page.index(label) for label in labels], sorted(page.index(label) for label in labels))
        for fragment in ("summary?.total_realms", "summary?.total_packages", "summary?.active_24h", "summary?.rpc_visible_items", "aria-pressed={kind === value}", "import { formatSuccessRate } from '../utils/realm'", ": 'Never'", "rowKey={(item) => item.path}"):
            self.assertIn(fragment, page)
        self.assertIn('type="search"', page)
        self.assertIn("maxLength={128}", page)
        self.assertNotIn("CopyButton", page)
        self.assertNotIn("dangerouslySetInnerHTML", page)
        self.assertNotIn("href=", page)
        self.assertNotIn("Verified", page)
        self.assertNotIn("Unverified", page)
        self.assertIn("item.kind === 'package' ? packageMetricPlaceholder() : <ChangedValue value={item.call_count}>{formatCount(item.call_count)}</ChangedValue>", page)
        self.assertIn("item.kind === 'package' ? packageMetricPlaceholder() : <ChangedValue value={item.success_rate}>{formatSuccessRate(item.success_rate)}</ChangedValue>", page)
        self.assertIn("packageMetricPlaceholder('Not tracked')", page)
        self.assertIn("Package usage through imports is not indexed yet. Direct-call metrics apply to realms only.", page)
        self.assertIn('title="Package usage through imports is not indexed yet."', page)

    def test_states_and_scoped_responsive_css(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        styles = self.read("frontend/src/styles/app.css")
        for message in ("Realms and packages are currently unavailable.", "The Realm catalog is not available yet.", "No realms or packages have been indexed yet.", "No realms match the current filters.", "No packages match the current filters.", "Newer entries", "Older entries"):
            self.assertIn(message, page)
        section = styles[styles.index("/* Realms catalog */"):styles.index("/* Account detail */")]
        self.assertIn("@media (max-width: 760px)", section)
        self.assertIn("content: attr(data-label)", section)
        self.assertIn(".realms-table__type--realm .status-badge", section)
        self.assertIn(".realms-table__type--package .status-badge", section)
        realm_badge = section[section.index(".realms-table__type--realm .status-badge"):section.index("\n", section.index(".realms-table__type--realm .status-badge"))]
        self.assertNotIn("var(--color-success)", realm_badge)
        self.assertIn(".realms-page__metric > span", section)
        self.assertIn("font-size: 12px", section[section.index(".realms-page__metric > span"):section.index("\n", section.index(".realms-page__metric > span"))])
        for selector in section.split("{")[:-1]:
            if selector.strip().startswith("@") or selector.strip().endswith("*/"):
                continue
        self.assertNotIn("fetch(", page + self.read("frontend/src/hooks/useRealmsPage.js"))
        self.assertNotIn("rpc.", page.lower() + self.read("frontend/src/hooks/useRealmsPage.js").lower())

    def test_success_rate_formatting(self):
        script = """
          import { formatSuccessRate } from './frontend/src/utils/realm.js';
          console.log(JSON.stringify([
            formatSuccessRate(null),
            formatSuccessRate(undefined),
            formatSuccessRate(1),
            formatSuccessRate(0),
            formatSuccessRate(0.995402),
            formatSuccessRate(Number.NaN)
          ]));
        """
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), ["—", "—", "100%", "0%", "99.5%", "—"])


if __name__ == "__main__":
    unittest.main()
