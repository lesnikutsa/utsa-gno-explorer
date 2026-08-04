import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RealmDetailFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_route_query_contract_and_sidebar(self):
        app = self.read("frontend/src/App.jsx")
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        page = self.read("frontend/src/pages/RealmDetail.jsx")
        self.assertIn("path === '/realm' || path === '/realm/'", app)
        self.assertIn("<RealmDetail />", app)
        self.assertIn("decodeRealmDetailPath()", page)
        self.assertIn("Invalid Realm or Package path", page)
        self.assertIn('href="/realms"', page)
        self.assertNotIn("label: 'Realm Detail'", sidebar)
        self.assertEqual(sidebar.count("label: 'Realms'"), 1)

    def test_urlsearchparams_helper_and_api_requests(self):
        realm = self.read("frontend/src/utils/realm.js")
        api = self.read("frontend/src/services/api.js")
        self.assertIn("export function realmDetailHref(path)", realm)
        self.assertIn("new URLSearchParams()", realm)
        self.assertIn("params.set('path', path)", realm)
        self.assertIn("/realm?${params.toString()}", realm)
        for fragment in ["export const getRealmDetail", "export const getRealmCalls", "query.set('limit', limit)", "query.set('before_height', beforeHeight)", "query.set('before_tx_index', beforeTxIndex)", "query.set('before_message_index', beforeMessageIndex)"]:
            self.assertIn(fragment, api)
        script = """
          import { realmDetailHref } from './frontend/src/utils/realm.js';
          console.log(JSON.stringify(realmDetailHref('gno.land/r/demo/path')));
        """
        result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), "/realm?path=gno.land%2Fr%2Fdemo%2Fpath")

    def test_realms_paths_clickable_without_row_or_copy_links(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("realmDetailHref(item.path)", page)
        self.assertIn("realms-table__path-link", page)
        self.assertNotIn("CopyButton", page)
        self.assertNotIn("<tr", page)
        self.assertIn("loadOlder", page)
        self.assertIn("loadNewer", page)
        self.assertIn("submitSearch", page)

    def test_detail_hook_state_and_stale_protection(self):
        hook = self.read("frontend/src/hooks/useRealmDetail.js")
        for fragment in ["getRealmDetail({ path, signal: activeController.signal })", "controller.current?.abort()", "requestId.current", "id !== requestId.current", "activeController.abort()", "notFound: requestError?.status === 404", "temporaryError: requestError?.status === 503", "retry"]:
            self.assertIn(fragment, hook)

    def test_calls_hook_cursor_pagination_and_unavailable_state(self):
        hook = self.read("frontend/src/hooks/useRealmCalls.js")
        for fragment in ["REALM_CALLS_PAGE_SIZE = 25", "beforeHeight: cursor?.height", "beforeTxIndex: cursor?.txIndex", "beforeMessageIndex: cursor?.messageIndex", "next_before_height", "next_before_tx_index", "next_before_message_index", "const seen = new Set(current.map(callKey))", "return [...current, ...rows.filter", "requestError?.status === 409", "setUnavailable(true)", "setOlderError(true)"]:
            self.assertIn(fragment, hook)
        self.assertNotIn("offset", hook.lower())

    def test_page_rendering_contract(self):
        page = self.read("frontend/src/pages/RealmDetail.jsx")
        for text in ["Overview", "Recent Calls", "Packages do not have direct Realm call history.", "Realm call history is temporarily unavailable.", "Realm or Package not found", "Catalog observed at block", "History complete", "History unavailable", "Load older calls", "Message #"]:
            self.assertIn(text, page)
        for label in ["Direct Calls", "Success Rate", "Successful Calls", "Failed Calls", "Unknown Results", "First Seen block", "Last Activity", "Last Activity block", "Deployment block", "Deployment transaction position", "Deployer", "Indexed height"]:
            self.assertIn(label, page)
        for column in ["Time", "Function", "Caller", "Block", "Status", "Gas Used", "Tx Hash"]:
            self.assertIn(f"label: '{column}'", page)
        self.assertIn("/blocks/${encodeURIComponent(value)}", page)
        self.assertIn("/accounts/${encodeURIComponent(value)}", page)
        self.assertIn("/blocks/${encodeURIComponent(row.block_height)}/transactions/${encodeURIComponent(row.tx_index)}", page)
        self.assertNotIn("CopyButton", page)

    def test_scoped_responsive_css(self):
        styles = self.read("frontend/src/styles/app.css")
        section = styles[styles.index(".realm-detail {"):]
        self.assertIn("overflow-wrap: anywhere", section)
        self.assertIn("overflow-x: auto", styles)
        self.assertIn("@media (max-width: 900px)", section)
        self.assertIn("@media (max-width: 620px)", section)
        self.assertNotIn("#ff", section.lower())


if __name__ == "__main__":
    unittest.main()
