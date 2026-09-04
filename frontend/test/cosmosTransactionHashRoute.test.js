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

test('Cosmos transaction hash route resolves and replaces itself with canonical block transaction URL', () => {
  assert.match(app, /cosmosTxHashMatch = path\.match/)
  assert.match(app, /CosmosTransactionHashRoute network=\{network\} txHash=\{cosmosTxHashMatch\[2\]\.toUpperCase\(\)\}/)
  assert.match(resolver, /\/api\/networks\/\$\{network\.id\}\/transactions\/\$\{encodeURIComponent\(txHash\)\}/)
  assert.match(resolver, /window\.history\.replaceState/)
  assert.match(resolver, /blocks\/\$\{resource\.data\.height\}\/transactions\/\$\{resource\.data\.index\}/)
  assert.match(resolver, /INTERNAL_NAVIGATION_EVENT/)
})
