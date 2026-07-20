import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorIdentitySourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "frontend/src/pages/Validators.jsx").read_text()

    def test_validator_column_renders_moniker_and_short_signing_address(self):
        self.assertIn("label: 'Validator'", self.source)
        self.assertIn("{row.moniker}", self.source)
        self.assertIn("{shortAddress(row.address)}", self.source)

    def test_signing_address_remains_the_technical_identity(self):
        self.assertIn("rowKey={(row) => row.address}", self.source)
        self.assertIn("historyMap.get(row.address)", self.source)
        self.assertIn("address={row.address}", self.source)
        self.assertIn('title={row.address}', self.source)

    def test_no_forbidden_fallback_label_is_introduced(self):
        identity_render = self.source.split("label: 'Validator'", 1)[1].split("label: 'Voting Power'", 1)[0]
        for label in ["Unknown", "Unnamed", "N/A", "Validator", "No profile"]:
            self.assertNotIn(f">{label}<", identity_render)
            self.assertNotIn(f"'{label}'", identity_render)
        self.assertNotIn("validator-${", identity_render)


if __name__ == "__main__":
    unittest.main()
