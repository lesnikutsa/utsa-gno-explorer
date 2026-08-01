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

    def test_states_pagination_and_responsive_layout(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        styles = self.read("frontend/src/styles/app.css")
        badge = self.read("frontend/src/components/TransactionTypeBadge.jsx")
        for text in ("Loading", "No transactions indexed yet.", "Transactions are currently unavailable.", "Retry", "Newer transactions", "Older transactions"):
            self.assertIn(text, page + self.read("frontend/src/components/DataTable.jsx"))
        self.assertIn("disabled={loading || pageIndex === 0}", page)
        self.assertIn("disabled={loading || !canLoadOlder}", page)
        self.assertIn("pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`", page)
        transactions_rules = styles[styles.index(".transactions-page {"):styles.index(".transaction-type-badge")]
        template = "110px minmax(24px, 1fr) 250px minmax(24px, 1fr) 110px minmax(24px, 1fr) 90px minmax(24px, 1fr) 100px minmax(24px, 1fr) 120px"
        self.assertIn(f"grid-template-columns: {template}", transactions_rules)
        self.assertEqual(template.count("minmax(24px, 1fr)"), 5)
        for child, column in enumerate((1, 3, 5, 7, 9, 11), start=1):
            self.assertIn(f"tr > :nth-child({child}) {{ grid-column: {column}; }}", transactions_rules)
        self.assertIn("padding-right: 16px; padding-left: 16px", transactions_rules)
        self.assertIn("font-size: 11px; font-weight: 700; text-align: center", transactions_rules)
        self.assertNotIn("column-gap:", transactions_rules)
        self.assertNotIn("justify-content: center", transactions_rules)
        self.assertNotIn("justify-content: space-between", transactions_rules)
        self.assertNotIn("min-width: 1042px", transactions_rules)
        self.assertIn("@media (max-width: 1180px)", transactions_rules)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", transactions_rules)
        self.assertIn("@media (max-width: 520px)", transactions_rules)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", transactions_rules)
        self.assertIn("td[data-label]::before", transactions_rules)
        self.assertIn("data-label={column.label}", self.read("frontend/src/components/DataTable.jsx"))
        self.assertIn(".transactions-table__hash-cell { white-space: nowrap; }", styles)
        self.assertIn(".transactions-table__hash { color: var(--color-text-bright); font-weight: 600; white-space: nowrap; }", styles)
        self.assertNotIn(".transactions-table__hash-cell .copy-button", styles)
        self.assertIn("import { TransactionTypeBadge }", page)
        self.assertIn("<TransactionTypeBadge title={transaction.type !== 'unknown' ? transaction.type : undefined}>{transaction.operation}</TransactionTypeBadge>", page)
        self.assertIn('className="transaction-type-badge"', badge)
        self.assertIn(".transaction-type-badge {", styles)
        self.assertNotIn("transactions-table__operation", page + styles)

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
        self.assertIn("<summary>Technical Data</summary>", detail)
        self.assertIn("Raw Transaction Base64", detail)
        self.assertIn("{transaction.raw_base64}</pre>", detail)
        self.assertIn("Encoded length", detail)
        self.assertIn("Decoded size", detail)
        self.assertNotIn("Base64 Decode", information)
        self.assertIn("Base64 Decode status", technical)
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
