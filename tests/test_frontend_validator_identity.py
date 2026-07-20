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


if __name__ == "__main__":
    unittest.main()
