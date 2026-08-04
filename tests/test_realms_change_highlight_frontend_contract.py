import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RealmsChangeHighlightFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_changed_value_tracks_real_changes_without_timers(self):
        component = self.read("frontend/src/components/ChangedValue.jsx")
        self.assertIn("export function ChangedValue", component)
        self.assertIn("useRef(value)", component)
        self.assertIn("Object.is(previousValue.current, value)", component)
        self.assertIn("useState(0)", component)
        self.assertIn("currentRevision + 1", component)
        self.assertIn("revision > 0 ? 'realms-changed-value--active' : ''", component)
        self.assertIn("key={revision}", component)
        self.assertNotIn("setTimeout", component)
        self.assertNotIn("setInterval", component)
        self.assertNotIn("aria-live", component)

    def test_existing_animation_and_reduced_motion_are_reused(self):
        styles = self.read("frontend/src/styles/app.css")
        realms_section = styles[styles.index("/* Realms catalog */"):styles.index("/* Account detail */")]
        self.assertEqual(styles.count("@keyframes value-refresh"), 1)
        self.assertIn(".realms-changed-value { display: inline-block; }", realms_section)
        self.assertIn("animation: value-refresh 700ms ease-out", realms_section)
        self.assertIn("@media (prefers-reduced-motion: reduce)", realms_section)
        self.assertIn(".realms-changed-value--active { animation: none; }", realms_section)
        for forbidden in ("box-shadow", "border", "background", "--color-"):
            highlight_rules = realms_section[:realms_section.index(".realms-page")]
            self.assertNotIn(forbidden, highlight_rules)

    def test_summary_and_metadata_values_are_wrapped(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        self.assertIn("import { ChangedValue }", page)
        self.assertIn("<strong><ChangedValue key={`${label}-${loading}`} value={value}>{formatCount(value)}</ChangedValue></strong>", page)
        self.assertIn("value={summary.catalog_observed_height}", page)
        self.assertIn("value={summary.indexed_height}", page)
        filters = page[page.index("const filters ="):page.index("return (", page.index("const filters ="))]
        self.assertNotIn("ChangedValue", filters)

    def test_application_metrics_use_raw_values(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        applications = page[page.index("function RealmApplications"):page.index("export function Realms")]
        for value in (
            "item.direct_call_count", "item.success_rate", "item.realm_count",
            "item.called_realm_count", "item.last_activity_at",
        ):
            self.assertIn(f"<ChangedValue value={{{value}}}", applications)
        self.assertNotIn("value={relativeTime", applications)
        identity = applications[applications.index("realms-application-card__identity"):applications.index("</header>")]
        self.assertNotIn("ChangedValue", identity)

    def test_table_wraps_realm_metrics_but_not_non_metrics(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        columns = page[page.index("const columns ="):page.index("function emptyMessage")]
        for value in ("item.call_count", "item.success_rate", "item.last_activity_at"):
            self.assertIn(f"<ChangedValue value={{{value}}}", columns)
        path = columns[columns.index("key: 'path'"):columns.index("key: 'kind'")]
        kind = columns[columns.index("key: 'kind'"):columns.index("key: 'call_count'")]
        visibility = columns[columns.index("key: 'rpc_visible'"):]
        self.assertNotIn("ChangedValue", path)
        self.assertNotIn("ChangedValue", kind)
        self.assertNotIn("ChangedValue", visibility)
        self.assertIn("item.kind === 'package' ? packageMetricPlaceholder()", columns)
        self.assertIn("item.kind === 'package'\n      ? packageMetricPlaceholder('Not tracked')", columns)

    def test_polling_coordinator_contract_remains_intact(self):
        polling = self.read("frontend/src/hooks/useRealmsAutoRefresh.js")
        self.assertIn("export const REALMS_POLL_MS = 30_000", polling)
        self.assertIn("setTimeout(runCycle, REALMS_POLL_MS)", polling)
        self.assertIn("Promise.allSettled([", polling)
        self.assertIn("Promise.resolve().then(() => refreshRealms())", polling)
        self.assertIn("Promise.resolve().then(() => refreshApplications())", polling)
        self.assertIn("visibilitychange", polling)
        self.assertNotIn("setInterval", polling)
        self.assertNotIn("ChangedValue", polling)


if __name__ == "__main__":
    unittest.main()
