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

    def test_cursor_navigation_is_bounded_and_paired(self):
        hook = self.read("frontend/src/hooks/useTransactionsPage.js")
        self.assertIn("MAX_CURSOR_HISTORY = 50", hook)
        self.assertIn("next_before_height", hook)
        self.assertIn("next_before_tx_index", hook)
        self.assertIn("loadPage(nextCursor, pageIndex + 1, history)", hook)
        self.assertIn("loadPage(cursorHistory[pageIndex - 1], pageIndex - 1)", hook)
        self.assertIn("pageIndex === 0", hook)

    def test_compact_four_column_table_and_links(self):
        page = self.read("frontend/src/pages/Transactions.jsx")
        for label in ("label: 'TX Hash'", "label: 'Height'", "label: 'Time'", "label: 'Type'"):
            self.assertIn(label, page)
        self.assertEqual(page.count("label: '"), 4)
        self.assertIn("shortAddress(transaction.tx_hash)", page)
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
        for text in ("Loading", "No transactions indexed yet.", "Transactions are currently unavailable.", "Retry", "Newer transactions", "Older transactions"):
            self.assertIn(text, page + self.read("frontend/src/components/DataTable.jsx"))
        self.assertIn("disabled={loading || pageIndex === 0}", page)
        self.assertIn("disabled={loading || !canLoadOlder}", page)
        self.assertIn("table-layout: fixed", styles)
        self.assertIn("text-overflow: ellipsis", styles)
        mobile = styles[styles.index("@media (max-width: 760px)"):]
        self.assertIn(".transactions-page__table .data-table { min-width: 0; }", mobile)


if __name__ == "__main__":
    unittest.main()
