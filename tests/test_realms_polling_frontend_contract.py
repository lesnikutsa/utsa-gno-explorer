import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RealmsPollingFrontendContractTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def function_section(self, source, start, end):
        return source[source.index(start):source.index(end, source.index(start))]

    def test_coordinator_timeout_visibility_and_cycle_contract(self):
        hook = self.read("frontend/src/hooks/useRealmsAutoRefresh.js")
        self.assertIn("export const REALMS_POLL_MS = 30_000", hook)
        timeout = re.search(r"REALMS_BACKGROUND_REQUEST_TIMEOUT_MS = ([\d_]+)", hook)
        poll = re.search(r"REALMS_POLL_MS = ([\d_]+)", hook)
        self.assertIsNotNone(timeout)
        self.assertLess(int(timeout.group(1).replace("_", "")), int(poll.group(1).replace("_", "")))
        self.assertIn("setTimeout(runCycle, REALMS_POLL_MS)", hook)
        self.assertNotIn("setInterval", hook)
        self.assertIn("Promise.allSettled([", hook)
        self.assertIn("Promise.resolve().then(() => refreshRealms())", hook)
        self.assertIn("Promise.resolve().then(() => refreshApplications())", hook)
        cycle = self.function_section(hook, "const runCycle", "const handleVisibilityChange")
        self.assertIn("try {", cycle)
        self.assertIn("} finally {", cycle)
        finally_section = cycle[cycle.index("} finally {"):]
        self.assertIn("cycleRunning.current = false", finally_section)
        self.assertIn("schedule()", finally_section)
        self.assertIn("cycleRunning.current", hook)
        self.assertIn("document.visibilityState === 'hidden'", hook)
        self.assertIn("clearTimeout(timeout.current)", hook)
        self.assertIn("document.addEventListener('visibilitychange'", hook)
        self.assertIn("document.removeEventListener('visibilitychange'", hook)
        self.assertIn("else if (enabledRef.current && !cycleRunning.current)", hook)
        self.assertIn("runCycle()", hook)
        self.assertIn("if (!enabledRef.current", hook)

    def test_app_enables_latest_idle_page_only(self):
        app = self.read("frontend/src/App.jsx")
        self.assertEqual(app.count("useRealmsAutoRefresh({"), 1)
        self.assertIn(
            "enabled: realmsPage.pageIndex === 0 && !realmsPage.loading && !realmApplications.loading",
            app,
        )
        self.assertIn("refreshRealms: realmsPage.refreshInBackground", app)
        self.assertIn("refreshApplications: realmApplications.refreshInBackground", app)

    def test_realms_background_refresh_preserves_foreground_state(self):
        hook = self.read("frontend/src/hooks/useRealmsPage.js")
        section = self.function_section(hook, "const refreshInBackground", "const resetAndLoad")
        self.assertIn("kind,", section)
        self.assertIn("q: appliedSearch", section)
        self.assertNotIn("searchInput", section)
        for forbidden in (
            "setLoading(true)", "setItems([])", "setPageIndex(",
            "setCursorHistory(", "setAppliedSearch(", "setKindState(",
        ):
            self.assertNotIn(forbidden, section)
        for recovery in ("setError(false)", "setSnapshotMissing(false)", "setHealthState('healthy')"):
            self.assertIn(recovery, section)
        self.assertIn("if (hasData.current) setHealthState('degraded')", section)
        self.assertIn("id !== requestId.current", section)
        self.assertIn("controller.current?.abort()", hook[:hook.index("const refreshInBackground")])
        self.assertIn("refreshInBackground", hook[hook.index("return {"):])
        self.assertIn("new AbortController()", section)
        self.assertIn("window.setTimeout", section)
        self.assertIn("timedOut = true", section)
        self.assertIn("activeController.abort()", section)
        self.assertIn("window.clearTimeout(requestTimeout)", section)
        self.assertIn("requestError?.name === 'AbortError' && !timedOut", section)
        self.assertIn("controller.current = null", section)
        self.assertNotIn("setSummary(null)", section)

    def test_applications_background_refresh_preserves_cards(self):
        hook = self.read("frontend/src/hooks/useRealmApplications.js")
        section = self.function_section(hook, "const refreshInBackground", "useEffect(() =>")
        self.assertIn("limit: APPLICATIONS_LIMIT", section)
        self.assertIn("window: currentWindow.current", section)
        self.assertIn("applyResponse(response)", section)
        for forbidden in ("setLoading(true)", "setItems([])", "setSource(null)"):
            self.assertNotIn(forbidden, section)
        self.assertIn("setError(false)", section)
        self.assertIn("setSnapshotMissing(false)", section)
        self.assertIn("id !== requestId.current", section)
        self.assertNotIn("healthState", hook)
        self.assertIn("new AbortController()", section)
        self.assertIn("window.setTimeout", section)
        self.assertIn("timedOut = true", section)
        self.assertIn("activeController.abort()", section)
        self.assertIn("window.clearTimeout(requestTimeout)", section)
        self.assertIn("requestError?.name === 'AbortError' && !timedOut", section)
        self.assertIn("controller.current = null", section)

    def test_polling_has_no_ui_api_or_style_surface(self):
        page = self.read("frontend/src/pages/Realms.jsx")
        styles = self.read("frontend/src/styles/app.css")
        hooks = "".join(self.read(path) for path in (
            "frontend/src/hooks/useRealmsPage.js",
            "frontend/src/hooks/useRealmApplications.js",
            "frontend/src/hooks/useRealmsAutoRefresh.js",
        ))
        self.assertNotIn("Last refreshed", page)
        self.assertNotIn("REALMS_POLL_MS", page + styles)
        self.assertNotIn("fetch(", hooks)


if __name__ == "__main__":
    unittest.main()
