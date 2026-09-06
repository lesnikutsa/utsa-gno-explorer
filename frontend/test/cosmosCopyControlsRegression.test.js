import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const blockDetail = read('../src/pages/CosmosBlockDetail.jsx')
const transactionDetail = read('../src/pages/CosmosTransactionDetail.jsx')
const validatorDetail = read('../src/pages/CosmosValidatorDetail.jsx')
const accountDetail = read('../src/pages/CosmosAccountDetail.jsx')
const copyStyles = read('../src/styles/cosmos-copy-controls.css')

for (const [name, source] of Object.entries({
  'Cosmos Block Detail': blockDetail,
  'Cosmos Transaction Detail': transactionDetail,
  'Cosmos Validator Detail': validatorDetail,
  'Cosmos Account Detail': accountDetail,
})) {
  test(`${name} copy buttons do not expose native title tooltips`, () => {
    const buttons = [...source.matchAll(/<CopyButton\b[^>]*\/>/g)].map((match) => match[0])
    assert.ok(buttons.length > 0)
    for (const button of buttons) assert.match(button, /showTitle=\{false\}/)
  })
}

test('block and transaction detail keep copy controls beside their values', () => {
  assert.match(copyStyles, /\.cosmos-block-detail \.cosmos-copy-value \{[\s\S]*width: fit-content;[\s\S]*justify-content: flex-start;[\s\S]*gap: 8px;/)
  assert.match(blockDetail, /import '\.\.\/styles\/cosmos-copy-controls\.css'/)
  assert.match(transactionDetail, /import '\.\.\/styles\/cosmos-copy-controls\.css'/)
})

test('validator Consensus Identity and Delegators keep their existing placement rules', () => {
  assert.doesNotMatch(copyStyles, /cosmos-validator-address|cosmos-validator-delegator/)
  assert.match(validatorDetail, /className=\{`cosmos-copy-value cosmos-validator-address/)
  assert.match(validatorDetail, /className=\{`cosmos-validator-delegator/)
})
