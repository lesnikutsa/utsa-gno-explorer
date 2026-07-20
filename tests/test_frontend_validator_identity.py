import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorIdentitySourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "frontend/src/pages/Validators.jsx").read_text()
        cls.identity_render = cls.source.split("label: 'Validator'", 1)[1].split(
            "label: 'Voting Power'", 1
        )[0]

    def test_matched_identity_renders_moniker_and_secondary_short_address(self):
        self.assertIn("label: 'Validator'", self.source)
        self.assertIn("hasValidatorMoniker(row) ?", self.identity_render)
        self.assertIn('className="validator-identity__moniker"', self.identity_render)
        self.assertIn("{row.moniker}", self.identity_render)
        self.assertIn(
            'className="validator-identity__address mono">{shortAddress(row.address)}',
            self.identity_render,
        )

    def test_unmatched_identity_renders_one_primary_short_address_line(self):
        fallback = self.identity_render.split(") : (", 1)[1]
        self.assertEqual(fallback.count("shortAddress(row.address)"), 1)
        self.assertIn('className="validator-identity__fallback mono"', fallback)
        self.assertNotIn("validator-identity__address", fallback)
        self.assertNotIn("validator-identity__moniker", fallback)

    def test_signing_address_remains_the_technical_identity(self):
        self.assertIn("rowKey={(row) => row.address}", self.source)
        self.assertIn("historyMap.get(row.address)", self.source)
        self.assertIn("address={row.address}", self.source)
        self.assertIn('title={row.address}', self.source)

    def test_no_forbidden_fallback_label_is_introduced(self):
        for label in ["Unknown", "Unnamed", "N/A", "Validator", "No profile"]:
            self.assertNotIn(f">{label}<", self.identity_render)
            self.assertNotIn(f"'{label}'", self.identity_render)
        self.assertNotIn("validator-${", self.identity_render)


class OverviewValidatorIdentitySourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.styles = (ROOT / "frontend/src/styles/app.css").read_text()
        cls.identity_render = cls.source.split("label: 'Validator'", 1)[1].split(
            "label: 'Signing (last 100)'", 1
        )[0]
        cls.ranking = cls.source.split("const validatorsByMisses", 1)[1].split(
            "useEffect", 1
        )[0]

    def test_uses_shared_helper_and_validator_column_label(self):
        self.assertIn(
            "import { hasValidatorMoniker } from '../utils/validatorIdentity'",
            self.source,
        )
        self.assertIn("label: 'Validator'", self.source)
        self.assertIn("hasValidatorMoniker(row) ?", self.identity_render)

    def test_matched_identity_renders_exact_moniker_and_secondary_address(self):
        self.assertIn(
            'className="validator-identity validator-identity--link"',
            self.identity_render,
        )
        self.assertIn('className="validator-identity__moniker">{row.moniker}', self.identity_render)
        self.assertIn(
            'className="validator-identity__address mono">{shortAddress(row.address)}',
            self.identity_render,
        )

    def test_unmatched_identity_renders_one_fallback_address(self):
        fallback = self.identity_render.split(") : (", 1)[1]
        self.assertEqual(fallback.count("shortAddress(row.address)"), 1)
        self.assertIn('className="validator-identity__fallback mono"', fallback)
        self.assertNotIn("validator-identity__address", fallback)
        self.assertNotIn("validator-identity__moniker", fallback)

    def test_signing_address_remains_the_technical_identity(self):
        self.assertIn("rowKey={(row) => row.address}", self.source)
        self.assertIn("historyMap.get(row.address)", self.source)
        self.assertIn("address={row.address}", self.source)
        self.assertIn("title={row.address}", self.identity_render)

    def test_identity_links_to_the_encoded_signing_address_only(self):
        self.assertIn(
            'href={`/validators/${encodeURIComponent(row.address)}`}',
            self.identity_render,
        )
        self.assertNotIn("encodeURIComponent(row.moniker)", self.identity_render)
        self.assertNotIn("onClick", self.identity_render)
        validator_table = self.source.split(
            "<DataTable columns={validatorColumns}", 1
        )[1].split("/>", 1)[0]
        self.assertNotIn("onClick", validator_table)

    def test_no_forbidden_fallback_label_is_introduced(self):
        for label in ["Unknown", "Unnamed", "N/A", "Validator", "No profile"]:
            self.assertNotIn(f">{label}<", self.identity_render)
            self.assertNotIn(f"'{label}'", self.identity_render)

    def test_missed_validator_ranking_remains_address_based(self):
        self.assertNotIn("moniker", self.ranking)
        self.assertIn("right.missedTotal - left.missedTotal", self.ranking)
        self.assertIn("left.address.localeCompare(right.address)", self.ranking)
        self.assertIn(".slice(0, OVERVIEW_VALIDATOR_ROW_LIMIT)", self.ranking)
        self.assertIn("const OVERVIEW_VALIDATOR_ROW_LIMIT = 6", self.source)

    def test_latest_blocks_and_validators_use_separate_limits(self):
        self.assertIn("const LATEST_BLOCKS_ROW_LIMIT = 7", self.source)
        self.assertIn("const OVERVIEW_VALIDATOR_ROW_LIMIT = 6", self.source)
        self.assertIn("data.blocks.slice(0, LATEST_BLOCKS_ROW_LIMIT)", self.source)
        self.assertNotIn("data.blocks.sort", self.source)

    def test_latest_blocks_reuses_explorer_data_without_an_api_request(self):
        self.assertNotIn("fetch(", self.source)
        self.assertNotIn("../services/api", self.source)

    def test_overview_tables_use_unchanged_global_cell_density(self):
        self.assertIn(
            ".data-table td { height: 35px; padding: 6px 12px;",
            self.styles,
        )
        self.assertNotIn(".dashboard-grid__blocks .data-table td", self.styles)
        self.assertNotIn(".dashboard-grid__validators .data-table td", self.styles)


if __name__ == "__main__":
    unittest.main()
