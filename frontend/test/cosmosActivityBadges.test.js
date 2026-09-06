import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const main = read('../src/main.jsx')
const shared = read('../src/styles/cosmos-activity-badges.css')
const transactions = read('../src/styles/cosmos-transactions.css')

test('Cosmos contextual activity tables load one shared badge visual layer', () => {
  assert.match(main, /import '\.\/styles\/cosmos-activity-badges\.css'/)
  assert.match(shared, /\.cosmos-account-activity \.cosmos-account-activity__action/)
  assert.match(shared, /\.cosmos-validator-detail \.cosmos-validator-activity td > strong/)
})

test('contextual activity badges match the compact Transactions type badge geometry', () => {
  for (const declaration of [
    'min-height: 20px',
    'padding: 2px 7px',
    'border: 1px solid currentColor',
    'border-radius: 5px',
    'font-size: 10px',
    'font-weight: 600',
    'line-height: 1.2',
  ]) {
    assert.ok(transactions.includes(declaration), `Transactions badge is missing ${declaration}`)
    assert.ok(shared.includes(declaration), `Shared activity badge is missing ${declaration}`)
  }
})

test('shared activity badge selectors stay Cosmos-scoped and preserve contextual tones', () => {
  assert.doesNotMatch(shared, /\.validator-activity(?!__)/)
  assert.doesNotMatch(shared, /\.account-activity(?!__)/)
  assert.match(shared, /is-positive[\s\S]*var\(--color-success\)/)
  assert.match(shared, /is-negative[\s\S]*var\(--color-error\)/)
  assert.match(shared, /is-neutral[\s\S]*var\(--color-warning\)/)
})
