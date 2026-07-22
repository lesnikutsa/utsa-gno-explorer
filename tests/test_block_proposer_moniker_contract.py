import unittest
from pathlib import Path

from api.database import BLOCKS_SQL, BLOCK_BY_BASE64_SQL, BLOCK_BY_HEX_SQL, BLOCK_DETAIL_SQL, NETWORK_SQL


ROOT = Path(__file__).resolve().parents[1]


class BlockProposerDatabaseContractTests(unittest.TestCase):
    def test_all_block_queries_left_join_current_profile_by_exact_signing_address(self):
        for query in (BLOCKS_SQL, BLOCK_BY_BASE64_SQL, BLOCK_BY_HEX_SQL, BLOCK_DETAIL_SQL):
            self.assertIn("profile.moniker AS proposer_moniker", query)
            self.assertIn("LEFT JOIN valoper_profiles profile", query)
            self.assertIn("profile.signing_address = block.proposer_address", query)
        self.assertIn("profile.moniker AS proposer_moniker", NETWORK_SQL)
        self.assertIn("LEFT JOIN valoper_profiles profile", NETWORK_SQL)
        self.assertIn("profile.signing_address = b.proposer_address", NETWORK_SQL)

    def test_join_does_not_expose_other_profile_fields(self):
        for query in (NETWORK_SQL, BLOCKS_SQL, BLOCK_BY_BASE64_SQL, BLOCK_BY_HEX_SQL, BLOCK_DETAIL_SQL):
            self.assertNotIn("profile.operator_address", query)
            self.assertNotIn("profile.description", query)
            self.assertNotIn("profile.logo", query)


class BlockProposerFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.component = (ROOT / "frontend/src/components/ProposerIdentity.jsx").read_text()
        cls.overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.blocks = (ROOT / "frontend/src/pages/Blocks.jsx").read_text()
        cls.detail = (ROOT / "frontend/src/pages/BlockDetail.jsx").read_text()

    def test_shared_component_has_link_fallback_and_full_address_modes(self):
        self.assertIn("if (!address) return", self.component)
        self.assertIn("encodeURIComponent(address)", self.component)
        self.assertIn("shortAddress(address)", self.component)
        self.assertIn("title={address}", self.component)
        self.assertNotIn("img", self.component)
        self.assertNotIn("fetch(", self.component)

    def test_all_block_views_use_api_moniker_with_shared_component(self):
        for source in (self.overview, self.blocks, self.detail):
            self.assertIn("<ProposerIdentity", source)
            self.assertIn("proposer_moniker", source)
        self.assertIn("compact", self.overview)
        self.assertIn("compact", self.blocks)
        self.assertIn("showFullAddress", self.detail)
        self.assertIn('value={block.proposer_address} label="proposer"', self.detail)

    def test_blocks_controls_remain_present(self):
        for control in ("submitSearch", "loadOlder", "loadNewer", "refresh"):
            self.assertIn(control, self.blocks)


if __name__ == "__main__":
    unittest.main()
