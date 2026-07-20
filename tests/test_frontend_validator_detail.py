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
        self.assertIn("return () => { mounted = false }", self.hook)
        self.assertNotIn("setInterval", self.hook)

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


if __name__ == "__main__":
    unittest.main()
