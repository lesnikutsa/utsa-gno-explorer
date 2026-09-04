import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosTransactionDetail.jsx')
const styles = read('../src/styles/cosmos-transaction-detail.css')

test('Cosmos transaction messages stay compact until Details is opened', () => {
  assert.match(page, /cosmos-message__heading/)
  assert.match(page, /#\{messageIndex\}/)
  assert.match(page, /<h3>\{message\.action\}<\/h3>/)
  assert.match(page, /<code>\{message\.type_url\}<\/code>/)
  assert.match(page, /<details className="cosmos-message__details"><summary>Details<\/summary>/)
  assert.doesNotMatch(page, /<details className="cosmos-message__details" open/)
  assert.match(page, /No safely decoded fields are available/)
})

test('Cosmos transaction detail safely renders structured non-coin message values', () => {
  assert.match(page, /Object\.entries\(value\)/)
  assert.match(page, /value\.every\(\(item\).*'denom' in item.*'amount' in item/s)
  assert.match(page, /value\.map\(objectValue\)\.join\('; '\)/)
})

test('message Details styling is scoped to Cosmos Transaction Detail', () => {
  assert.match(styles, /\.cosmos-transaction-detail \.cosmos-message__details/)
  assert.match(styles, /grid-template-columns: minmax\(120px, 180px\) minmax\(0, 1fr\)/)
  assert.match(styles, /\.cosmos-message__field \{\s*display: contents;/)
  assert.match(styles, /@media \(max-width: 700px\)/)
})
