import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TransactionDetailFrontendContractTests(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_route_precedes_generic_block_route(self):
        app = self.read("frontend/src/App.jsx")
        transaction_route = "^\\/blocks\\/([^/]+)\\/transactions\\/([^/]+)\\/?$"
        self.assertIn(transaction_route, app)
        self.assertLess(app.index("transactionDetailMatch"), app.index("path.startsWith('/blocks/')"))

    def test_client_and_hook_contract(self):
        client = self.read("frontend/src/services/api.js")
        hook = self.read("frontend/src/hooks/useTransactionDetail.js")
        self.assertIn("encodeURIComponent(blockHeight)", client)
        self.assertIn("encodeURIComponent(index)", client)
        self.assertIn("/^(0|[1-9]\\d*)$/", hook)
        self.assertIn("requestId === requestIdRef.current", hook)
        self.assertNotIn("setInterval", hook)

    def test_compact_accessible_block_transaction_link(self):
        block = self.read("frontend/src/pages/BlockDetail.jsx")
        self.assertIn("label: 'Index'", block)
        self.assertIn('label: \'Raw Base64\'', block)
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        self.assertIn('className="transaction-link mono"', block)
        self.assertIn("/blocks/${encodeURIComponent(blockHeight)}/transactions/${encodeURIComponent(transaction.index)}", block)
        self.assertIn("aria-label={`Open transaction #${transaction.index} in block #${blockHeight}`}", block)
        self.assertIn("#{transaction.index}", block)
        self.assertNotIn(">Transaction #{transaction.index}</a>", block)
        self.assertIn("href={canonicalBlockHref}", detail)
        self.assertIn("<CopyButton value={transaction.raw_base64}", detail)
        self.assertIn("Transaction #{transaction.index}", detail)
        self.assertIn("canonical transaction hash are not indexed yet", detail)
        self.assertNotIn("avatar", detail.lower())
        self.assertNotIn("logo", detail.lower())

    def test_raw_base64_layout_is_scoped_and_truncated(self):
        styles = self.read("frontend/src/styles/app.css")
        selector = ".block-detail__transactions .transaction-raw"
        self.assertIn(selector, styles)
        rule = styles[styles.index(selector):styles.index("}", styles.index(selector))]
        for declaration in (
            "display: block",
            "min-width: 0",
            "max-width: 100%",
            "overflow: hidden",
            "text-overflow: ellipsis",
            "white-space: nowrap",
        ):
            self.assertIn(declaration, rule)
        self.assertIn(".block-detail__transactions .data-table th:nth-child(1) { width: 80px; }", styles)
        self.assertNotIn("\n.data-table { table-layout: fixed", styles)

    def test_navigation_and_search_are_unchanged(self):
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        search = self.read("frontend/src/hooks/useGlobalSearch.js")
        self.assertNotIn("/transactions", sidebar)
        self.assertNotIn("transaction", search.lower())


if __name__ == "__main__":
    unittest.main()
