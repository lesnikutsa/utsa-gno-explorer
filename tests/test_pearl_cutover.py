import os
import unittest
from pathlib import Path
from unittest.mock import patch

from api.config import DEFAULT_CHAIN_ID
from api.network_profile import gno_profile
from scripts.inspect_rpc import configured_chain_id


ROOT = Path(__file__).resolve().parents[1]
PEARL_RPC = "https://rpc.pearl.testnets.gno.land"


class PearlCutoverTests(unittest.TestCase):
    def test_runtime_and_environment_defaults_use_pearl(self):
        self.assertEqual(DEFAULT_CHAIN_ID, "pearl-1")
        for relative in (".env.example", "deploy/systemd/rpc.env.example"):
            source = (ROOT / relative).read_text()
            self.assertIn("GNO_CHAIN_ID=pearl-1", source)
            self.assertIn(f"GNO_RPC_URLS={PEARL_RPC}", source)
        self.assertIn("INDEXER_START_HEIGHT=1", (ROOT / ".env.example").read_text())

    def test_cutover_requires_empty_data_instead_of_sapphire_rows(self):
        documentation = "\n".join(
            (ROOT / relative).read_text()
            for relative in ("docs/install.md", "docs/operator-runbook.md", "docs/production-deployment.md")
        )
        self.assertIn("empty database", documentation)
        self.assertIn("Never restore or reuse Sapphire", documentation)
        self.assertIn("INDEXER_START_HEIGHT=1", documentation)

    def test_active_product_identity_has_no_sapphire_references(self):
        paths = [ROOT / ".env.example", ROOT / "deploy/systemd/rpc.env.example", ROOT / "frontend/.env.example"]
        for directory in ("api", "scripts", "frontend/src"):
            paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
        active = "\n".join(path.read_text(errors="ignore") for path in paths)
        self.assertNotIn("sapphire", active.lower())

    def test_rpc_inspector_defaults_to_pearl(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_chain_id(), "pearl-1")

    def test_active_runtime_sources_do_not_default_to_topaz(self):
        active_paths = [ROOT / ".env.example", ROOT / "deploy/systemd/rpc.env.example"]
        active_paths.extend((ROOT / directory).rglob("*") for directory in ("api", "scripts", "frontend/src"))
        paths = active_paths[:2]
        for group in active_paths[2:]:
            paths.extend(path for path in group if path.is_file())
        source = "\n".join(path.read_text(errors="ignore") for path in paths)
        self.assertNotIn("topaz-1", source)
        self.assertNotIn("https://gnoland-testnet-rpc.itrocket.net", source)

    def test_frontend_defaults_to_pearl_and_disables_topaz_monitor(self):
        profile = (ROOT / "frontend/src/config/networkRegistry.js").read_text()
        environment = (ROOT / "frontend/.env.example").read_text()
        telegram = (ROOT / "frontend/src/utils/telegram.js").read_text()
        self.assertIn("'Pearl'", profile)
        self.assertIn("Pearl is the current public test network", profile)
        self.assertIn("VITE_NETWORK_NAME=Pearl", environment)
        self.assertIn("VITE_TELEGRAM_VALIDATOR_MONITOR_ENABLED=false", environment)
        self.assertIn("VITE_TELEGRAM_VALIDATOR_WATCH_PREFIX=\n", environment)
        self.assertNotIn("watch_topaz_", telegram)
        self.assertNotIn(
            "watch_topaz_",
            "\n".join(path.read_text() for path in (ROOT / "frontend/src").rglob("*") if path.is_file()),
        )
        self.assertIn("networkProfile.telegramValidatorWatchPrefix", telegram)

    def test_generic_gno_profile_preserves_address_semantics(self):
        profile = gno_profile("pearl-1")
        self.assertEqual(
            (profile.chain_family, profile.account_hrp, profile.native_denom,
             profile.native_symbol, profile.native_decimals),
            ("gno", "g", "ugnot", "GNOT", 6),
        )


if __name__ == "__main__":
    unittest.main()
