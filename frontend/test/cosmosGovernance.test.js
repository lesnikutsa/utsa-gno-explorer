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

test('Cosmos governance table mirrors validator numbering and keeps titles bounded', () => {
  assert.match(page, /<th>#<\/th><th>Title<\/th><th>Type<\/th><th>Status<\/th><th>Voting end<\/th><th>Vote split<\/th>/)
  assert.match(page, /className="cosmos-governance__proposal-id">\{proposal\.proposal_id\}/)
  assert.match(page, /cosmos-governance__title-tooltip/)
  assert.match(page, /data-tooltip=\{titleTooltip \|\| undefined\}/)
  assert.doesNotMatch(page, /title=\{proposal\.title\}/)
  assert.match(styles, /\.cosmos-governance__proposal-id \{[^}]*min-width: 23px;[^}]*height: 19px;/)
  assert.match(styles, /\.cosmos-governance__title \{[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/)
})

test('Cosmos governance dates are deterministic English UTC rather than browser locale', () => {
  assert.match(page, /const MONTHS = \['Jan', 'Feb', 'Mar'/)
  assert.match(page, /getUTCDate\(\)/)
  assert.match(page, /getUTCHours\(\)/)
  assert.match(page, /UTC`/)
  assert.doesNotMatch(page, /toLocaleDateString\(undefined/)
})

test('Cosmos governance keeps proposal status and readable centered Gno-inspired vote split visualisation', () => {
  assert.match(page, /cosmos-gov-type/)
  assert.match(page, /cosmos-gov-status/)
  assert.match(page, /cosmos-governance-votes__labels/)
  assert.match(page, /cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-governance-votes__labels \{[^}]*justify-content: center;[^}]*font-size: 10px;[^}]*font-weight: 700;/)
  assert.match(styles, /\.cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-gov-status--passed/)
})

test('Cosmos governance has its own network route and leaves legacy Gno governance routes intact', () => {
  assert.match(app, /blocks\|transactions\|validators\|governance/)
  assert.match(app, /<CosmosGovernance network=\{network\}/)
  assert.match(app, /if \(path === '\/governance'/)
  assert.match(app, /<Governance governancePage=\{governancePage\}/)
})
