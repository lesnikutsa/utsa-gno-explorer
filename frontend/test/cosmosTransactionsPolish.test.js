import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosTransactions.jsx')
const styles = read('../src/styles/cosmos-transactions.css')
const accountStyles = read('../src/styles/cosmos-account-activity.css')

test('Cosmos transaction columns follow Type, hash, time, block, status, fee, gas order', () => {
  assert.match(page, /<th>Type<\/th><th>Tx hash<\/th><th>Time<\/th><th>Block<\/th><th>Status<\/th><th>Fee<\/th><th>Gas<\/th>/)
})

test('Cosmos transaction types use scoped badge tones and compact status pills', () => {
  assert.match(page, /cosmos-tx-type--\$\{typeTone\(row\)\}/)
  for (const tone of ['transfer', 'staking', 'reward', 'governance', 'exec', 'ibc', 'other']) {
    assert.match(styles, new RegExp(`\\.cosmos-tx-type--${tone}`))
  }
  assert.match(styles, /\.cosmos-transactions \.cosmos-tx-status \{[^}]*min-height: 20px[^}]*font-size: 10px/)
})

test('Cosmos transaction hashes and account activity hashes use accent only on hover', () => {
  assert.match(page, /className="cosmos-tx-hash"/)
  assert.match(page, /transactions\/\$\{encodeURIComponent\(row\.tx_hash\)\}/)
  assert.match(styles, /\.cosmos-tx-hash \{[^}]*color: var\(--color-text-secondary\)/)
  assert.match(styles, /\.cosmos-tx-hash:hover, \.cosmos-tx-hash:focus-visible \{ color: var\(--color-accent\); \}/)
  assert.match(accountStyles, /\.cosmos-account-activity__tx:hover, \.cosmos-account-activity__tx:focus-visible \{ color: var\(--color-accent\); \}/)
})
