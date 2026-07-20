import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorSearchSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "frontend/src/pages/Validators.jsx").read_text()
        cls.styles = (ROOT / "frontend/src/styles/app.css").read_text()

    def test_imports_helper_and_uses_controlled_state(self):
        self.assertIn("matchesValidatorSearch } from '../utils/validatorIdentity'", self.source)
        self.assertIn("const [searchInput, setSearchInput] = useState('')", self.source)
        self.assertIn("value={searchInput}", self.source)
        self.assertIn("onChange={(event) => setSearchInput(event.target.value)}", self.source)

    def test_ranks_then_filters_then_sorts_a_copy(self):
        rows = self.source.index("const rows = useMemo")
        filtered = self.source.index("const filteredRows = useMemo")
        sorted_rows = self.source.index("const sortedRows = useMemo")
        self.assertLess(rows, filtered)
        self.assertLess(filtered, sorted_rows)
        self.assertIn("powerRank: index + 1", self.source[rows:filtered])
        self.assertIn("rows.filter((validator) => matchesValidatorSearch(validator, searchInput))", self.source)
        self.assertIn("[...filteredRows].sort", self.source)
        self.assertNotIn("[...rows].sort", self.source)

    def test_signing_address_identity_is_preserved(self):
        self.assertIn("rowKey={(row) => row.address}", self.source)
        self.assertIn("historyMap.get(row.address)", self.source)
        self.assertIn("address={row.address}", self.source)
        self.assertIn("title={row.address}", self.source)

    def test_toolbar_content_and_accessibility(self):
        self.assertIn('type="search"', self.source)
        self.assertIn('placeholder="Search by moniker or signing address"', self.source)
        self.assertIn('aria-label="Search validators by moniker or signing address"', self.source)
        self.assertIn('aria-label="Clear validator search">Clear</button>', self.source)
        self.assertIn('aria-live="polite">Showing {filteredRows.length} of {rows.length}', self.source)

    def test_empty_states_and_complete_summary_total(self):
        self.assertIn("'No validators found.'", self.source)
        self.assertIn("'Validators are currently unavailable.'", self.source)
        self.assertIn("'No active validators returned.'", self.source)
        self.assertIn("response.total.toLocaleString()", self.source)

    def test_search_is_local_and_has_focused_scope(self):
        self.assertNotIn("fetch(", self.source)
        self.assertNotIn("../services/api", self.source)
        filtering = self.source.split("const filteredRows", 1)[1].split("const sortedRows", 1)[0]
        for excluded_field in ["operator_address", "description", "server_type"]:
            self.assertNotIn(excluded_field, filtering)
        self.assertIn(".validators-search", self.styles)

    def test_global_search_files_do_not_use_validator_search_helper(self):
        for path in (ROOT / "frontend/src").rglob("*Search*"):
            if path.is_file():
                self.assertNotIn("matchesValidatorSearch", path.read_text())


if __name__ == "__main__":
    unittest.main()
