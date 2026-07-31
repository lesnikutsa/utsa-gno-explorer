import unittest
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

    def test_aligned_four_column_table_and_links(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        labels = ("label: 'TX Hash'", "label: 'Time'", "label: 'Block'", "label: 'Type'")
        for label in labels:
            self.assertIn(label, page)
        self.assertEqual([page.index(label) for label in labels], sorted(page.index(label) for label in labels))
        self.assertNotIn("label: 'Height'", page)
        self.assertEqual(page.count("label: '"), 4)
        self.assertNotIn("shortAddress", page)
        self.assertIn("{transaction.tx_hash || 'Unavailable'}", page)
        self.assertIn("<CopyButton value={transaction.tx_hash} label=\"transaction hash\" />", page)
        self.assertIn("{transaction.tx_hash && <CopyButton", page)
        self.assertLess(page.index('</a>'), page.index('<CopyButton'))
        self.assertIn("/transactions/${encodeURIComponent(transaction.index)}", page)
        self.assertIn("/blocks/${encodeURIComponent(transaction.block_height)}", page)
        self.assertIn("{transaction.operation}", page)
        self.assertIn("transaction.type !== 'unknown'", page)
        self.assertIn("'Unavailable'", page)
        self.assertIn("`${transaction.block_height}:${transaction.index}`", page)
        for forbidden in ("sender", "recipient", "amount", "gas", "fee", "status"):
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
        self.assertIn("table-layout: fixed", styles)
        self.assertIn("min-width: 1050px", styles)
        transactions_rules = styles[styles.index(".transactions-page {"):styles.index(".blocks-table__height")]
        column_widths = (50, 14, 12, 24)
        for column, width in enumerate(column_widths, start=1):
            self.assertIn(f"th:nth-child({column}) {{ width: {width}%; }}", transactions_rules)
        self.assertEqual(sum(column_widths), 100)
        for old_width in ("width: 1%", "width: 145px", "width: 125px"):
            self.assertNotIn(old_width, transactions_rules)
        self.assertNotIn(".transactions-page__table td {", transactions_rules)
        self.assertIn(".transactions-table__hash-cell { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; vertical-align: middle; }", styles)
        self.assertIn(".transactions-table__hash { flex: 0 0 auto; color: var(--color-text-bright); font-weight: 600; white-space: nowrap; }", styles)
        self.assertNotIn("flex: 1 1 auto", transactions_rules)
        self.assertIn(".transactions-table__hash:hover { color: var(--color-accent); }", styles)
        self.assertIn("import { TransactionTypeBadge }", page)
        self.assertIn("<TransactionTypeBadge title={transaction.type !== 'unknown' ? transaction.type : undefined}>{transaction.operation}</TransactionTypeBadge>", page)
        self.assertIn('className="transaction-type-badge"', badge)
        self.assertIn(".transaction-type-badge {", styles)
        self.assertNotIn("transactions-table__operation", page + styles)
        hash_rule = styles[styles.index(".transactions-table__hash {"):styles.index(".transactions-table__hash:hover")]
        self.assertNotIn("text-overflow", hash_rule)
        mobile = styles[styles.index("@media (max-width: 760px)"):]
        self.assertIn(".transactions-page__table .data-table { min-width: 1050px; }", mobile)

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
