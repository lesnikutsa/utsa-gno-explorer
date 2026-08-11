import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const detail = readFileSync(new URL('../src/pages/RealmDetail.jsx', import.meta.url), 'utf8')
const hook = readFileSync(new URL('../src/hooks/useRealmMetadata.js', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('metadata polish keeps the established sections and explicit empty states', () => {
  assert.match(detail, />Overview</)
  assert.match(detail, />Recent Calls</)
  assert.match(detail, /No dependencies/)
  assert.match(detail, /Functions unavailable · \{statusLabel\(summary\.qfuncs_status\)\}/)
  assert.doesNotMatch(detail, /qfuncs_status === 'application_error'[\s\S]*?function_count[^\n]*0/)
  assert.match(detail, /data\.kind === 'realm' && field\('Storage'/)
  assert.match(detail, /data\.kind === 'realm' && field\('Render'/)
})

test('Docs uses a bounded definition grid and existing status badges', () => {
  assert.match(detail, /<dl className="realm-metadata__docs">/)
  assert.match(detail, /tone=\{docs\.available \? 'success' : 'neutral'\}/)
  assert.match(detail, /tone=\{docs\.package_doc_present \? 'success' : 'neutral'\}/)
  assert.match(styles, /\.realm-metadata__docs \{[^}]*grid-template-columns: minmax\(130px, 190px\) max-content;[^}]*width: fit-content;[^}]*max-width: 100%;/)
})

test('Source expansion is independent from selected-file loading', () => {
  assert.match(detail, /useState\(false\)/)
  assert.match(detail, /sourceExpanded \? 'Hide source ↑' : 'Show source ↓'/)
  assert.match(detail, /className="blocks-page__button realm-metadata__source-toggle"/)
  assert.match(styles, /\.realm-metadata__source-toggle \{[^}]*border-color: var\(--color-accent\);[^}]*background: var\(--color-accent-soft\);[^}]*color: var\(--color-text-bright\);/)
  assert.match(detail, /aria-expanded=\{sourceExpanded\}/)
  assert.match(detail, /sourceExpanded && metadata\.source\.data && <pre><code>\{metadata\.source\.data\.content\}<\/code><\/pre>/)
  assert.match(hook, /const \[selectedFilename, setSelectedFilename\] = useState\(null\)/)
  assert.match(detail, /aria-pressed=\{file\.filename === metadata\.selectedFilename\}/)
  assert.doesNotMatch(hook, /setSourceExpanded/)
})

test('Files follow Dependencies and remain close to Source', () => {
  const grid = detail.slice(detail.indexOf('<div className="realm-metadata__grid">'), detail.indexOf('<div className="realm-metadata__source">'))
  assert.ok(grid.indexOf('<h3>Dependencies') < grid.indexOf('<h3>Files'))
  assert.ok(grid.indexOf('<h3>Files') < grid.indexOf('<h3>Docs'))
})

test('untrusted source stays exact passive React text', () => {
  const hostileSource = '<script>alert("x")</script>\n<img src=x onerror=alert(1)>\n</pre><script>alert(2)</script>'
  const markup = renderToStaticMarkup(React.createElement('pre', null, React.createElement('code', null, hostileSource)))

  assert.equal(markup, '<pre><code>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;\n&lt;img src=x onerror=alert(1)&gt;\n&lt;/pre&gt;&lt;script&gt;alert(2)&lt;/script&gt;</code></pre>')
  assert.match(detail, /<pre><code>\{metadata\.source\.data\.content\}<\/code><\/pre>/)
  assert.doesNotMatch(detail, /dangerouslySetInnerHTML/)
})

test('Source and long-path geometry remain bounded', () => {
  assert.match(styles, /\.realm-metadata__source pre \{[^}]*width: 100%;[^}]*max-width: 100%;[^}]*max-height: min\(560px, 65vh\);[^}]*overflow: auto;[^}]*white-space: pre;[^}]*tab-size: 4;/)
  assert.match(styles, /\.realm-metadata__files button > span:first-child, \.realm-metadata__names a, \.realm-metadata__source-header > p \{ overflow-wrap: anywhere; word-break: break-word; \}/)
})

test('Realm and Package dependencies share the canonical detail helper', () => {
  assert.match(detail, /import \{ formatSuccessRate, realmDetailHref \} from '\.\.\/utils\/realm'/)
  assert.match(detail, /href=\{realmDetailHref\(dependency\.imported_path\)\}/)
  assert.match(detail, /data\.dependencies\.map\(\(dependency\)/)
  assert.doesNotMatch(detail, /\/realms\/detail\?path=/)
  assert.doesNotMatch(detail, /dependency\.imported_kind === ['"](?:realm|package)['"]/)
})
