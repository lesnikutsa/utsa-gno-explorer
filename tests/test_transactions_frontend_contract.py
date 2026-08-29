import unittest
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TransactionsFrontendContractTests(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_navigation_and_route(self):
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        app = self.read("frontend/src/App.jsx")
        self.assertLess(sidebar.index("label: 'Blocks'"), sidebar.index("label: 'Transactions'"))
        self.assertLess(sidebar.index("label: 'Transactions'"), sidebar.index("label: 'Validators'"))
        self.assertIn("path === '/transactions'", app)
        self.assertIn("<TransactionsPage />", app)
        self.assertIn("transactionDetailMatch", app)

    def test_active_navigation_and_page_headers(self):
        styles = self.read("frontend/src/styles/app.css")
        active_rule = styles[styles.index(".nav-item.is-active {"):styles.index("\n", styles.index(".nav-item.is-active {"))]
        self.assertIn("font-weight: 600", active_rule)
        self.assertNotIn("blocks", active_rule.lower())

        pages = {
            "frontend/src/pages/Blocks.jsx": ("Blocks", "Refresh"),
            "frontend/src/pages/Transactions.jsx": ("Transactions", "Retry"),
            "frontend/src/pages/Validators.jsx": ("Validators", "Refresh"),
            "frontend/src/pages/Governance.jsx": ("Governance", "Retry"),
        }
        subtitles = (
            "Latest finalized blocks indexed by UTSA Explorer.",
            "Latest transactions indexed by UTSA Explorer.",
            "Active validator set indexed by UTSA Explorer.",
            "Governance proposals saved by UTSA Explorer.",
        )
        all_pages = "".join(self.read(path) for path in pages)
        for subtitle in subtitles:
            self.assertNotIn(subtitle, all_pages)
        for path, (title, action) in pages.items():
            page = self.read(path)
            self.assertIn(f">{title}</h1>", page)
            self.assertIn(action, page)
        self.assertIn("All validators shown are members of the current active set.", self.read("frontend/src/pages/Validators.jsx"))
        for path in ("frontend/src/pages/Blocks.jsx", "frontend/src/pages/Transactions.jsx", "frontend/src/pages/Validators.jsx", "frontend/src/pages/Governance.jsx"):
            self.assertIn("DataTable", self.read(path))

    def test_sidebar_assigns_transaction_detail_to_transactions(self):
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        self.assertIn("/^\\/blocks\\/[^/]+\\/transactions\\/[^/]+\\/?$/.test(pathname)", sidebar)
        self.assertIn("href === '/transactions' && isTransactionDetail", sidebar)
        self.assertIn("href === '/blocks' && isTransactionDetail", sidebar)
        self.assertIn("return pathname === href || pathname.startsWith(`${href}/`)", sidebar)
        self.assertEqual(sidebar.count("aria-current="), 1)
        self.assertIn("aria-current={active ? 'page' : undefined}", sidebar)

    def test_transaction_detail_returns_to_transactions_and_keeps_block_link(self):
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        app = self.read("frontend/src/App.jsx")
        self.assertIn('href="/transactions">← Back to Transactions</a>', detail)
        self.assertNotIn('Back to Block', detail)
        self.assertIn('className="transaction-detail__block-link accent-value mono" href={canonicalBlockHref}', detail)
        self.assertIn("href === '/transactions' && isTransactionDetail", self.read("frontend/src/components/Sidebar.jsx"))
        self.assertIn("^\\/blocks\\/([^/]+)\\/transactions\\/([^/]+)\\/?$", app)

    def test_api_uses_limit_and_complete_composite_cursor(self):
        client = self.read("frontend/src/services/api.js")
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        self.assertIn("export const getTransactions", client)
        self.assertIn("const hasCompleteCursor", client)
        self.assertIn("query.set('before_height', beforeHeight)", client)
        self.assertIn("query.set('before_tx_index', beforeTxIndex)", client)
        self.assertIn("export const PAGE_SIZE = 25", hook)
        self.assertIn("limit: PAGE_SIZE", hook)
        self.assertIn("beforeHeight: cursor?.height", hook)
        self.assertIn("beforeTxIndex: cursor?.txIndex", hook)
        self.assertIn(".slice(0, PAGE_SIZE)", hook)

    def test_cursor_navigation_is_unbounded_and_paired(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        self.assertNotIn("MAX_CURSOR_HISTORY", hook)
        self.assertNotIn("cursorHistory.length", hook)
        self.assertIn("next_before_height", hook)
        self.assertIn("next_before_tx_index", hook)
        self.assertIn("loadPage(nextCursor, pageIndex + 1, history)", hook)
        self.assertIn("loadPage(cursorHistory[pageIndex - 1], pageIndex - 1)", hook)
        self.assertIn("[...cursorHistory.slice(0, pageIndex + 1), nextCursor]", hook)
        self.assertIn("canLoadOlder: nextCursor !== null", hook)
        self.assertIn("pageIndex === 0", hook)

    def test_retry_repeats_exact_failed_request(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        self.assertIn("const failedRequest = useRef(null)", hook)
        self.assertIn("const attemptedRequest = { cursor, targetIndex, history }", hook)
        self.assertIn("failedRequest.current = attemptedRequest", hook)
        self.assertIn("loadPage(request.cursor, request.targetIndex, request.history)", hook)
        self.assertIn("failedRequest.current = null", hook)

    def test_latest_live_refresh_is_visibility_safe_and_non_overlapping(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        self.assertIn("export const TRANSACTIONS_POLL_MS = 5_000", hook)
        self.assertIn("window.setTimeout", hook)
        self.assertIn("setNextRefreshAt(Date.now() + TRANSACTIONS_POLL_MS)", hook)
        self.assertIn("Math.max(0, nextRefreshAt - Date.now())", hook)
        self.assertNotIn("setInterval", hook)
        self.assertIn("pageIndexRef.current !== 0", hook)
        self.assertIn("pageIndexRef.current === 0", hook)
        self.assertIn("document.visibilityState === 'hidden'", hook)
        self.assertIn("document.visibilityState !== 'hidden'", hook)
        self.assertIn("visibilitychange", hook)
        self.assertIn("if (inFlight.current", hook)
        self.assertIn("inFlight.current = true", hook)
        self.assertIn("inFlight.current = false", hook)
        finally_section = hook.split("} finally {", 1)[1]
        self.assertIn("scheduleRefresh()", finally_section)

    def test_latest_refresh_exposes_only_a_scheduled_countdown(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        app = self.read("frontend/src/App.jsx")
        self.assertIn("const [nextRefreshAt, setNextRefreshAt] = useState(null)", hook)
        self.assertIn("setNextRefreshAt(Date.now() + TRANSACTIONS_POLL_MS)", hook)
        clear_timer = hook.split("const clearRefreshTimer", 1)[1].split("const scheduleRefresh", 1)[0]
        self.assertIn("setNextRefreshAt(null)", clear_timer)
        schedule = hook.split("const scheduleRefresh", 1)[1].split("const refreshLatestInBackground", 1)[0]
        self.assertIn("pageIndexRef.current !== 0", schedule)
        self.assertIn("document.visibilityState === 'hidden'", schedule)
        visibility = hook.split("const handleVisibilityChange", 1)[1].split("document.addEventListener", 1)[0]
        self.assertIn("clearRefreshTimer()", visibility)
        self.assertIn("nextRefreshAt,", hook.split("return {", 1)[1])
        transactions_page = app.split("function TransactionsPage", 1)[1].split("function RealmsPage", 1)[0]
        self.assertIn("transactionsPage.pageIndex === 0 && Boolean(transactionsPage.nextRefreshAt)", transactions_page)
        self.assertIn("nextFastRefreshAt={transactionsPage.nextRefreshAt}", transactions_page)
        self.assertIn("showRefreshCountdown={showRefreshCountdown}", transactions_page)

    def test_background_and_manual_refresh_preserve_latest_rows_and_cursor_state(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        background = hook.split("const refreshLatestInBackground", 1)[1].split("const loadPage", 1)[0]
        self.assertIn("getTransactions({ limit: PAGE_SIZE })", background)
        self.assertIn("setTransactions(rows)", background)
        self.assertIn("setNextCursor(cursorFromResponse(response))", background)
        for forbidden in ("setTransactions([])", "setLoading(true)", "setPageIndex(", "setCursorHistory("):
            self.assertNotIn(forbidden, background)
        self.assertIn("setHealthState(transactionsRef.current.length ? 'degraded' : 'error')", background)
        self.assertIn("setHealthState('healthy')", background)
        self.assertIn("refreshLatestInBackground({ manual: true })", hook)
        self.assertIn("setManualRefreshing(manual)", background)

    def test_latest_refresh_controls_and_multiple_row_highlights(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        self.assertIn("latestMode ? (", page)
        self.assertIn("manualRefreshing ? 'Refreshing…' : 'Refresh'", page)
        self.assertIn("error && transactions.length === 0", page)
        self.assertIn("previousTransactionIds = useRef(null)", page)
        self.assertIn("const leadingIds = currentIds.slice", page)
        self.assertIn("new Set(leadingIds)", page)
        self.assertIn("'is-new-row' : 'is-settling-row'", page)
        self.assertIn("if (!latestMode || loading)", page)
        self.assertIn("previousTransactionIds.current = null", page)

    def test_six_column_transaction_table_and_links(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        labels = ("label: 'Type'", "label: 'TX Hash'", "label: 'Time'", "label: 'Block'", "label: 'Status'", "label: 'Gas Used'")
        for label in labels:
            self.assertIn(label, page)
        self.assertEqual([page.index(label) for label in labels], sorted(page.index(label) for label in labels))
        self.assertNotIn("label: 'Height'", page)
        self.assertEqual(page.count("label: '"), 6)
        self.assertNotIn("shortAddress", page)
        self.assertNotIn("shortHash", page)
        self.assertIn("import { shortTransactionHash } from '../utils/transactionHash'", page)
        self.assertIn("shortTransactionHash(transaction.tx_hash, 'Unavailable')", page)
        self.assertIn("title={transaction.tx_hash || undefined}", page)
        self.assertNotIn("CopyButton", page)
        self.assertIn("/transactions/${encodeURIComponent(transaction.index)}", page)
        self.assertIn("/blocks/${encodeURIComponent(transaction.block_height)}", page)
        self.assertIn("{transaction.operation}", page)
        self.assertIn("transaction.type !== 'unknown'", page)
        self.assertIn("<TransactionExecutionBadge status={transaction.execution_status} />", page)
        self.assertIn("<GasValue used={transaction.gas_used} wanted={transaction.gas_wanted} />", page)
        self.assertIn("'Unavailable'", page)
        self.assertIn("`${transaction.block_height}:${transaction.index}`", page)
        for forbidden in ("sender", "recipient", "amount", "fee"):
            self.assertNotIn(forbidden, page.lower())

    def test_states_pagination_and_native_scrollable_table_layout(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        styles = self.read("frontend/src/styles/app.css")
        badge = self.read("frontend/src/components/TransactionTypeBadge.jsx")
        for text in ("Loading", "No transactions indexed yet.", "Transactions are currently unavailable.", "Retry", "Newer transactions", "Older transactions"):
            self.assertIn(text, page + self.read("frontend/src/components/DataTable.jsx"))
        self.assertIn("disabled={loading || manualRefreshing || pageIndex === 0}", page)
        self.assertIn("disabled={loading || manualRefreshing || !canLoadOlder}", page)
        self.assertIn("pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`", page)
        transactions_rules = styles[styles.index(".transactions-page {"):styles.index(".transaction-type-badge")]
        self.assertIn(".table-scroll { overflow-x: auto; }", styles)
        self.assertIn(".transactions-page__table .data-table { min-width: 940px; }", transactions_rules)
        self.assertNotIn("display: grid", transactions_rules)
        self.assertNotIn("display: block", transactions_rules)
        self.assertNotIn("grid-template-columns", transactions_rules)
        self.assertNotIn("overflow-x: visible", transactions_rules)
        self.assertNotIn("thead { display: none", transactions_rules)
        self.assertNotIn("td[data-label]::before", transactions_rules)
        shared_headers = styles[styles.index(".data-table th {"):styles.index("\n", styles.index(".data-table th {"))]
        self.assertIn("font-size: 11px", shared_headers)
        self.assertIn("font-weight: 700", shared_headers)
        self.assertIn(".transactions-page__table .data-table th, .transactions-page__table .data-table td { text-align: center; }", transactions_rules)
        self.assertIn("width: 160px", transactions_rules)
        self.assertIn("data-label={column.label}", self.read("frontend/src/components/DataTable.jsx"))
        self.assertIn(".transactions-table__hash-cell { white-space: nowrap; }", styles)
        self.assertIn(".transactions-table__hash { color: var(--color-text-bright); font-weight: 600; white-space: nowrap; }", styles)
        self.assertNotIn(".transactions-table__hash-cell .copy-button", styles)
        self.assertIn("import { TransactionTypeBadge }", page)
        self.assertIn("<TransactionTypeBadge title={transaction.type !== 'unknown' ? transaction.type : undefined}>{transaction.operation}</TransactionTypeBadge>", page)
        self.assertIn("transaction-type-badge--${variant}", badge)
        self.assertIn("segment ? ' transaction-type-badge--segmented' : ''", badge)
        self.assertIn("aria-label={segment ? children : undefined}", badge)
        self.assertIn(".transaction-type-badge {", styles)
        self.assertNotIn("transactions-table__operation", page + styles)

    def test_additional_message_badge_does_not_shift_primary_type(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        badge = self.read("frontend/src/components/AdditionalMessageBadge.jsx")
        styles = self.read("frontend/src/styles/app.css")
        self.assertIn('className="transactions-table__type-cell"', page)
        self.assertIn("<AdditionalMessageBadge messageCount={transaction.message_count} />", page)
        self.assertIn("Number.isInteger(messageCount) || messageCount <= 1", badge)
        self.assertIn("return null", badge)
        self.assertIn(".transactions-table__type-cell { position: relative; display: inline-block; }", styles)
        self.assertIn(".transactions-table__type-cell .additional-message-badge { position: absolute;", styles)
        self.assertIn("left: calc(100% + 4px)", styles)

    def test_execution_status_badge_has_accessible_text_and_safe_fallback(self):
        badge = self.read("frontend/src/components/TransactionExecutionBadge.jsx")
        self.assertIn("status === 'success'", badge)
        self.assertIn("label: 'Success', tone: 'success'", badge)
        self.assertIn("status === 'failed'", badge)
        self.assertIn("label: 'Failed', tone: 'error'", badge)
        self.assertIn("label: 'Unavailable', tone: 'neutral'", badge)
        self.assertNotIn("Pending", badge)

    def test_block_transactions_show_execution_columns_instead_of_sizes(self):
        page = self.read("frontend/src/pages/BlockDetail.jsx")
        labels = ("label: 'Index'", "label: 'Tx Hash'", "label: 'Status'", "label: 'Gas Used'", "label: 'Base64 Decode'")
        self.assertEqual([page.index(label) for label in labels], sorted(page.index(label) for label in labels))
        self.assertNotIn("label: 'Base64 Length'", page)
        self.assertNotIn("label: 'Decoded Bytes'", page)
        self.assertIn("<TransactionExecutionBadge status={transaction.execution_status} />", page)
        self.assertIn("<GasValue used={transaction.gas_used} wanted={transaction.gas_wanted} />", page)

    def test_transaction_detail_execution_and_technical_data(self):
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        styles = self.read("frontend/src/styles/app.css")
        information = detail[detail.index('id="transaction-information-title"'):detail.index('aria-labelledby="execution-result-title"')]
        technical = detail[detail.index('className="panel transaction-detail__section transaction-detail__technical"'):]
        self.assertIn('id="execution-result-title">Execution Result</h2>', detail)
        self.assertLess(detail.index("Execution Result"), detail.index("<TransactionSummary"))
        for label in ("Status", "Gas Used", "Gas Wanted", "Gas Utilization"):
            self.assertIn(f">{label}</span>", detail)
        self.assertIn("transaction.execution_status === 'failed' && transaction.error", detail)
        self.assertIn("<p>{transaction.error}</p>", detail)
        self.assertNotIn("dangerouslySetInnerHTML", detail)
        self.assertIn("The execution result is not available from the indexed RPC data.", detail)
        self.assertNotIn("not indexed yet", detail)
        self.assertIn('<details className="panel transaction-detail__section transaction-detail__technical">', detail)
        self.assertNotIn('<details className="panel transaction-detail__section transaction-detail__technical" open', detail)
        self.assertIn("<summary>Developer Data</summary>", detail)
        self.assertIn("Raw Transaction Base64", detail)
        self.assertIn("<summary>Show raw transaction</summary>", detail)
        self.assertNotIn("transaction-detail__developer-actions", detail)
        self.assertNotIn("transaction-detail__developer-actions", styles)
        self.assertIn("{transaction.raw_base64}</pre>", detail)
        self.assertNotIn("Encoded length", detail)
        self.assertIn("Payload size", detail)
        self.assertNotIn("Base64 Decode", information)
        self.assertIn("Content decoding", technical)
        self.assertIn('className="transaction-detail__field transaction-detail__field--full-width"><span className="transaction-detail__label">Block Hash', information)
        self.assertIn(".transaction-detail__grid .transaction-detail__field--full-width { grid-column: 1 / -1; border-right: 0; }", styles)
        self.assertNotIn(".transaction-detail__notice", styles)

    def test_gas_formatting_and_utilization(self):
        script = """
          import { formatGas, formatGasUtilization } from './frontend/src/utils/gas.js';
          console.log(JSON.stringify({
            values: [formatGas('934971'), formatGas('128671780'), formatGas('9007199254740993123456789'), formatGas(null), formatGas('12x')],
            utilization: [formatGasUtilization('934971', '5000000'), formatGasUtilization('1', '0'), formatGasUtilization('6000000', '5000000')]
          }));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["values"], ["934,971", "128,671,780", "9,007,199,254,740,993,123,456,789", "—", "—"])
        self.assertEqual(result["utilization"], ["18.7%", "—", "120%"])

    def test_blocks_local_search_removed_without_changing_pagination_or_polling(self):
        page = self.read("frontend/src/pages/Blocks.jsx")
        hook = self.read("frontend/src/hooks/useBlocksPage.js")
        styles = self.read("frontend/src/styles/app.css")
        for fragment in ('className="blocks-search"', 'type="search"', "submitSearch", "resetSearch", "searchInput", "searchMode", "searchNotFound"):
            self.assertNotIn(fragment, page)
        for fragment in ("getBlock,", "HEX_HASH_PATTERN", "HEIGHT_PATTERN", "searchInput", "searchQuery", "searchNotFound", "submitSearch", "resetSearch"):
            self.assertNotIn(fragment, hook)
        self.assertIn("const PAGE_SIZE = 25", hook)
        self.assertIn("export const BLOCKS_POLL_MS = 5_000", hook)
        self.assertIn("pageIndexRef.current !== 0", hook)
        self.assertIn("pageIndexRef.current === 0", hook)
        self.assertIn("Blocks are currently unavailable.", page)
        self.assertIn("No blocks have been indexed yet.", page)
        self.assertIn("pageIndex === 0", page)
        self.assertNotIn(".blocks-search", styles)
        self.assertIn(".validators-search", styles)

    def test_existing_blocks_and_transaction_detail_routes_remain_intact(self):
        blocks = self.read("frontend/src/pages/Blocks.jsx")
        app = self.read("frontend/src/App.jsx")
        self.assertIn("pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`", blocks)
        self.assertIn("Newer blocks", blocks)
        self.assertIn("Older blocks", blocks)
        transaction_route = "^\\/blocks\\/([^/]+)\\/transactions\\/([^/]+)\\/?$"
        self.assertIn(transaction_route, app)
        self.assertLess(app.index("transactionDetailMatch"), app.index("path.startsWith('/blocks/')"))


if __name__ == "__main__":
    unittest.main()
