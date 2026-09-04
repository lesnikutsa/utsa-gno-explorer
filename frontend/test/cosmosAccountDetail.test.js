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

test('account summary stays chain-generic with exactly four logical cards', () => {
  assert.match(page, /const configuredAssets = network\.assets \|\| \[\]/)
  assert.match(page, /const primaryDenom = network\.presentation\?\.nativeDenom/)
  for (const label of ['Balance', 'Delegated', 'Rewards', 'Unbonding']) {
    assert.match(page, new RegExp(`<SummaryCard label="${label}"`))
  }
  assert.doesNotMatch(page, /label=\{`\$\{asset\.symbol\} Balance`\}/)
  assert.doesNotMatch(page, /uatone/)
  assert.doesNotMatch(page, /uphoton/)
  assert.doesNotMatch(page, /ATONE Balance/)
  assert.doesNotMatch(page, /PHOTON Balance/)
})

test('balances panel shows configured assets and extra live bank denoms dynamically', () => {
  assert.match(page, /<h2>Balances<\/h2>/)
  assert.match(page, /configuredAssets\.map\(\(asset\) => coinFor\(account\.balances, asset\.base\)/)
  assert.match(page, /account\.balances \|\| \[\]\)\.filter\(\(coin\) => !configuredDenoms\.has\(coin\.denom\) && hasAmount\(coin\)\)/)
  assert.match(page, /balanceCoins\.map/)
  assert.match(css, /\.cosmos-account-balance-grid/)
})

test('current delegations hide zero-balance historical rows while rewards remain independent', () => {
  assert.match(page, /activeDelegations = \(account\.delegations \|\| \[\]\)\.filter\(\(row\) => hasAmount\(row\.balance\)\)/)
  assert.match(page, /activeDelegations\.map/)
  assert.match(page, /account\.rewards_by_validator\.map/)
  assert.match(page, /delegationCount = activeDelegations\.length/)
})

test('rewards stay multi-asset and prefer the configured primary denom for the headline', () => {
  assert.match(page, /visibleRewards = \(account\.rewards_total \|\| \[\]\)\.filter\(hasAmount\)/)
  assert.match(page, /rewardHeadline = coinFor\(visibleRewards, primaryDenom\) \|\| visibleRewards\[0\]/)
  assert.match(page, /visibleRewards\.map/)
  assert.match(page, /otherRewardCount = visibleRewards\.filter/)
})

test('unbonding is placed after rewards and immediately before technical details', () => {
  const rewardsIndex = page.indexOf('cosmos-account-rewards')
  const unbondingIndex = page.indexOf('cosmos-account-unbonding')
  const technicalIndex = page.indexOf('cosmos-account-technical')
  assert.ok(rewardsIndex > -1 && unbondingIndex > rewardsIndex && technicalIndex > unbondingIndex)
})

test('account page keeps staking reward unbonding and technical surfaces', () => {
  for (const label of ['Balances', 'Delegations', 'Unbonding', 'Rewards', 'Technical details']) {
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

test('account page removes redundant network and section helper copy', () => {
  assert.doesNotMatch(page, /cosmos-account-eyebrow/)
  assert.doesNotMatch(page, /network\.presentation\?\.projectName/)
  assert.doesNotMatch(page, /Current staking positions/)
  assert.doesNotMatch(page, /Tokens currently leaving staking/)
  assert.doesNotMatch(page, /Claimable staking rewards/)
})

test('empty states stay compact and technical labels match validator detail typography', () => {
  assert.match(page, /cosmos-account-empty-state/)
  assert.match(css, /\.cosmos-account-panel > \.cosmos-account-empty-state \{[^}]*font-size: 10px/)
  assert.match(css, /\.cosmos-account-technical dt \{[^}]*font-size: 9px[^}]*font-weight: 700[^}]*text-transform: uppercase/)
  assert.match(css, /\.cosmos-account-technical dd \{[^}]*font-size: 12px[^}]*font-weight: 600/)
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
