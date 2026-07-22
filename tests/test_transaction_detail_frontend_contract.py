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
        self.assertIn("label: 'Tx Hash'", block)
        self.assertNotIn("label: 'Raw Base64'", block)
        self.assertIn("label: 'Base64 Decode'", block)
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        self.assertIn('className="transaction-link mono"', block)
        self.assertIn("/blocks/${encodeURIComponent(blockHeight)}/transactions/${encodeURIComponent(transaction.index)}", block)
        self.assertIn("aria-label={`Open transaction #${transaction.index} in block #${blockHeight}`}", block)
        self.assertIn("#{transaction.index}", block)
        self.assertNotIn(">Transaction #{transaction.index}</a>", block)
        self.assertIn("href={canonicalBlockHref}", detail)
        self.assertIn("<CopyButton value={transaction.raw_base64}", detail)
        self.assertIn("Transaction #{transaction.index}", detail)
        self.assertIn('<CopyButton value={transaction.tx_hash} label="transaction hash" />', detail)
        self.assertIn("title={transaction.tx_hash}", block)
        self.assertIn('className="transaction-hash__full" aria-hidden="true">{transaction.tx_hash}', block)
        self.assertIn('className="transaction-hash__short" aria-hidden="true"', block)
        self.assertIn("transaction.tx_hash.slice(0, 12)", block)
        self.assertIn("transaction.tx_hash.slice(-9)", block)
        self.assertIn(": '—'", block)
        self.assertNotIn("canonical transaction hash are not indexed", detail)
        self.assertNotIn("avatar", detail.lower())
        self.assertNotIn("logo", detail.lower())

    def test_transaction_hash_layout_is_scoped_and_truncated(self):
        styles = self.read("frontend/src/styles/app.css")
        selector = ".block-detail__transactions .transaction-hash"
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
        self.assertIn("@media (min-width: 1200px)", styles)
        self.assertIn(".block-detail__transactions .transaction-hash__full { display: none; }", styles)
        self.assertIn(".block-detail__transactions .transaction-hash__short { display: block; }", styles)
        responsive = styles[styles.index("@media (min-width: 1200px)"):]
        self.assertIn(".block-detail__transactions .transaction-hash__full { display: block; }", responsive)
        self.assertIn(".block-detail__transactions .transaction-hash__short { display: none; }", responsive)
        self.assertNotIn("\n.data-table { table-layout: fixed", styles)

    def test_block_hash_and_balanced_information_grid(self):
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        information = detail[detail.index('className="transaction-detail__grid"'):detail.index("</section>", detail.index('className="transaction-detail__grid"'))]
        self.assertEqual(information.count('className="transaction-detail__field"'), 6)
        for label in ("Block", "Transaction Index", "Block Time", "Proposer", "Block Hash", "Base64 Decode"):
            self.assertIn(f">{label}</span>", information)
        self.assertIn("{transaction.block_hash}", information)
        self.assertIn('<CopyButton value={transaction.block_hash} label="block hash" />', information)

    def test_decode_badge_is_shared_and_never_implies_execution_success(self):
        block = self.read("frontend/src/pages/BlockDetail.jsx")
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        badge = self.read("frontend/src/components/TransactionDecodeBadge.jsx")
        self.assertIn("TransactionDecodeBadge", block)
        self.assertIn("TransactionDecodeBadge", detail)
        self.assertIn("status === 'decoded'", badge)
        self.assertIn("{ label: 'Decoded', tone: 'neutral' }", badge)
        self.assertNotIn("tone: 'success'", badge)
        self.assertIn("{ label: 'Invalid Base64', tone: 'error' }", badge)
        self.assertIn("This is not transaction execution status", badge)

    def test_future_fields_are_notice_only(self):
        block = self.read("frontend/src/pages/BlockDetail.jsx")
        detail = self.read("frontend/src/pages/TransactionDetail.jsx")
        self.assertIn("Transaction type, sender, execution result, gas, fee", detail)
        self.assertNotIn("label: 'Type'", block)
        self.assertNotIn("Transaction Hash</span>", detail)

    def test_transaction_spacing_remains_scoped(self):
        styles = self.read("frontend/src/styles/app.css")
        self.assertIn(".transaction-detail__header { margin-bottom: 14px; }", styles)
        self.assertIn(".transaction-detail__section { margin-bottom: 10px; }", styles)
        self.assertIn(".transaction-detail__field { min-width: 0; padding: 11px 13px; }", styles)
        transaction_rule = styles[styles.index(".transaction-detail {"):styles.index("}", styles.index(".transaction-detail {"))]
        self.assertNotIn("padding", transaction_rule)

    def test_navigation_and_search_are_unchanged(self):
        sidebar = self.read("frontend/src/components/Sidebar.jsx")
        search = self.read("frontend/src/hooks/useGlobalSearch.js")
        self.assertNotIn("/transactions", sidebar)
        self.assertNotIn("transaction", search.lower())


if __name__ == "__main__":
    unittest.main()
