import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.inspect_rpc import configured_chain_id

ROOT = Path(__file__).resolve().parents[1]
RPC_URLS = (
    "https://rpc.topaz.testnets.gno.land,"
    "https://gnoland-testnet-rpc.itrocket.net,"
    "https://topaz.rpc.onbloc.xyz"
)


class TopazCutoverTests(unittest.TestCase):
    def test_active_environment_examples_use_topaz_defaults(self):
        for relative in [".env.example", "deploy/systemd/indexer.env.example"]:
            source = (ROOT / relative).read_text()
            self.assertIn("GNO_CHAIN_ID=topaz-1", source)
            self.assertIn(f"GNO_RPC_URLS={RPC_URLS}", source)
            self.assertIn("INDEXER_START_HEIGHT=1", source)
            self.assertIn("INDEXER_BATCH_SIZE=50", source)
            self.assertIn("INDEXER_HARD_MAX_HEIGHTS=100", source)

    def test_rpc_inspector_defaults_to_topaz(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_chain_id(), "topaz-1")

    def test_test13_telegram_source_is_removed(self):
        frontend = ROOT / "frontend" / "src"
        source = "\n".join(path.read_text() for path in frontend.rglob("*") if path.is_file())
        self.assertNotIn("UTSAGNOTest13Bot", source)
        self.assertNotIn("watch_gno13_", source)
        self.assertNotIn("Monitor in Telegram", source)

    def test_resource_strip_keeps_remaining_resources(self):
        source = (ROOT / "frontend/src/components/ResourceStrip.jsx").read_text()
        self.assertIn("UTSA Guides", source)
        self.assertIn("Community Resources", source)
        self.assertEqual(source.count('className="resource-divider"'), 1)


if __name__ == "__main__":
    unittest.main()
