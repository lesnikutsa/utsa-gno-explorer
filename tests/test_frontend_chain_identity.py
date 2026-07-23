import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ChainIdentitySourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
        cls.layout = (ROOT / "frontend/src/layouts/ExplorerLayout.jsx").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useChainIdentity.js").read_text()

    def test_sidebar_renders_dynamic_chain_and_fallback(self):
        self.assertIn("Sidebar({ open, onClose, chainId })", self.sidebar)
        self.assertIn("import { networkProfile } from '../config/networkProfile'", self.sidebar)
        self.assertIn("`${networkProfile.projectName} · ${chainId}`", self.sidebar)
        self.assertIn("`${networkProfile.projectName} network`", self.sidebar)
        self.assertIn("title={chainLabel}", self.sidebar)

    def test_sidebar_has_no_hardcoded_network_identity(self):
        for stale_label in (
            "Gno.land Testnet 13",
            "Gno.land Topaz Testnet",
            "test-13",
            "topaz-1",
        ):
            self.assertNotIn(stale_label, self.sidebar)

    def test_layout_uses_hook_once_and_passes_result_to_sidebar(self):
        self.assertIn("import { useChainIdentity } from '../hooks/useChainIdentity'", self.layout)
        self.assertEqual(self.layout.count("useChainIdentity()"), 1)
        self.assertIn("const chainId = useChainIdentity()", self.layout)
        self.assertIn("chainId={chainId}", self.layout)

    def test_hook_uses_existing_health_api_and_poll_interval(self):
        self.assertIn("import { getHealth } from '../services/api'", self.hook)
        self.assertIn("const health = await getHealth()", self.hook)
        self.assertIn("export const CHAIN_IDENTITY_POLL_MS = 30_000", self.hook)
        self.assertIn("window.setTimeout(requestChainIdentity, CHAIN_IDENTITY_POLL_MS)", self.hook)

    def test_hook_preserves_success_on_failure_and_cleans_up(self):
        catch_block = self.hook[self.hook.index("} catch {"):self.hook.index("} finally {")]
        self.assertNotIn("setChainId", catch_block)
        self.assertIn("if (mounted && nextChainId) setChainId(nextChainId)", self.hook)
        self.assertIn("mounted = false", self.hook)
        self.assertIn("window.clearTimeout(refreshTimer)", self.hook)


if __name__ == "__main__":
    unittest.main()
