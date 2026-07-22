import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GlobalSearchUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topbar = (ROOT / "frontend/src/components/TopBar.jsx").read_text()
        cls.hook = (ROOT / "frontend/src/hooks/useGlobalSearch.js").read_text()
        cls.styles = (ROOT / "frontend/src/styles/app.css").read_text()

    def test_populated_results_suppress_the_floating_feedback_panel(self):
        self.assertIn(
            "const hasOpenResults = dropdownOpen && validatorResults.length > 0",
            self.topbar,
        )
        self.assertIn("{hasOpenResults && (", self.topbar)
        self.assertIn("{message && !hasOpenResults && (", self.topbar)
        self.assertIn('className="global-search__announcement" aria-live="polite"', self.topbar)
        self.assertIn(".global-search__announcement { position: absolute; width: 1px;", self.styles)

    def test_accessible_listbox_and_keyboard_behavior_remain_wired(self):
        for fragment in (
            'role="listbox"',
            'role="option"',
            "aria-expanded={dropdownOpen}",
            'aria-controls="global-search-results"',
            "aria-activedescendant=",
            "aria-selected=",
            "event.key === 'ArrowDown' || event.key === 'ArrowUp'",
            "event.key === 'Escape'",
            "event.key !== '/'",
            "onSubmit={submitSearch}",
        ):
            self.assertIn(fragment, self.topbar)

    def test_select_state_keeps_results_open_without_a_second_popup(self):
        self.assertIn("setDropdownOpen(true)", self.hook)
        self.assertIn("setStatus('select')", self.hook)
        self.assertEqual(self.topbar.count('className="global-search__results"'), 1)
        self.assertEqual(self.topbar.count("global-search__feedback global-search__feedback--"), 1)
        self.assertNotIn("logo", self.topbar.lower())
        self.assertNotIn("avatar", self.topbar.lower())


if __name__ == "__main__":
    unittest.main()
