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
  assert.match(page, /headlineAssets = configuredAssets\.slice\(0, 2\)/)
  assert.doesNotMatch(page, /uatone/)
  assert.doesNotMatch(page, /uphoton/)
  assert.doesNotMatch(page, /ATONE Balance/)
  assert.doesNotMatch(page, /PHOTON Balance/)
})

test('account page contains the agreed balance staking reward and unbonding surfaces', () => {
  for (const label of ['Balances', 'Delegations', 'Unbonding', 'Rewards', 'Account Information', 'Technical details']) {
    assert.ok(page.includes(label), `missing ${label}`)
  }
  assert.match(page, /validator\.operator_address/)
  assert.match(page, /entry\.completion_time/)
  assert.match(page, /entry\.remaining_seconds/)
  assert.match(page, /account\.withdraw_address/)
  assert.match(page, /account\.public_key/)
})

test('account page stays aligned with the explorer panel and theme system', () => {
  assert.match(page, /panel cosmos-account-hero/)
  assert.match(page, /card status-card cosmos-account-summary-card/)
  assert.match(css, /var\(--color-border\)/)
  assert.match(css, /var\(--color-accent\)/)
  assert.match(css, /var\(--color-text-secondary\)/)
  assert.match(css, /@media \(max-width: 680px\)/)
})
