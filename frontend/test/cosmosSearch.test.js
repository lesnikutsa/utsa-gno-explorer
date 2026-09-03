import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const search = read('../src/components/NetworkBlockSearch.jsx')
const api = read('../src/services/api.js')
const topbar = read('../src/components/TopBar.jsx')
const gnoSearch = read('../src/hooks/useGlobalSearch.js')

test('Cosmos search preserves block and transaction navigation', () => {
  assert.match(search, /BLOCK_HEIGHT\.test\(value\)/)
  assert.match(search, /`\/networks\/\$\{network\.id\}\/blocks\/\$\{value\}`/)
  assert.match(search, /TRANSACTION_HASH\.test\(value\)/)
  assert.match(search, /transactions\/\$\{encodeURIComponent\(value\)\}/)
  assert.match(search, /blocks\/\$\{transaction\.height\}\/transactions\/\$\{transaction\.index\}/)
  assert.match(search, /Transaction not found\./)
})

test('Cosmos validator search is network-scoped and registry-prefix driven', () => {
  assert.match(search, /network\.addressPrefixes\.validator_operator/)
  assert.doesNotMatch(search, /atonevaloper/i)
  assert.match(api, /networks\/\$\{encodeURIComponent\(networkId\)\}\/search\/validators/)
  assert.match(search, /networkId: network\.id, query: value, limit: 6/)
  assert.match(search, /networks\/\$\{network\.id\}\/validators\/\$\{encodeURIComponent\(validator\.operator_address\)\}/)
  assert.match(search, /shortAddress\(validator\.operator_address\)/)
  assert.match(search, /Validator not found\./)
  assert.match(search, /No matching validator found\./)
})

test('Cosmos dropdown supports bounded debouncing and keyboard and mouse selection', () => {
  assert.match(search, /}, 250\)/)
  assert.match(search, /response\.items\.slice\(0, 6\)/)
  assert.match(search, /event\.key === 'ArrowDown'/)
  assert.match(search, /event\.key === 'ArrowUp'/)
  assert.match(search, /event\.key === 'Escape'/)
  assert.match(search, /highlightedIndex >= 0 && dropdownOpen/)
  assert.match(search, /onClick=\{\(event\) => \{ event\.preventDefault\(\); selectValidator\(validator\) \}\}/)
  assert.match(search, /document\.addEventListener\('pointerdown'/)
  assert.match(search, /Search is temporarily unavailable\./)
})

test('Cosmos search prevents stale cross-network results without changing GNO search', () => {
  assert.match(search, /controller\.abort\(\)/)
  assert.match(search, /sequence !== requestSequence\.current/)
  assert.match(search, /currentNetworkId\.current !== networkId/)
  assert.match(search, /useEffect\(\(\) => clear\(\), \[network\.id\]\)/)
  assert.match(topbar, /cosmosSearch \? <NetworkBlockSearch/)
  assert.match(gnoSearch, /searchValidators/)
  assert.doesNotMatch(gnoSearch, /searchCosmosValidators|\/networks\//)
})
