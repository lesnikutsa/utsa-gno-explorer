import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OverviewRpcPoolContractTests(unittest.TestCase):
    def test_overview_uses_existing_network_payload_without_rpc_requests(self):
        overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        component = (ROOT / "frontend/src/components/RpcPoolStatus.jsx").read_text()
        self.assertIn("data.network?.rpc_pool", overview)
        for forbidden in ("fetch(", "setInterval(", "XMLHttpRequest", "axios"):
            self.assertNotIn(forbidden, component)
        self.assertNotIn("observed_height", component)

    def test_popover_is_accessible_and_has_no_selection_control(self):
        component = (ROOT / "frontend/src/components/RpcPoolStatus.jsx").read_text()
        for required in ('type="button"', "aria-expanded", "aria-controls", "event.key === 'Escape'", "onPointerEnter", "onFocus", "onClick"):
            self.assertIn(required, component)
        self.assertNotIn("Select endpoint", component)
        self.assertNotIn("radio", component)
        self.assertIn("event.pointerType", component)
        self.assertIn("document.addEventListener('pointerdown'", component)

    def test_mobile_popover_is_viewport_bounded(self):
        css = (ROOT / "frontend/src/styles/app.css").read_text()
        self.assertIn("calc(100vw - 40px)", css)
        self.assertIn("prefers-reduced-motion: reduce", css)


if __name__ == "__main__":
    unittest.main()
