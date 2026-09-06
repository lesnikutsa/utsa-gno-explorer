import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const tooltipStyles = read('../src/styles/cosmos-tx-tooltip.css')
const validatorDetail = read('../src/pages/CosmosValidatorDetail.jsx')

test('Cosmos Blocks tooltip cells are not clipped by the shared table cell overflow rule', () => {
  assert.match(tooltipStyles, /\.cosmos-blocks-table \.cosmos-table td:nth-child\(2\),[\s\S]*td:nth-child\(5\) \{\s*overflow: visible;/)
})

test('validator detail removes redundant browser-native white tooltips from visible data', () => {
  assert.doesNotMatch(validatorDetail, /cosmos-validator-shares" title=/)
  assert.doesNotMatch(validatorDetail, /className="cosmos-validator-delegated" title=/)
  assert.doesNotMatch(validatorDetail, /className="cosmos-validator-delegation-share" title=/)
  assert.doesNotMatch(validatorDetail, /<code title=\{item\.account_address\}/)
  assert.doesNotMatch(validatorDetail, /cosmos-validator-reward-usd" title=/)
  assert.doesNotMatch(validatorDetail, /Sorts currently loaded delegators only\./)
  assert.doesNotMatch(validatorDetail, /Share of this validator's total delegator shares\./)
})
