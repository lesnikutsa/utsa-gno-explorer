import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosGovernance.jsx')
const styles = read('../src/styles/cosmos-governance.css')
const app = read('../src/App.jsx')

test('Cosmos governance reuses validator summary, tabs and search structure', () => {
  assert.match(page, /cosmos-validator-summary cosmos-governance__summary/)
  assert.match(page, /cosmos-validator-toolbar cosmos-governance__toolbar/)
  assert.match(page, /cosmos-validator-tabs cosmos-governance__tabs/)
  assert.match(page, /Search proposal id, title or type/)
  assert.match(page, /Total proposals/)
  assert.match(page, /Rejected \/ failed/)
})

test('Cosmos governance table keeps proposal status and Gno-inspired vote split visualisation', () => {
  assert.match(page, /<th>Proposal<\/th><th>Title<\/th><th>Type<\/th><th>Status<\/th><th>Voting end<\/th><th>Vote split<\/th>/)
  assert.match(page, /cosmos-gov-type/)
  assert.match(page, /cosmos-gov-status/)
  assert.match(page, /cosmos-governance-votes__labels/)
  assert.match(page, /cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-gov-status--passed/)
})

test('Cosmos governance has its own network route and leaves legacy Gno governance routes intact', () => {
  assert.match(app, /blocks\|transactions\|validators\|governance/)
  assert.match(app, /<CosmosGovernance network=\{network\}/)
  assert.match(app, /if \(path === '\/governance'/)
  assert.match(app, /<Governance governancePage=\{governancePage\}/)
})
