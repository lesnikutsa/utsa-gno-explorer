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
        self.assertNotIn("title={selectedRpc.url}", component)
        self.assertNotIn("title={endpoint.url}", component)
        self.assertNotRegex(component, r"data-[a-z-]+=\{(?:selectedRpc|endpoint)\.url\}")
        self.assertNotIn(">{selectedRpc.url}<", component)
        self.assertNotIn(">{endpoint.url}<", component)

    def test_mobile_popover_is_viewport_bounded(self):
        css = (ROOT / "frontend/src/styles/app.css").read_text()
        self.assertIn("calc(100vw - 40px)", css)
        self.assertIn("prefers-reduced-motion: reduce", css)

    def test_collapsed_rpc_trigger_is_one_compact_line(self):
        component = (ROOT / "frontend/src/components/RpcPoolStatus.jsx").read_text()
        css = (ROOT / "frontend/src/styles/app.css").read_text()
        trigger = component.split('<button className={`rpc-pool__trigger', 1)[1].split('</button>', 1)[0]
        self.assertEqual(trigger.count('rpc-pool__compact'), 1)
        self.assertNotIn('<span>RPC pool:', trigger)
        self.assertNotIn('/{pool.total} available</span>', trigger)
        self.assertIn('<span>RPC:</span>', trigger)
        self.assertIn('selectedName', trigger)
        self.assertIn('selectedLatency', trigger)
        self.assertIn('RPC unavailable', trigger)
        self.assertIn('aria-label={`RPC pool: ${pool.available} of ${pool.total} available.', trigger)
        self.assertIn('rpc-pool__trigger--${summary.tone}', trigger)
        self.assertIn('.rpc-pool__compact { display: flex;', css)
        self.assertIn('text-overflow: ellipsis', css)
        self.assertIn('white-space: nowrap', css)
        self.assertIn('min-width: 0', css)

    def test_popover_keeps_pool_availability_and_checked_time(self):
        component = (ROOT / "frontend/src/components/RpcPoolStatus.jsx").read_text()
        popover = component.split('className="rpc-pool__popover"', 1)[1]
        self.assertIn('<strong>RPC endpoints</strong>', popover)
        self.assertIn('{pool.available}/{pool.total} available', popover)
        self.assertIn('` · Checked ${relativeTime(pool.last_checked_at)}`', popover)


if __name__ == "__main__":
    unittest.main()
