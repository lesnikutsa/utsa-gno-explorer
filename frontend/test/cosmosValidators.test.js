import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { directedValidatorComparison, favoriteFirst, missedCountClass } from '../src/utils/cosmosValidators.js'

const source = fs.readFileSync(new URL('../src/pages/CosmosValidators.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
test('Cosmos validator list exposes tabs, sorting, search and partial states', () => {
  for (const text of ['active', 'inactive', 'jailed', 'Search validators', 'History unavailable', 'Loading recent signing history…']) assert.match(source, new RegExp(text, 'i'))
  for (const key of ['tokens', 'change_24h', 'commission', 'missed_blocks', 'moniker']) assert.match(source, new RegExp(key))
})
test('Cosmos validator list includes all delta tones and compact strip', () => {
  for (const tone of ['positive', 'negative', 'neutral']) assert.match(source, new RegExp(`is-\\$\\{tone\\}`))
  assert.match(source, /Recent 50-block signing history/)
  assert.match(source, /Liveness unavailable/)
  assert.match(source, /imageSrc=\{validator\.avatar_url\}/)
})
test('Cosmos validators reuse sort arrows, scoped favorites, and risk tones', () => {
  for (const arrow of ['↕', '↑', '↓']) assert.match(source, new RegExp(arrow))
  assert.match(source, /loadValidatorFavorites\(`cosmos:\$\{network\.id\}`\)/)
  assert.match(source, /saveValidatorFavorites\(`cosmos:\$\{network\.id\}`/)
  assert.match(source, /favoriteFirst\(filtered, favorites, compare\)/)
  assert.match(source, /cosmosRiskToneFromUsage\(usage\)/)
})
test('signing points keep block context accessible without tooltips or another request', () => {
  assert.match(source, /aria-label=\{`Block \$\{point\.height\} \$\{point\.status\}/)
  assert.match(source, /point\.status/)
  assert.match(source, /pointTime\(point\)/)
  assert.doesNotMatch(source, /InfoTooltip/)
  assert.doesNotMatch(source, /title=/)
  assert.doesNotMatch(source, /fetch\([^)]*point/)
})

test('rank, explicit comparators, network favorites, inactive columns, and missed severity are stable', () => {
  assert.match(source, /powerRanks\.get\(validator\.operator_address\)/)
  assert.doesNotMatch(source, /rows\.map\(\(validator, index\)/)
  assert.doesNotMatch(source, /a\[sort\].*missed_blocks/)
  assert.match(source, /useEffect\(\(\) => setFavorites\(loadValidatorFavorites\(`cosmos:\$\{network\.id\}`\)\), \[network\.id\]\)/)
  assert.match(source, /tab === 'active'.*SortHeader field="change_24h"/)
  assert.match(source, /tab === 'active'.*<Delta/)
  assert.match(source, /<strong className=\{missedCountClass\(live\.missed_blocks\)\}>.*missed<\/strong> · \{live\.signed_percent/)
})

test('comparators preserve large powers, null-last deltas, rank, and favorite groups', () => {
  const huge = { operator_address: 'huge', tokens: '999999999999999999999999999999', change_24h: null }
  const small = { operator_address: 'small', tokens: '10', change_24h: '5' }
  assert.ok(directedValidatorComparison(huge, small, 'tokens', -1) < 0)
  assert.ok(directedValidatorComparison(huge, small, 'change_24h', -1) > 0)
  assert.ok(directedValidatorComparison(huge, small, 'change_24h', 1) > 0)
  const grouped = favoriteFirst([small, huge], new Set(['huge']), (a, b) => directedValidatorComparison(a, b, 'tokens', 1))
  assert.deepEqual(grouped.map((item) => item.operator_address), ['huge', 'small'])
})

test('risk cascade and missed threshold retain semantic colors', () => {
  assert.match(source, /validator-budget cosmos-risk__bar cosmos-risk__bar--\$\{tone\}/)
  assert.doesNotMatch(css, /\.validator-budget i\s*\{[^}]*background/)
  assert.equal(missedCountClass(10), 'validator-missed-count')
  assert.equal(missedCountClass(11), 'validator-missed-count validator-missed-count--alert')
  assert.match(css, /\.validator-missed-count--alert\s*\{\s*color:\s*var\(--color-error\)/)
})

test('clean UI, zero delta, compact search, and jailed layout are retained', () => {
  assert.doesNotMatch(source, /InfoTooltip|title=/)
  assert.match(source, /showTitles=\{false\}/)
  assert.match(source, /change_24h === '0'.*—/)
  assert.doesNotMatch(source, /SortHeader field="missed_blocks">Missed blocks/)
  assert.match(source, /startsWith\('1970-01-01T00:00:00'\).*'—'/)
  assert.match(css, /\.cosmos-validator-toolbar input \{ font-size: 12px; \}/)
  assert.doesNotMatch(css, /\.info-tooltip/)
  assert.match(source, /className="cosmos-validator-stake-share"/)
  assert.match(css, /\.cosmos-validator-stake-share[^}]*color:\s*var\(--color-text-secondary\)/)
  assert.match(source, /className="card status-card cosmos-validator-summary__card"/)
})

test('validator token presentation uses whole numbers and shared Gno card surfaces', () => {
  assert.match(source, /const wholeTokens = .*Math\.trunc/)
  assert.match(source, /wholeTokens\(validator\.tokens, asset\.exponent\)\.toLocaleString\(\)/)
  assert.match(source, /wholeTokens\(data\.summary\.bonded_change_24h, asset\.exponent\)/)
  assert.match(source, /className="card status-card cosmos-validator-summary__card"/)
  assert.match(css, /\.cosmos-validator-summary article[^}]*background:\s*linear-gradient\(135deg, var\(--color-accent-soft\), var\(--color-card\)\)/)
  assert.doesNotMatch(source, /maximumFractionDigits: 2 \}\)\} \{asset\.symbol\}/)
})

test('validator toolbar gives remaining desktop width to search and can wrap', () => {
  assert.match(css, /\.cosmos-validator-toolbar\s*\{[^}]*flex-wrap:\s*wrap;/)
  assert.match(css, /\.cosmos-validator-tabs\s*\{[^}]*flex:\s*0 0 auto;/)
  assert.match(css, /\.cosmos-validator-toolbar input\s*\{[^}]*flex:\s*1 1 300px;[^}]*width:\s*auto;/)
  assert.match(css, /@media \(max-width: 800px\) \{[^\n]*\.cosmos-validator-toolbar \{[^\n]*flex-direction: column;/)
})

test('commission and voting power share primary metric typography', () => {
  assert.equal((source.match(/className="cosmos-validator-primary-metric"/g) || []).length, 2)
  assert.match(source, /cosmos-validator-primary-metric">\{\(Number\(validator\.commission\) \* 100\)\.toFixed\(2\)\}%/)
  assert.match(css, /\.cosmos-validator-primary-metric\s*\{[^}]*font-size:\s*12px;[^}]*font-weight:\s*600;/)
  assert.match(css, /\.cosmos-validator-stake-share[^}]*font-size:\s*9px;/)
})
