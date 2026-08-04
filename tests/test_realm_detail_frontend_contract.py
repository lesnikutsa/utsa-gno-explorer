import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_node(script):
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class RealmDetailFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_route_wrapper_query_contract_and_sidebar(self):
        app = self.read("frontend/src/App.jsx")
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        page = self.read("frontend/src/pages/RealmDetail.jsx")
        self.assertIn("path === '/realm' || path === '/realm/'", app)
        self.assertIn("function RealmDetailPage()", app)
        self.assertIn("const realmPath = decodeRealmDetailPath()", app)
        self.assertIn("const detailState = useRealmDetail(realmPath)", app)
        self.assertIn("healthState={detailState.healthState}", app)
        self.assertIn("<RealmDetail path={realmPath} detailState={detailState} />", app)
        self.assertNotIn('healthState="loading"', app)
        self.assertIn("Invalid Realm or Package path", page)
        self.assertIn('href="/realms"', page)
        self.assertNotIn("label: 'Realm Detail'", sidebar)
        self.assertEqual(sidebar.count("label: 'Realms'"), 1)

    def test_strict_path_identity_and_urlsearchparams_round_trip(self):
        values = run_node(
            """
            import { decodeRealmDetailPath, realmDetailHref } from './frontend/src/utils/realm.js';
            const longPath = `gno.land/r/${'a'.repeat(246)}`;
            const cases = {
              realm: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%2Fpath'),
              package: decodeRealmDetailPath('?path=gno.land%2Fp%2Fdemo'),
              leading: decodeRealmDetailPath('?path=%20gno.land%2Fr%2Fdemo'),
              trailing: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%20'),
              missingSegment: decodeRealmDetailPath('?path=gno.land%2Fr'),
              emptySegment: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%2F%2Fapp'),
              trailingSlash: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%2F'),
              query: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%3Fx%3D1'),
              hash: decodeRealmDetailPath('?path=gno.land%2Fr%2Fdemo%23part'),
              long: decodeRealmDetailPath(`?path=${encodeURIComponent(longPath)}`),
              href: realmDetailHref('gno.land/r/gnoswap/app'),
            };
            const url = new URL(`https://example.invalid${cases.href}`);
            cases.roundTrip = url.pathname === '/realm' && url.searchParams.get('path') === 'gno.land/r/gnoswap/app';
            console.log(JSON.stringify(cases));
            """
        )
        self.assertEqual(values["realm"], "gno.land/r/demo/path")
        self.assertEqual(values["package"], "gno.land/p/demo")
        for key in ["leading", "trailing", "missingSegment", "emptySegment", "trailingSlash", "query", "hash", "long"]:
            self.assertIsNone(values[key], key)
        self.assertEqual(values["href"], "/realm?path=gno.land%2Fr%2Fgnoswap%2Fapp")
        self.assertTrue(values["roundTrip"])

    def test_exact_api_shape_view_model_and_call_fixture(self):
        values = run_node(
            """
            import { getRealmDetailViewModel, getRealmCallViewModel, realmCallsPathForDetail } from './frontend/src/utils/realmDetail.js';
            const response = {
              source: {
                chain_id: 'topaz-1', indexed_height: 422000, catalog_observed_height: 421900,
                catalog_refreshed_at: '2026-08-04T00:00:00Z', activity_from_height: 140000,
                activity_through_height: 422000, call_index_from_height: 140000,
                call_index_through_height: 422000, call_index_complete: true,
              },
              item: {
                path: 'gno.land/r/gnoswap/app', name: 'app', kind: 'realm', rpc_visible: true,
                deployer_address: null, deploy_height: 150000, deploy_tx_index: 1,
                first_seen_height: 150000, last_activity_height: 421999, last_activity_tx_index: 0,
                last_activity_at: '2026-08-04T00:10:00Z', call_count: 12,
                successful_call_count: 10, failed_call_count: 1, unknown_result_call_count: 1,
                success_rate: 0.8333,
              },
              namespace_key: 'gnoswap', application: null,
            };
            const call = {
              block_height: 421999, tx_index: 0, message_index: 2,
              block_time: '2026-08-04T00:10:00Z', tx_hash: 'ABCDEF0123456789',
              caller_address: 'g1calleraddress', function_name: 'Swap', args_count: 2,
              send_amount: '1ugnot', execution_status: 'success', gas_wanted: '1000000', gas_used: '900000',
            };
            const view = getRealmDetailViewModel(response);
            const callView = getRealmCallViewModel(call);
            console.log(JSON.stringify({ view, callView, callsPath: realmCallsPathForDetail(response) }));
            """
        )
        self.assertEqual(values["view"]["path"], "gno.land/r/gnoswap/app")
        self.assertEqual(values["view"]["overview"]["directCalls"], 12)
        self.assertEqual(values["view"]["overview"]["deployHeight"], 150000)
        self.assertEqual(values["view"]["overview"]["deployerAddress"], None)
        self.assertEqual(values["view"]["overview"]["unknownResultCalls"], 1)
        self.assertEqual(values["view"]["sourceStatus"]["callIndexFromHeight"], 140000)
        self.assertEqual(values["view"]["sourceStatus"]["callIndexThroughHeight"], 422000)
        self.assertEqual(values["view"]["sourceStatus"]["callIndexComplete"], True)
        self.assertEqual(values["view"]["namespaceKey"], "gnoswap")
        self.assertEqual(values["callsPath"], "gno.land/r/gnoswap/app")
        self.assertEqual(values["callView"]["callerAddress"], "g1calleraddress")
        self.assertNotIn("caller", values["callView"])

    def test_negative_wrong_api_field_names_cannot_return(self):
        combined = "\n".join([
            self.read("frontend/src/pages/RealmDetail.jsx"),
            self.read("frontend/src/utils/realmDetail.js"),
        ])
        for wrong in [
            "detail.deployment_height", "detail.deployer", "detail.unknown_result_count",
            "detail.call_history_from_height", "detail.call_index_complete",
            "direct_call_count", "deployment_tx_index", "call_history_through_height",
        ]:
            self.assertNotIn(wrong, combined)
        self.assertIsNone(re.search(r"row\.caller(?!_)", combined))

    def test_realms_paths_clickable_without_row_or_copy_links(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("realmDetailHref(item.path)", page)
        self.assertIn("realms-table__path-link", page)
        self.assertNotIn("CopyButton", page)
        self.assertNotIn("<tr", page)
        self.assertIn("loadOlder", page)
        self.assertIn("loadNewer", page)
        self.assertIn("submitSearch", page)

    def test_detail_state_selection_is_path_aware(self):
        values = run_node(
            """
            import { selectRealmDetailStateForPath } from './frontend/src/utils/realmDetail.js';
            const oldData = { item: { path: 'gno.land/r/old' }, source: {} };
            const success = { path: 'gno.land/r/old', data: oldData, loading: false, error: false, temporaryError: false, notFound: false, healthState: 'healthy' };
            const oldForNew = selectRealmDetailStateForPath(success, 'gno.land/r/new');
            const initialValid = selectRealmDetailStateForPath(undefined, 'gno.land/r/new');
            const nullPath = selectRealmDetailStateForPath(success, null);
            const error = { path: 'gno.land/r/error', data: null, loading: false, error: true, temporaryError: false, notFound: false, healthState: 'error' };
            const sameError = selectRealmDetailStateForPath(error, 'gno.land/r/error');
            console.log(JSON.stringify({ oldForNew, initialValid, nullPath, sameSuccess: selectRealmDetailStateForPath(success, 'gno.land/r/old'), sameError }));
            """
        )
        self.assertEqual(values["oldForNew"]["path"], "gno.land/r/new")
        self.assertIsNone(values["oldForNew"]["data"])
        self.assertTrue(values["oldForNew"]["loading"])
        self.assertTrue(values["initialValid"]["loading"])
        self.assertEqual(values["initialValid"]["path"], "gno.land/r/new")
        self.assertFalse(values["nullPath"]["loading"])
        self.assertIsNone(values["nullPath"]["data"])
        self.assertEqual(values["sameSuccess"]["data"]["item"]["path"], "gno.land/r/old")
        self.assertTrue(values["sameError"]["error"])
        hook = self.read("frontend/src/hooks/useRealmDetail.js")
        for fragment in ["path: requestedPath", "setState(loadingRealmDetailState(path))", "id !== requestId.current", "activeController.abort()"]:
            self.assertIn(fragment, hook)

    def test_calls_state_selection_and_pagination_contract(self):
        values = run_node(
            """
            import { selectRealmCallsStateForPath } from './frontend/src/utils/realmDetail.js';
            const loaded = {
              path: 'gno.land/r/old',
              items: [{ block_height: 3, tx_index: 0, message_index: 1 }],
              pagination: { next_before_height: 2, next_before_tx_index: 0, next_before_message_index: 0 },
              loading: false, loadingOlder: false, error: false, olderError: false, unavailable: false,
            };
            const oldForNew = selectRealmCallsStateForPath(loaded, 'gno.land/r/new');
            const initialValid = selectRealmCallsStateForPath(undefined, 'gno.land/r/new');
            const nullPath = selectRealmCallsStateForPath(loaded, null);
            const same = selectRealmCallsStateForPath(loaded, 'gno.land/r/old');
            const olderLoading = { ...loaded, loadingOlder: true };
            console.log(JSON.stringify({ oldForNew, initialValid, nullPath, same, olderLoading: selectRealmCallsStateForPath(olderLoading, 'gno.land/r/old') }));
            """
        )
        self.assertTrue(values["initialValid"]["loading"])
        self.assertEqual(values["initialValid"]["items"], [])
        self.assertTrue(values["oldForNew"]["loading"])
        self.assertEqual(values["oldForNew"]["items"], [])
        self.assertIsNone(values["oldForNew"]["pagination"])
        self.assertFalse(values["nullPath"]["loading"])
        self.assertEqual(values["nullPath"]["items"], [])
        self.assertFalse(values["same"]["loading"])
        self.assertEqual(len(values["same"]["items"]), 1)
        self.assertTrue(values["olderLoading"]["loadingOlder"])
        self.assertEqual(len(values["olderLoading"]["items"]), 1)
        hook = self.read("frontend/src/hooks/useRealmCalls.js")
        for fragment in ["REALM_CALLS_PAGE_SIZE = 25", "beforeHeight: cursor?.height", "beforeTxIndex: cursor?.txIndex", "beforeMessageIndex: cursor?.messageIndex", "next_before_height", "next_before_tx_index", "next_before_message_index", "const seen = new Set(selected.items.map(callKey))", "return { ...selected, path: requestedPath, loadingOlder: false, olderError: true }", "requestError?.status === 409", "unavailable: true", "id !== requestId.current"]:
            self.assertIn(fragment, hook)
        self.assertNotIn("offset", hook.lower())

    def test_page_rendering_contract(self):
        page = self.read("frontend/src/pages/RealmDetail.jsx")
        for text in ["Overview", "Recent Calls", "Packages do not have direct Realm call history.", "Realm call history is temporarily unavailable.", "Realm or Package not found", "Catalog observed at block", "History complete", "History unavailable", "Load older calls", "Message #"]:
            self.assertIn(text, page)
        for exact in ["const response = detailState.data", "const item = response.item", "const source = response.source", "const namespaceKey = response.namespace_key", "const application = response.application"]:
            self.assertIn(exact, page)
        for field in ["item.call_count", "item.success_rate", "item.successful_call_count", "item.failed_call_count", "item.unknown_result_call_count", "item.first_seen_height", "item.last_activity_at", "item.last_activity_height", "item.deploy_height", "item.deploy_tx_index", "item.deployer_address", "source.indexed_height", "source.call_index_complete", "source.call_index_from_height", "source.call_index_through_height", "row.caller_address"]:
            self.assertIn(field, page)
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
