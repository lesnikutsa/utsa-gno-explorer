import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const validator = fs.readFileSync(new URL('../src/pages/CosmosValidatorDetail.jsx', import.meta.url), 'utf8')
const resolver = fs.readFileSync(new URL('../src/pages/CosmosTransactionHashRoute.jsx', import.meta.url), 'utf8')

test('validator activity TX links have a real hash URL for native browser navigation', () => {
  assert.match(validator, /href=\{`\/networks\/\$\{network\.id\}\/transactions\/\$\{item\.tx_hash\}`\}/)
  assert.match(validator, /event\.metaKey \|\| event\.ctrlKey \|\| event\.shiftKey \|\| event\.altKey/)
  assert.match(validator, /getCosmosTransactionByHash/)
})

test('Cosmos transaction hash route resolves with full navigation to canonical block transaction URL', () => {
  assert.match(app, /cosmosTxHashMatch = path\.match/)
  assert.match(app, /CosmosTransactionHashRoute network=\{network\} txHash=\{cosmosTxHashMatch\[2\]\.toUpperCase\(\)\}/)
  assert.match(resolver, /getCosmosTransactionByHash\(\{ networkId: network\.id, txHash, signal: controller\.signal \}\)/)
  assert.match(resolver, /window\.location\.replace\(destination\)/)
  assert.match(resolver, /blocks\/\$\{data\.height\}\/transactions\/\$\{data\.index\}/)
  assert.doesNotMatch(resolver, /history\.replaceState/)
  assert.doesNotMatch(resolver, /INTERNAL_NAVIGATION_EVENT/)
})

test('hash route initial lookup is not suppressed when a middle-click opens a background tab', () => {
  assert.doesNotMatch(resolver, /useCosmosResource/)
  assert.doesNotMatch(resolver, /document\.hidden/)
  assert.match(resolver, /new AbortController\(\)/)
  assert.match(resolver, /getCosmosTransactionByHash/)
})

test('hash route does not impose a shorter client-side timeout than backend RPC failover', () => {
  assert.doesNotMatch(resolver, /setTimeout\s*\(/)
  assert.doesNotMatch(resolver, /clearTimeout\s*\(/)
  assert.match(resolver, /return \(\) => \{\s*active = false\s*controller\.abort\(\)/s)
})
