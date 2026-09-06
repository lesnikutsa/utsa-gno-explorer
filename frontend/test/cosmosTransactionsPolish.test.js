import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosTransactions.jsx')
const blockDetail = read('../src/pages/CosmosBlockDetail.jsx')
const validatorDetail = read('../src/pages/CosmosValidatorDetail.jsx')
const accountActivity = read('../src/components/CosmosAccountActivity.jsx')
const styles = read('../src/styles/cosmos-transactions.css')
const tooltipStyles = read('../src/styles/cosmos-tx-tooltip.css')
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

test('Cosmos transaction hashes share bright default, accent hover, and larger compact text', () => {
  assert.match(page, /className="cosmos-tx-hash cosmos-tx-tooltip"/)
  assert.match(page, /transactions\/\$\{encodeURIComponent\(row\.tx_hash\)\}/)
  assert.match(page, /data-tooltip=\{row\.tx_hash\}/)
  assert.doesNotMatch(page, /data-tooltip=\{`Transaction hash/)
  assert.doesNotMatch(page, /className="cosmos-tx-hash cosmos-tx-tooltip"[^>]*title=/)
  assert.match(styles, /\.cosmos-tx-hash \{[^}]*color: var\(--color-text-bright\)[^}]*font-size: 11px/)
  assert.match(styles, /\.cosmos-tx-hash:hover, \.cosmos-tx-hash:focus-visible \{[^}]*color: var\(--color-accent\)/)
  assert.match(styles, /\.cosmos-validator-activity a\.cosmos-validator-activity__tx,[\s\S]*\.cosmos-account-activity a\.cosmos-account-activity__tx \{[^}]*color: var\(--color-text-bright\)[^}]*font-size: 11px/)
  assert.match(accountStyles, /\.cosmos-account-activity__tx:hover, \.cosmos-account-activity__tx:focus-visible \{ color: var\(--color-accent\); \}/)
})

test('Cosmos shortened transaction hashes use one hash-only Explorer tooltip', () => {
  assert.match(accountActivity, /className="cosmos-account-activity__tx cosmos-tx-tooltip"[^>]*data-tooltip=\{item\.tx_hash\}/)
  assert.doesNotMatch(accountActivity, /cosmos-account-activity__tx[^>]*title=\{item\.tx_hash\}/)
  assert.match(validatorDetail, /className="mono cosmos-validator-activity__tx cosmos-tx-tooltip"[^>]*data-tooltip=\{item\.tx_hash\}/)
  assert.doesNotMatch(validatorDetail, /cosmos-validator-activity__tx[^>]*title=\{item\.tx_hash\}/)
  assert.match(tooltipStyles, /\.cosmos-tx-tooltip\[data-tooltip\]::after \{[^}]*background: var\(--color-card\)[^}]*color: var\(--color-text-bright\)[^}]*content: attr\(data-tooltip\)/)
})

test('Block detail full transaction hash uses the same neutral to accent link semantics without a redundant tooltip', () => {
  assert.match(blockDetail, /className="transaction-hash mono cosmos-hash-value cosmos-tx-full-hash-link"/)
  assert.doesNotMatch(blockDetail, /cosmos-tx-full-hash-link[^>]*title=\{tx\.hash\}/)
  assert.match(styles, /\.cosmos-block-detail a\.cosmos-tx-full-hash-link \{[^}]*color: var\(--color-text-bright\)/)
  assert.match(styles, /\.cosmos-block-detail a\.cosmos-tx-full-hash-link:hover,[\s\S]*color: var\(--color-accent\)/)
})
