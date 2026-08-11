import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidatorFavoritesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "frontend/src/pages/Validators.jsx").read_text()
        cls.styles = (ROOT / "frontend/src/styles/app.css").read_text()

    def run_module(self, script):
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_toggle_persistence_isolation_and_storage_failures(self):
        result = self.run_module("""
          import { loadValidatorFavorites, saveValidatorFavorites, toggleValidatorFavorite } from './frontend/src/utils/validatorFavorites.js'
          const values = new Map()
          const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
          let favorites = toggleValidatorFavorite(new Set(), 'g1favorite')
          saveValidatorFavorites('sapphire-1', favorites, storage)
          const restored = loadValidatorFavorites('sapphire-1', storage)
          favorites = toggleValidatorFavorite(favorites, 'g1favorite')
          values.set('utsa-gno-explorer.validator-favorites.v1:broken', '{')
          const throwing = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
          saveValidatorFavorites('blocked', new Set(['g1x']), throwing)
          console.log(JSON.stringify({
            added: restored.has('g1favorite'), removed: !favorites.has('g1favorite'),
            isolated: loadValidatorFavorites('other-1', storage).size === 0,
            malformed: loadValidatorFavorites('broken', storage).size === 0,
            unavailable: loadValidatorFavorites('blocked', throwing).size === 0,
          }))
        """)
        self.assertTrue(all(result.values()))

    def test_browser_storage_resolution_failures_do_not_escape(self):
        result = self.run_module("""
          import { loadValidatorFavorites, saveValidatorFavorites } from './frontend/src/utils/validatorFavorites.js'
          const withoutWindow = loadValidatorFavorites('no-window').size === 0
          Object.defineProperty(globalThis, 'window', {
            configurable: true,
            value: Object.defineProperty({}, 'localStorage', {
              get: () => { throw new DOMException('blocked', 'SecurityError') },
            }),
          })
          let readSafe = false
          let writeSafe = false
          try { readSafe = loadValidatorFavorites('blocked-window').size === 0 } catch {}
          try { saveValidatorFavorites('blocked-window', new Set(['g1x'])); writeSafe = true } catch {}
          console.log(JSON.stringify({ withoutWindow, readSafe, writeSafe }))
        """)
        self.assertTrue(all(result.values()))

    def test_favorites_group_without_mutating_sort_or_rank(self):
        result = self.run_module("""
          import { compareFavoriteGroups } from './frontend/src/utils/validatorFavorites.js'
          const source = [{ address: 'normal', value: 2, powerRank: 1 }, { address: 'favorite-b', value: 2, powerRank: 27 }, { address: 'favorite-a', value: 1, powerRank: 9 }, { address: 'normal-b', value: 1, powerRank: 4 }]
          const favorites = new Set(['favorite-a', 'favorite-b'])
          const sort = (direction) => [...source].sort((a, b) => compareFavoriteGroups(a, b, favorites) || direction * ((a.value - b.value) || (a.powerRank - b.powerRank)))
          console.log(JSON.stringify({ ascending: sort(1).map(x => x.address), descending: sort(-1).map(x => x.address), rank: sort(1)[1].powerRank, source: source.map(x => x.address) }))
        """)
        self.assertEqual(result["ascending"], ["favorite-a", "favorite-b", "normal-b", "normal"])
        self.assertEqual(result["descending"], ["favorite-b", "favorite-a", "normal", "normal-b"])
        self.assertEqual(result["rank"], 27)
        self.assertEqual(result["source"], ["normal", "favorite-b", "favorite-a", "normal-b"])

    def test_search_and_accessibility_contract(self):
        filtering = self.page.split("const filteredRows", 1)[1].split("const sortedRows", 1)[0]
        sorting = self.page.split("const sortedRows", 1)[1].split("const effectiveQuery", 1)[0]
        self.assertIn("matchesValidatorSearch", filtering)
        self.assertIn("compareFavoriteGroups", sorting)
        self.assertIn('className={`validator-favorite', self.page)
        self.assertIn('type="button" aria-pressed={isFavorite}', self.page)
        self.assertIn('aria-label={favoriteLabel} title={favoriteLabel}', self.page)
        self.assertIn('<a className="validator-identity validator-identity--link"', self.page)
        self.assertIn("'Remove' : 'Add'", self.page)
        self.assertIn("'from' : 'to'", self.page)
        self.assertIn(".validator-favorite:focus-visible", self.styles)


if __name__ == "__main__":
    unittest.main()
