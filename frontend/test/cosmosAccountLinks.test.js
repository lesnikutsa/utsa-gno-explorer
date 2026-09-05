import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosValidatorDetail.jsx', import.meta.url), 'utf8')
const link = fs.readFileSync(new URL('../src/components/CosmosAccountLink.jsx', import.meta.url), 'utf8')

test('Cosmos account links are network-scoped browser-native anchors', () => {
  assert.match(link, /href=\{`\/networks\/\$\{encodeURIComponent\(networkId\)\}\/accounts\/\$\{encodeURIComponent\(address\)\}`\}/)
  assert.doesNotMatch(link, /preventDefault|navigateInternal|onClick/)
  assert.match(link, /textDecoration: 'none'/)
})

test('validator account identity links only the semantic account address', () => {
  assert.match(page, /Address label="Account Address" value=\{v\.account_address\} accent networkId=\{network\.id\}/)
  assert.doesNotMatch(page, /Address label="Operator Address"[^>]+networkId=/)
  assert.doesNotMatch(page, /Address label="Consensus Address \(ValCons\)"[^>]+networkId=/)
  assert.doesNotMatch(page, /Address label="EVM Address"[^>]+networkId=/)
  assert.match(page, /value && networkId \? <CosmosAccountLink networkId=\{networkId\} address=\{value\}>\{content\}<\/CosmosAccountLink>/)
})

test('delegator and validator activity account addresses link to Account Detail', () => {
  assert.match(page, /CosmosAccountLink networkId=\{network\.id\} address=\{item\.delegator_address\}><code>\{item\.delegator_address\}<\/code><\/CosmosAccountLink>/)
  assert.match(page, /item\.account_address \? <CosmosAccountLink networkId=\{network\.id\} address=\{item\.account_address\}>/)
  assert.match(page, /shortValue\(item\.account_address\)/)
  assert.match(page, /CopyButton value=\{item\.delegator_address\}/)
})
