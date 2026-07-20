import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorDetailSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (ROOT / "frontend/src/services/api.js").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useValidatorDetail.js").read_text()
        cls.app = (ROOT / "frontend/src/App.jsx").read_text()
        cls.page = (ROOT / "frontend/src/pages/ValidatorDetail.jsx").read_text()
        cls.validators = (ROOT / "frontend/src/pages/Validators.jsx").read_text()
        cls.overview = (ROOT / "frontend/src/pages/Overview.jsx").read_text()
        cls.styles = (ROOT / "frontend/src/styles/app.css").read_text()

    def test_api_client_encodes_address_with_existing_request(self):
        self.assertIn("export const getValidator = (address)", self.api)
        self.assertIn("request(`/validators/${encodeURIComponent(address)}`)", self.api)

    def test_hook_calls_detail_api_only_after_local_validation(self):
        self.assertIn("import { getValidator } from '../services/api'", self.hook)
        validation = self.hook.index("if (address === null)")
        request = self.hook.index("getValidator(address)")
        self.assertLess(validation, request)
        self.assertIn("decodeURIComponent(routeAddress)", self.hook)
        self.assertIn("address.includes('/')", self.hook)
        self.assertIn("routeAddress.length > 128", self.hook)

    def test_hook_maps_results_and_guards_lifecycle(self):
        self.assertIn("requestError.status === 404", self.hook)
        self.assertIn("notFound: true", self.hook)
        self.assertIn("error: true", self.hook)
        self.assertIn("const retry = useCallback", self.hook)
        self.assertIn("requestId === requestIdRef.current", self.hook)
        self.assertIn("if (mounted &&", self.hook)
        self.assertIn("if (mounted && requestId === requestIdRef.current && hasSuccessfulResponse)", self.hook)
        self.assertNotIn("setInterval", self.hook)

    def test_hook_refreshes_serially_and_preserves_background_data(self):
        self.assertIn("const VALIDATOR_DETAIL_REFRESH_MS = 2000", self.hook)
        self.assertIn("await getValidator(address)", self.hook)
        self.assertIn("window.setTimeout(requestValidator, VALIDATOR_DETAIL_REFRESH_MS)", self.hook)
        self.assertIn("if (!hasSuccessfulResponse)", self.hook)
        self.assertIn("if (refreshTimer !== null) window.clearTimeout(refreshTimer)", self.hook)
        self.assertLess(self.hook.index("if (address === null)"), self.hook.index("requestValidator()"))

    def test_app_preserves_list_and_block_routes_and_adds_detail(self):
        self.assertIn("path === '/validators' || path === '/validators/'", self.app)
        self.assertIn("path.match(/^\\/validators\\/([^/]+)\\/?$/)", self.app)
        self.assertIn("<ValidatorDetailPage address={validatorDetailMatch[1]} />", self.app)
        self.assertIn("if (path.startsWith('/blocks/'))", self.app)
        self.assertIn("<BlockDetailPage height={height} />", self.app)
        self.assertIn("showRefreshCountdown={false}", self.app)

    def test_page_has_required_states_and_back_link(self):
        for title in (
            "Loading validator details…",
            "Invalid validator address",
            "Validator not found",
            "Validator details are currently unavailable",
        ):
            self.assertIn(title, self.page)
        self.assertIn('href="/validators">← Back to Validators</a>', self.page)
        self.assertEqual(self.page.count(">Retry</button>"), 1)

    def test_loaded_identity_and_status_are_present(self):
        self.assertIn("hasValidatorMoniker(validator) ? validator.moniker : 'Validator'", self.page)
        for label in (
            "Validator Identity", "Signing Address", "Operator Address", "Server Type",
            "Profile Source Height", "Current Status", "Indexed Height", "Voting Power",
            "Voting Power Share", "Proposer Priority", "Active", "Inactive",
        ):
            self.assertIn(label, self.page)
        self.assertIn('copyLabel="signing address"', self.page)
        self.assertIn('copyLabel="operator address"', self.page)
        self.assertIn("validator.address", self.page)

    def test_profile_uses_existing_fields_copy_and_safe_block_links(self):
        for label in (
            "Validator Profile", "Description", "Public Key Type", "Public Key",
            "First Seen Height", "Last Seen Height",
        ):
            self.assertIn(label, self.page)
        self.assertIn('copyLabel="validator public key"', self.page)
        self.assertIn("validator.public_key_value", self.page)
        self.assertIn('href={`/blocks/${value}`}', self.page)
        self.assertIn("present(value) ?", self.page)

    def test_signing_history_contains_uptime_and_health_without_performance_card(self):
        self.assertLess(self.page.index("<SigningHistory validator={validator} />"), self.page.index("Validator Identity"))
        self.assertIn("const uptime = validator.uptime_100", self.page)
        self.assertIn('<Field label="Uptime" mono>{formatPercent(uptime.uptime_percent)}</Field>', self.page)
        self.assertIn("getValidatorHealth(uptime)", self.page)
        self.assertIn("<StatusBadge tone={health.tone}>{health.label}</StatusBadge>", self.page)
        self.assertNotIn("Signing Performance", self.page)
        self.assertNotIn("PerformanceCard", self.page)
        self.assertNotIn("uptime={validator.uptime_20}", self.page)
        self.assertNotIn("getMissedBlocks", self.page)
        for metric in ('label="Active Blocks"', 'label="Signed"', 'label="Missed"'):
            self.assertNotIn(metric, self.page)

    def test_incomplete_uptime_data_has_neutral_health(self):
        self.assertIn("const requiredCounters =", self.page)
        self.assertIn("requiredCounters.every", self.page)
        self.assertIn("Number.isFinite(Number(uptime[counter]))", self.page)
        self.assertIn("? getValidatorHealth(uptime)", self.page)
        self.assertIn("{ label: 'No data', tone: 'neutral' }", self.page)

    def test_signing_history_reuses_strip_statuses_and_api_order(self):
        for value in (
            "Signing History", "ValidatorSigningStrip", "SIGNING_STATUSES",
            "getSigningStatusLabel", "normalizeSigningStatus", "Commit", "Not active",
            "From Block", "To Block",
        ):
            sources = self.page + (ROOT / "frontend/src/components/ValidatorSigningStrip.jsx").read_text()
            self.assertIn(value, sources)
        self.assertIn("oldest-to-newest", self.page)
        self.assertNotIn(".reverse()", self.page)
        self.assertIn("address={validator.address}", self.page)
        self.assertIn("items.map((item) => ({ height: item?.height, time: item?.time }))", self.page)
        self.assertIn("const items = Array.isArray(history.items) ? history.items : []", self.page)
        self.assertNotIn("Array(100)", self.page)
        self.assertNotIn("fill(", self.page)
        self.assertNotIn("getValidator(", self.page)

    def test_validator_table_links_exact_identity_without_changing_processing(self):
        self.assertIn("encodeURIComponent(row.address)", self.validators)
        self.assertIn("rowKey={(row) => row.address}", self.validators)
        self.assertIn("historyMap.get(row.address)", self.validators)
        self.assertIn("address={row.address}", self.validators)
        rows = self.validators.index("const rows = useMemo")
        filtered = self.validators.index("const filteredRows = useMemo")
        sorted_rows = self.validators.index("const sortedRows = useMemo")
        self.assertLess(rows, filtered)
        self.assertLess(filtered, sorted_rows)

    def test_overview_has_no_validator_detail_links(self):
        self.assertNotIn("/validators/${", self.overview)

    def test_current_status_final_field_spans_both_desktop_columns(self):
        self.assertIn(
            ".validator-detail__grid--status .validator-detail__field:last-child "
            "{ grid-column: 1 / -1; border-right: 0; }",
            self.styles,
        )
        self.assertNotIn(
            ".validator-detail__grid .validator-detail__field:last-child",
            self.styles,
        )
        self.assertIn(
            ".validator-detail__grid { grid-template-columns: 1fr; }",
            self.styles,
        )

    def test_profile_grid_has_specific_desktop_and_mobile_borders(self):
        self.assertIn(
            ".validator-detail__grid--profile .validator-detail__field:nth-child(n+2) "
            "{ border-top: 1px solid var(--color-border-soft); }",
            self.styles,
        )
        self.assertIn(
            ".validator-detail__grid--profile .validator-detail__field:nth-child(2),\n"
            ".validator-detail__grid--profile .validator-detail__field:nth-child(4) "
            "{ border-right: 1px solid var(--color-border-soft); }",
            self.styles,
        )
        self.assertIn(
            ".validator-detail__grid--profile .validator-detail__field { border-right: 0; }",
            self.styles,
        )


if __name__ == "__main__":
    unittest.main()
