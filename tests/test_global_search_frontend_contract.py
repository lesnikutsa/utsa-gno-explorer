import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GlobalSearchFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topbar = (ROOT / "frontend/src/components/TopBar.jsx").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useGlobalSearch.js").read_text()
        cls.helpers = (ROOT / "frontend/src/utils/globalSearch.js").read_text()
        cls.api = (ROOT / "frontend/src/services/api.js").read_text()
        cls.app = (ROOT / "frontend/src/App.jsx").read_text()
        cls.transactions = (ROOT / "frontend/src/pages/Transactions.jsx").read_text()
        cls.blocks = (ROOT / "frontend/src/pages/Blocks.jsx").read_text()
        cls.validators = (ROOT / "frontend/src/pages/Validators.jsx").read_text()

    def test_labels_and_encoded_api_path(self):
        self.assertIn('placeholder="Search blocks, transactions, or validators..."', self.topbar)
        self.assertIn("transaction hash, validator moniker, signing address, or operator address", self.topbar)
        self.assertIn("/transactions/by-hash/${encodeURIComponent(txHash)}", self.api)

    def test_hex_hash_checks_both_lookups_and_prefers_transaction(self):
        for fragment in (
            "Promise.allSettled", "getTransactionByHash(trimmed)", "getBlocks({ limit: 1, hash: trimmed })",
            "transactionResult.reason?.status === 404", "`/blocks/${transaction.block_height}/transactions/${transaction.index}`",
            "No matching block or transaction found.", "Search is currently unavailable.",
        ):
            self.assertIn(fragment, self.hook)
        self.assertLess(self.hook.index("if (transaction)"), self.hook.index("else if (block)"))

    def test_malformed_transaction_response_is_a_lookup_failure(self):
        for fragment in (
            "isValidTransactionHashLookupResponse(transactionResponse)",
            "transactionResult.status === 'fulfilled' && !transaction",
            "Number.isInteger(response?.block_height)",
            "response.block_height > 0",
            "Number.isInteger(response?.index)",
            "response.index >= 0",
            "/^[0-9a-fA-F]{64}$/.test(response?.tx_hash ?? '')",
        ):
            self.assertIn(fragment, self.hook if "transactionResult" in fragment or "transactionResponse" in fragment else self.helpers)

    def test_valid_fallback_wins_over_other_malformed_response(self):
        self.assertLess(self.hook.index("if (transaction)"), self.hook.index("const transactionFailed"))
        self.assertLess(self.hook.index("else if (block)"), self.hook.index("const transactionFailed"))
        self.assertIn("const blockFailed = !blockLookupValid", self.hook)
        self.assertIn("isValidBlockHashLookupResponse(blockResponse)", self.hook)

    def test_two_normal_not_found_results_use_hash_not_found(self):
        self.assertIn("transactionResult.reason?.status === 404", self.hook)
        self.assertIn("const block = blockLookupValid ? blockResponse.items[0] : null", self.hook)
        self.assertIn("setStatus(transactionFailed || blockFailed ? 'error' : 'hashNotFound')", self.hook)

    def test_hashes_do_not_trigger_validator_search(self):
        self.assertIn("!isExactBlockHash(trimmed)", self.helpers)
        self.assertIn("/^(?:0[xX])?[0-9a-fA-F]{64}$/", self.helpers)
        self.assertIn("/^[A-Za-z0-9+/]{43}=$/", self.helpers)
        self.assertIn("}, 250)", self.hook)

    def test_existing_behavior_and_scope_remain(self):
        self.assertIn("window.location.assign(`/blocks/${trimmed}`)", self.hook)
        self.assertIn("event.key !== '/'", self.topbar)
        self.assertIn("event.key === 'Escape'", self.topbar)
        self.assertIn("ArrowDown", self.topbar)
        self.assertIn("transactionDetailMatch", self.app)
        self.assertNotRegex(self.app, r"transactions/by-hash")
        self.assertNotIn('type="search"', self.transactions)
        self.assertNotIn('className="blocks-search"', self.blocks)
        self.assertNotIn('type="search"', self.blocks)
        self.assertIn('placeholder="Search by moniker or signing address"', self.validators)


if __name__ == "__main__":
    unittest.main()
