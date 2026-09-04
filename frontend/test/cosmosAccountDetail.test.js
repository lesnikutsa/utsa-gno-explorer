import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/cosmos-account-detail.css', import.meta.url), 'utf8')

test('Cosmos account route is network-scoped and separate from the Gno account route', () => {
  assert.match(app, /cosmosAccountMatch = path\.match/)
  assert.match(app, /CosmosAccountDetail network=\{network\} address=\{decodeURIComponent\(cosmosAccountMatch\[2\]\)\}/)
  assert.match(app, /const accountDetailMatch = path\.match\(\/\^\\\/accounts/)
})

test('account page is multi-asset and uses the network registry instead of AtomOne hardcoding', () => {
  assert.match(page, /const configuredAssets = network\.assets \|\| \[\]/)
  assert.match(page, /configuredAssets\.map\(\(asset\) => <SummaryCard/)
  assert.doesNotMatch(page, /uatone/)
  assert.doesNotMatch(page, /uphoton/)
  assert.doesNotMatch(page, /ATONE Balance/)
  assert.doesNotMatch(page, /PHOTON Balance/)
})

test('balances are shown once in the hero rather than repeated in a second panel', () => {
  assert.match(page, /label=\{`\$\{asset\.symbol\} Balance`\}/)
  assert.doesNotMatch(page, /<h2>Balances<\/h2>/)
  assert.doesNotMatch(page, /Current bank balances/)
})

test('current delegations hide zero-balance historical rows while rewards remain independent', () => {
  assert.match(page, /activeDelegations = \(account\.delegations \|\| \[\]\)\.filter\(\(row\) => hasAmount\(row\.balance\)\)/)
  assert.match(page, /activeDelegations\.map/)
  assert.match(page, /account\.rewards_by_validator\.map/)
  assert.match(page, /delegationCount = activeDelegations\.length/)
})

test('account page keeps staking reward unbonding and technical surfaces', () => {
  for (const label of ['Delegations', 'Unbonding', 'Rewards', 'Technical details']) {
    assert.ok(page.includes(label), `missing ${label}`)
  }
  assert.doesNotMatch(page, /Account Information/)
  assert.match(page, /Account number/)
  assert.match(page, /Sequence/)
  assert.match(page, /entry\.completion_time/)
  assert.match(page, /entry\.remaining_seconds/)
  assert.match(page, /account\.withdraw_address/)
  assert.match(page, /account\.public_key/)
})

test('summary cards include unbonding and preserve tiny non-zero reward visibility', () => {
  assert.match(page, /<SummaryCard label="Unbonding"/)
  assert.match(page, /sumUnbonding\(account\.unbonding\)/)
  assert.match(page, /<0\.000001 \$\{asset\.symbol\}/)
})

test('account page stays aligned with the explorer panel and theme system', () => {
  assert.match(page, /panel cosmos-account-hero/)
  assert.match(page, /card status-card cosmos-account-summary-card/)
  assert.match(css, /linear-gradient\(135deg, var\(--color-accent-soft\), var\(--color-card-gradient-end\)\)/)
  assert.match(css, /var\(--color-border\)/)
  assert.match(css, /var\(--color-accent\)/)
  assert.match(css, /var\(--color-text-secondary\)/)
  assert.match(css, /\.cosmos-account-technical dl \{ display: grid; grid-template-columns: repeat\(2/)
  assert.match(css, /@media \(max-width: 680px\)/)
})
