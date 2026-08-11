import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { applyTheme, DEFAULT_THEME, readStoredTheme, THEME_STORAGE_KEY } from '../src/utils/theme.js'

const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8')
const layout = readFileSync(new URL('../src/layouts/ExplorerLayout.jsx', import.meta.url), 'utf8')
const topbar = readFileSync(new URL('../src/components/TopBar.jsx', import.meta.url), 'utf8')
const theme = readFileSync(new URL('../src/styles/theme.css', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
const realmDetail = readFileSync(new URL('../src/pages/RealmDetail.jsx', import.meta.url), 'utf8')
const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))

test('theme storage accepts only dark and light and safely defaults to dark', () => {
  assert.equal(THEME_STORAGE_KEY, 'utsa-gno-explorer.theme')
  assert.equal(DEFAULT_THEME, 'dark')
  assert.equal(readStoredTheme({ getItem: () => null }), 'dark')
  assert.equal(readStoredTheme({ getItem: () => 'light' }), 'light')
  assert.equal(readStoredTheme({ getItem: () => 'dark' }), 'dark')
  assert.equal(readStoredTheme({ getItem: () => 'system' }), 'dark')
  assert.equal(readStoredTheme({ getItem: () => { throw new Error('unavailable') } }), 'dark')
})

test('applying a theme updates the root and rejects invalid values', () => {
  const root = { dataset: {} }
  assert.equal(applyTheme('light', root), 'light')
  assert.equal(root.dataset.theme, 'light')
  assert.equal(applyTheme('dark', root), 'dark')
  assert.equal(root.dataset.theme, 'dark')
  assert.equal(applyTheme('invalid', root), 'dark')
})

test('bootstrap restores preference before React renders and layout owns changes', () => {
  assert.match(main, /initializeTheme\(\)[\s\S]*createRoot/)
  assert.match(layout, /useTheme\(\)/)
  assert.match(layout, /theme=\{theme\}/)
  assert.match(layout, /onToggleTheme=\{toggleTheme\}/)
})

test('TopBar theme toggle is compact and accessible', () => {
  assert.match(topbar, /className="theme-toggle"/)
  assert.match(topbar, /aria-label=\{theme === 'light' \? 'Switch to dark theme' : 'Switch to light theme'\}/)
  assert.match(topbar, /aria-pressed=\{theme === 'light'\}/)
  assert.match(topbar, /title=\{theme === 'light'/)
  assert.match(styles, /\.theme-toggle:focus-visible \{ outline: 2px solid var\(--color-accent\)/)
})

test('dark defaults and complete warm light semantic palette are present', () => {
  assert.match(theme, /:root \{[\s\S]*color-scheme: dark;/)
  assert.match(theme, /--color-sidebar: #091827;/)
  assert.match(theme, /--color-popover: #0d2133;/)
  assert.match(theme, /--color-topbar: rgba\(8, 19, 31, \.92\);/)
  assert.match(theme, /:root\[data-theme="light"\] \{[\s\S]*--color-background: #f4f1ea;[\s\S]*--color-card: #fffdf8;[\s\S]*--color-text-secondary: #74716c;/)
  assert.match(theme, /--color-code-background: #f8f3eb;[\s\S]*--color-code-text: #29241f;/)
})

test('primary surfaces use tokens and source remains plain React text', () => {
  for (const token of ['sidebar', 'topbar', 'input', 'popover', 'surface-hover', 'shadow', 'code-background']) {
    assert.match(styles, new RegExp(`var\\(--color-${token}\\)`))
  }
  assert.doesNotMatch(styles, /background: (?:#091827|#0d2133|rgba\(8,19,31,\.92\))/)
  assert.match(realmDetail, /<pre><code>\{metadata\.source\.data\.content\}<\/code><\/pre>/)
  assert.doesNotMatch(realmDetail, /dangerouslySetInnerHTML/)
})

test('theme support adds no frontend dependency', () => {
  assert.deepEqual(Object.keys(packageJson.dependencies).sort(), ['flag-icons', 'react', 'react-dom'])
})
