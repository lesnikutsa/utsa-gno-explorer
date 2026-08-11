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
        cls.telegram = (ROOT / "frontend/src/utils/telegram.js").read_text()
        cls.description = (ROOT / "frontend/src/components/ValidatorDescription.jsx").read_text()
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
        self.assertNotIn("Consensus validator details indexed by UTSA Explorer.", self.page)
        header = self.page[self.page.index('<header className="validator-detail__header">'):self.page.index("</header>")]
        self.assertNotIn("StatusBadge", header)
        for label in (
            "Validator Identity", "Signing Address", "Operator Address", "Signing PubKey (gpub)",
            "Consensus Key Type (RPC)", "Consensus Public Key (RPC)",
            "Current Status", "Indexed Height", "Voting Power",
            "Voting Power Share", "Proposer Priority", "Active", "Inactive",
        ):
            self.assertIn(label, self.page)
        self.assertIn('copyLabel="signing address"', self.page)
        self.assertIn('copyLabel="operator address"', self.page)
        self.assertIn('copyLabel="signing public key"', self.page)
        self.assertIn('copyLabel="validator public key"', self.page)
        identity = self.page[self.page.index("Validator Identity"):self.page.index("Validator Profile")]
        labels = ["Signing Address", "Operator Address", "Signing PubKey (gpub)",
                  "Consensus Key Type (RPC)", "Consensus Public Key (RPC)"]
        self.assertEqual(sorted(labels, key=identity.index), labels)
        self.assertIn("validator-detail__grid--identity", identity)
        self.assertIn("validator.signing_pubkey", identity)
        self.assertIn("validator.public_key_type", identity)
        self.assertIn("validator.public_key_value", identity)
        signing_field = identity[identity.index('label="Signing PubKey (gpub)"'):identity.index('label="Consensus Key Type (RPC)"')]
        self.assertNotIn("validator.public_key_value", signing_field)
        self.assertNotIn("Server Type", self.page)
        self.assertNotIn("Profile Source Height", self.page)
        self.assertIn("validator.address", self.page)

    def test_telegram_helper_fails_closed_when_monitoring_is_disabled(self):
        self.assertNotIn("UTSAGNOTest13Bot", self.telegram)
        self.assertNotIn("watch_gno13_", self.telegram)
        self.assertNotIn("watch_topaz_", self.telegram)
        self.assertIn("export const TELEGRAM_BOT_USERNAME = 'UTSAGNOBot'", self.telegram)
        self.assertIn("networkProfile.telegramValidatorMonitorEnabled", self.telegram)
        self.assertIn("networkProfile.telegramValidatorWatchPrefix", self.telegram)
        self.assertIn("buildConfiguredTelegramValidatorWatchUrl", self.telegram)

    def test_telegram_link_uses_signing_address_and_accessible_new_tab(self):
        self.assertIn("buildTelegramValidatorWatchUrl(validator.address)", self.page)
        self.assertIn("{telegramWatchUrl && (", self.page)
        self.assertIn('className="validator-detail__telegram-link"', self.page)
        self.assertIn('href={telegramWatchUrl}', self.page)
        self.assertIn('target="_blank"', self.page)
        self.assertIn('rel="noopener noreferrer"', self.page)
        self.assertIn(
            'aria-label="Monitor this validator in Telegram (opens in a new tab)"',
            self.page,
        )
        self.assertIn("Monitor in Telegram", self.page)

    def test_topaz_telegram_link_has_compact_interactive_responsive_styles(self):
        self.assertIn(".validator-detail__telegram-link {", self.styles)
        self.assertIn(".validator-detail__telegram-link:hover {", self.styles)
        self.assertIn(".validator-detail__telegram-link:focus-visible {", self.styles)
        header = self.styles[self.styles.index(".validator-detail__header {"):]
        self.assertIn("flex-wrap: wrap", header.split("}", 1)[0])
        mobile = self.styles[self.styles.index("@media (max-width: 760px)"):]
        self.assertIn(".validator-detail__header h1 { flex: 1 1 100%;", mobile)

    def test_profile_contains_only_description(self):
        profile = self.page[self.page.index("Validator Profile"):self.page.index("</section>", self.page.index("Validator Profile"))]
        self.assertIn("Description", profile)
        self.assertNotIn("Public Key Type", profile)
        self.assertNotIn("Public Key", profile)
        self.assertNotIn("First Seen Height", self.page)
        self.assertNotIn("Last Seen Height", self.page)

    def test_profile_uses_safe_structured_description_component(self):
        self.assertIn("import { ValidatorDescription }", self.page)
        self.assertIn("<ValidatorDescription description={validator.description} />", self.page)
        self.assertNotIn('<Field label="Description">', self.page)
        self.assertNotIn("dangerouslySetInnerHTML", self.description)
        self.assertNotIn("<strong", self.description)
        self.assertIn('target="_blank"', self.description)
        self.assertIn('rel="noopener noreferrer"', self.description)
        self.assertIn("font-weight: 400", self.styles)
        self.assertIn("line-height: 1.65", self.styles)

    def test_signing_history_contains_uptime_and_health_without_performance_card(self):
        self.assertLess(self.page.index("Current Status"), self.page.index("<SigningHistory validator={validator} />"))
        self.assertLess(self.page.index("<SigningHistory validator={validator} />"), self.page.index("Validator Identity"))
        self.assertIn("const uptime = validator.uptime_1000", self.page)
        self.assertIn('<Field label="Uptime (1000)" mono>{formatPercent(uptime.uptime_percent)}</Field>', self.page)
        self.assertIn("getValidatorHealth(uptime)", self.page)
        self.assertIn("<StatusBadge tone={health.tone}>{health.label}</StatusBadge>", self.page)
        self.assertEqual(self.page.count("<StatusBadge"), 1)
        self.assertNotIn('className="signing-history__summary"', self.page)
        metadata = self.page[self.page.index('className="signing-history__range"'):self.page.index('className="signing-history__strip"')]
        labels = ["From Block", "To Block", "Visible Blocks", "Uptime (1000)", "Health (1000)"]
        self.assertEqual(sorted(labels, key=metadata.index), labels)
        self.assertNotIn("Signing Performance", self.page)
        self.assertNotIn("PerformanceCard", self.page)
        self.assertNotIn("uptime={validator.uptime_20}", self.page)
        self.assertNotIn("getMissedBlocks", self.page)
        for metric in ('label="Active Blocks"', 'label="Signed"', 'label="Missed"'):
            self.assertNotIn(metric, self.page)

    def test_list_pages_use_1000_block_contract_and_keep_visual_history_at_50(self):
        for source in (self.overview, self.validators):
            self.assertIn("uptime_1000", source)
            self.assertNotIn("uptime_100.", source)
            self.assertIn("missed >= 50 ? 'high' : missed >= 10", source)
        self.assertIn("label: 'Signing (1000)'", self.overview)
        self.assertIn("No validator misses in the last 1000 blocks.", self.overview)
        for label in ("Uptime (1000)", "Signing (1000)", "Health (1000)"):
            self.assertIn(label, self.validators)
        self.assertIn("less than 1% missed", self.validators)
        self.assertIn("1–4.99% missed", self.validators)
        self.assertIn("5–99.99% missed", self.validators)
        self.assertIn("Latest 50 signing blocks", self.overview)

    def test_production_frontend_has_no_20_block_uptime_dependency(self):
        frontend_sources = (
            source for source in (ROOT / "frontend/src").rglob("*")
            if source.suffix in {".js", ".jsx", ".css", ".html"}
        )
        for source in frontend_sources:
            if source.is_file():
                self.assertNotIn("uptime_20", source.read_text(), source)

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

    def test_overview_links_exact_signing_identity_without_row_navigation(self):
        identity = self.overview.split("label: 'Validator'", 1)[1].split(
            "label: 'Signing (1000)'", 1
        )[0]
        self.assertIn(
            'className="validator-identity validator-identity--link"', identity
        )
        self.assertIn(
            'href={`/validators/${encodeURIComponent(row.address)}`}', identity
        )
        self.assertIn("{row.moniker}", identity)
        self.assertNotIn("onClick", identity)
        validator_table = self.overview.split(
            "<DataTable columns={validatorColumns}", 1
        )[1].split("/>", 1)[0]
        self.assertNotIn("onClick", validator_table)

    def test_current_status_is_compact_ordered_and_responsive(self):
        current = self.page[self.page.index('aria-labelledby="validator-current-status-title"'):self.page.index("<SigningHistory validator={validator} />")]
        labels = ["Status", "Indexed Height", "Voting Power", "Voting Power Share", "Proposer Priority"]
        self.assertEqual(sorted(labels, key=current.index), labels)
        self.assertIn("validator-detail__grid--status", current)
        self.assertNotIn("validator-detail__section--current-status", self.page)
        self.assertNotIn("validator-detail__section--current-status", self.styles)
        self.assertNotIn("width: min(100%, 940px)", self.styles)
        self.assertIn(".validator-detail__grid--status { grid-template-columns: repeat(5, minmax(0, 1fr)); }", self.styles)
        self.assertIn("@media (max-width: 900px)", self.styles)
        self.assertIn(".validator-detail__grid--status { grid-template-columns: repeat(3, minmax(0, 1fr)); }", self.styles)
        self.assertIn(".validator-detail__grid--status { grid-template-columns: 1fr; }", self.styles)
        self.assertNotIn(".validator-detail__grid--status .validator-detail__field:last-child", self.styles)
        self.assertIn("active ? 'success' : 'danger'", current)
        self.assertIn("validator-detail__value--success", self.styles)
        self.assertIn("validator-detail__value--danger", self.styles)

    def test_profile_description_spans_both_columns(self):
        self.assertIn(
            ".validator-detail__grid--profile .validator-detail__field:first-child "
            "{ grid-column: 1 / -1; border-right: 0; }",
            self.styles,
        )
        self.assertNotIn("signing-history__summary", self.styles)

    def test_identity_grid_spans_signing_key_and_stacks_on_mobile(self):
        self.assertIn(
            ".validator-detail__grid--identity .validator-detail__field:nth-child(3) "
            "{ grid-column: 1 / -1; border-right: 0; }",
            self.styles,
        )
        mobile = self.styles[self.styles.index("@media (max-width: 760px)"):]
        self.assertIn(".validator-detail__grid { grid-template-columns: 1fr; }", mobile)
        self.assertIn(
            ".validator-detail__grid--identity .validator-detail__field:nth-child(3) { grid-column: auto; }",
            mobile,
        )
        self.assertIn("overflow-wrap: anywhere", self.styles)


if __name__ == "__main__":
    unittest.main()
