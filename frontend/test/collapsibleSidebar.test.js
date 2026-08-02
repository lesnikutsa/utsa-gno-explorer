import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const layout = readFileSync(new URL('../src/layouts/ExplorerLayout.jsx', import.meta.url), 'utf8')
const sidebar = readFileSync(new URL('../src/components/Sidebar.jsx', import.meta.url), 'utf8')
const logo = readFileSync(new URL('../src/components/UtsaLogo.jsx', import.meta.url), 'utf8')
const icons = readFileSync(new URL('../src/components/Icons.jsx', import.meta.url), 'utf8')
const theme = readFileSync(new URL('../src/styles/theme.css', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('desktop collapsed preference is separate, safe, and persistent', () => {
  assert.match(layout, /const \[sidebarOpen, setSidebarOpen\] = useState\(false\)/)
  assert.match(layout, /const \[sidebarCollapsed, setSidebarCollapsed\] = useState\(\(\) => \{/)
  assert.match(layout, /localStorage\.getItem\('utsa-gno-explorer\.sidebar-collapsed'\) === 'true'/)
  assert.match(layout, /catch \{\s*return false\s*\}/)
  assert.match(layout, /localStorage\.setItem\('utsa-gno-explorer\.sidebar-collapsed', String\(sidebarCollapsed\)\)/)
  assert.match(layout, /catch \{[\s\S]*?\}/)
  assert.match(layout, /is-sidebar-collapsed/)
  assert.match(layout, /collapsed=\{sidebarCollapsed\}/)
  assert.match(layout, /onToggleCollapsed=\{\(\) => setSidebarCollapsed/)
})

test('sidebar retains navigation contracts and exposes accessible state controls', () => {
  assert.match(sidebar, /export function Sidebar\(\{ open, onClose, chainId, collapsed, onToggleCollapsed \}\)/)
  assert.match(sidebar, /aria-current=\{active \? 'page' : undefined\}/)
  assert.match(sidebar, /title=\{collapsed \? label : undefined\}/)
  assert.match(sidebar, /className="nav-item__label"/)
  assert.match(sidebar, /'Collapse sidebar'/)
  assert.match(sidebar, /'Expand sidebar'/)
  assert.match(sidebar, /aria-expanded=\{!collapsed\}/)
  assert.match(sidebar, /collapsed \? <ChevronRightIcon \/> : <ChevronLeftIcon \/>/)
  assert.match(sidebar, /<ChainIcon \/>/)
  assert.match(sidebar, /if \(href === '\/'\) return pathname === '\/'/)
  assert.match(sidebar, /if \(href === '\/transactions' && isTransactionDetail\) return true/)
  assert.match(icons, /export const ChevronLeftIcon/)
  assert.match(icons, /export const ChevronRightIcon/)
})

test('existing logo and shared responsive width contracts are preserved', () => {
  assert.match(logo, /logoSrc = '\/assets\/utsa-logo\.png'/)
  assert.match(theme, /--sidebar-width: 204px;/)
  assert.match(theme, /--sidebar-collapsed-width: 68px;/)
  assert.match(styles, /--sidebar-current-width: var\(--sidebar-width\)/)
  assert.match(styles, /\.sidebar \{[^}]*width: var\(--sidebar-current-width\)/)
  assert.match(styles, /\.app-frame \{[^}]*margin-left: var\(--sidebar-current-width\)/)
  assert.match(styles, /@media \(min-width: 761px\)/)
  assert.match(styles, /@media \(max-width: 760px\) \{[\s\S]*?--sidebar-current-width: var\(--sidebar-width\)/)
  assert.match(styles, /@media \(max-width: 760px\) \{[\s\S]*?\.sidebar__toggle \{ display: none; \}/)
  assert.match(styles, /@media \(max-width: 760px\) \{[\s\S]*?\.brand__product[\s\S]*?\.nav-item__label \{ display: block; \}/)
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\) \{ \.sidebar, \.app-frame \{ transition: none; \}/)
  assert.doesNotMatch(styles, /(?:html|body)\s*\{[^}]*overflow-x/)
})
