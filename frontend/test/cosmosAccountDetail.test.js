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

test('account hero mirrors validator identity language with network logo and adjacent address copy', () => {
  assert.match(page, /cosmos-account-hero__profile/)
  assert.match(page, /cosmos-account-network-logo/)
  assert.match(page, /network\.presentation\?\.networkIconSrc/)
  assert.match(page, /cosmos-account-hero__identity/)
  assert.match(page, /<h1>Account<\/h1>/)
  assert.match(page, /cosmos-account-identity-line/)
  assert.match(page, /<AddressValue value=\{account\.address\} label="account address" \/>/)
  assert.match(css, /\.cosmos-account-network-logo \{[^}]*width: 86px[^}]*height: 86px/)
  assert.match(css, /\.cosmos-account-address-value \{[^}]*display: inline-flex[^}]*width: fit-content[^}]*gap: 7px/)
})

test('validator relation stays on the wallet line but is pushed to the right edge', () => {
  const lineStart = page.indexOf('cosmos-account-identity-line')
  const lineEnd = page.indexOf('</div>', lineStart)
  const identityLine = page.slice(lineStart, lineEnd)
  assert.match(identityLine, /This account belongs to validator/)
  assert.match(identityLine, /cosmos-account-validator-relation/)
  assert.match(css, /\.cosmos-account-identity-line \{[^}]*width: 100%/)
  assert.match(css, /\.cosmos-account-validator-relation \{[^}]*margin: 0 0 0 auto[^}]*color: var\(--color-text-secondary\)[^}]*font-size: 11px/)
  assert.match(css, /\.cosmos-account-validator-relation a \{[^}]*color: var\(--color-text-bright\)[^}]*font-weight: 700/)
  assert.match(css, /\.cosmos-account-validator-relation a:hover,[^}]*focus-visible \{ color: var\(--color-accent\); \}/)
})

test('summary cards reuse validator colors and keep the more compact account height', () => {
  assert.match(page, /cosmos-validator-hero__metrics cosmos-account-summary-grid/)
  assert.match(page, /card status-card cosmos-validator-summary__card cosmos-account-summary-card/)
  assert.match(css, /\.cosmos-account-hero \.cosmos-account-summary-grid > article \{[^}]*min-height: 96px[^}]*padding: 15px 16px/)
  assert.match(css, /\.cosmos-account-hero \.cosmos-account-summary-grid > article:hover \{ background: var\(--color-overlay-hover\); \}/)
  assert.doesNotMatch(css, /\.cosmos-account-summary-card \{[^}]*background:/)
})

test('account headline numbers use the UI font and keep USD on the same value line with breathing room', () => {
  assert.match(css, /\.cosmos-account-hero \.cosmos-account-summary-grid > article > strong \{[^}]*display: inline-block[^}]*margin-right: 12px[^}]*font-family: var\(--font-ui\)[^}]*font-size: clamp\(18px, 1\.55vw, 22px\)/)
  assert.match(css, /\.cosmos-account-summary-card > \.cosmos-account-usd \{[^}]*display: inline-block[^}]*margin: 0[^}]*font-size: 11px[^}]*font-weight: 600[^}]*vertical-align: baseline/)
  assert.match(css, /\.cosmos-account-summary-card__meta \{[^}]*font-family: var\(--font-ui\)/)
})

test('wallet assets replace the standalone balances panel and stay dynamic', () => {
  assert.match(page, /Wallet assets/)
  assert.match(page, /cosmos-account-hero__wallet-assets/)
  assert.match(page, /balanceCoins\.map\(\(coin\) => <WalletAsset/)
  assert.match(page, /configuredAssets\.map\(\(asset\) => coinFor\(account\.balances, asset\.base\)/)
  assert.match(page, /account\.balances \|\| \[\]\)\.filter\(\(coin\) => !configuredDenoms\.has\(coin\.denom\) && hasAmount\(coin\)\)/)
  assert.doesNotMatch(page, /<h2>Balances<\/h2>/)
  assert.doesNotMatch(page, /cosmos-account-balances/)
  assert.match(css, /\.cosmos-account-hero__wallet-assets \{[^}]*border-top: 1px solid var\(--color-border-soft\)/)
  assert.match(css, /\.cosmos-account-wallet-assets-grid \{[^}]*flex-wrap: wrap/)
})

test('wallet asset labels amounts and optional USD share one compact line', () => {
  const walletAssetRule = css.match(/\.cosmos-account-wallet-asset \{([^}]*)\}/)?.[1] || ''
  assert.match(walletAssetRule, /min-width: 168px/)
  assert.match(walletAssetRule, /grid-template-columns: auto auto auto/)
  assert.match(walletAssetRule, /grid-template-rows: 1fr/)
  assert.match(walletAssetRule, /align-items: center/)
  assert.match(walletAssetRule, /gap: 0 8px/)
  assert.match(walletAssetRule, /padding: 8px 9px/)
  assert.match(css, /\.cosmos-account-wallet-asset > span \{[^}]*grid-column: 1[^}]*grid-row: 1[^}]*align-self: center/)
  assert.match(css, /\.cosmos-account-wallet-asset > strong \{[^}]*grid-column: 2[^}]*grid-row: 1[^}]*align-self: center/)
  assert.match(css, /\.cosmos-account-wallet-asset > \.cosmos-account-usd \{[^}]*grid-column: 3[^}]*grid-row: 1[^}]*align-self: center/)
})

test('native-token USD uses the configured native denom and existing market endpoint without hover tooltips', () => {
  assert.match(page, /useCosmosResource\(`\/api\/networks\/\$\{network\.id\}\/market`, 30000\)/)
  assert.match(page, /function approximateUsd\(coin, network, market\)/)
  assert.match(page, /const nativeDenom = network\.presentation\?\.nativeDenom \|\| network\.assets\?\.\[0\]\?\.base/)
  assert.match(page, /network\.assets\?\.find\(\(asset\) => asset\.base === nativeDenom\) \|\| network\.assets\?\.\[0\]/)
  assert.match(page, /coin\?\.denom !== marketAsset\.base/)
  assert.match(page, /<SummaryCard label="Balance" usd=\{balanceUsd\}>/)
  assert.match(page, /<SummaryCard label="Delegated" usd=\{delegatedUsd\}/)
  assert.match(page, /<SummaryCard label="Rewards" usd=\{rewardsUsd\}/)
  assert.doesNotMatch(page, /Approximate USD value · CoinGecko/)
  assert.match(css, /\.cosmos-account-usd \{[^}]*color: var\(--color-success\)[^}]*font-size: 9px[^}]*font-weight: 500/)
  assert.match(css, /\.cosmos-account-summary-card > \.cosmos-account-usd \{[^}]*font-size: 11px[^}]*font-weight: 600/)
})

test('delegations absorb reward-only validator rows without a duplicate rewards section', () => {
  assert.match(page, /function buildDelegationRows\(delegations, rewardsByValidator, bondDenom\)/)
  assert.match(page, /rewardsByOperator = new Map/)
  assert.match(page, /hasAmount\(delegation\.balance\) \|\| rewards\.some\(hasAmount\)/)
  assert.match(page, /balance: bondDenom \? \{ denom: bondDenom, amount: '0' \} : null/)
  assert.match(page, /delegationRows = buildDelegationRows\(account\.delegations, account\.rewards_by_validator, account\.bond_denom\)/)
  assert.match(page, /delegationRows\.map/)
  assert.match(page, /delegationSurfaceAvailable = stakingAvailable \|\| rewardsAvailable/)
  assert.match(page, /rewardsAvailable \? <CoinStack coins=\{row\.rewards\} network=\{network\} market=\{market\.data\} \/>/)
  assert.match(page, /delegationCount = activeDelegations\.length/)
  assert.doesNotMatch(page, /cosmos-account-rewards/)
  assert.doesNotMatch(page, /cosmos-account-reward-total/)
  assert.doesNotMatch(page, /cosmos-account-reward-breakdown/)
  assert.doesNotMatch(page, /<h2>Rewards<\/h2>/)
})

test('delegation rewards show native-token USD inline and stay multi-asset safe', () => {
  assert.match(page, /function CoinStack\(\{ coins, network, market \}\)/)
  assert.match(page, /const usd = approximateUsd\(coin, network, market\)/)
  assert.match(page, /cosmos-account-coin-line/)
  assert.match(page, /cosmos-account-reward-usd/)
  assert.match(css, /\.cosmos-account-coin-line \{[^}]*display: flex[^}]*align-items: baseline[^}]*gap: 9px/)
  assert.match(css, /\.cosmos-account-reward-usd \{[^}]*color: var\(--color-success\)[^}]*font-size: 9px[^}]*font-weight: 600/)
})

test('delegation columns are balanced and headings match validator table typography', () => {
  assert.match(css, /th:nth-child\(1\)[^}]*width: 34%/)
  assert.match(css, /th:nth-child\(2\)[^}]*width: 18%/)
  assert.match(css, /th:nth-child\(3\)[^}]*width: 24%/)
  assert.match(css, /th:nth-child\(4\)[^}]*width: 24%/)
  assert.match(css, /\.cosmos-account-delegations th \{[^}]*font-family: inherit[^}]*font-size: 10px[^}]*font-weight: 700[^}]*text-transform: uppercase[^}]*letter-spacing: 0/)
})

test('validator status stays explicit for active inactive jailed and unknown rows', () => {
  assert.match(page, /cosmos-account-status is-\$\{row\.validator\.category \|\| 'unknown'\}/)
  assert.match(page, /row\.validator\.category \|\| 'Unknown'/)
  assert.match(css, /\.cosmos-account-status\.is-active \{ color: var\(--color-success\); \}/)
  assert.match(css, /\.cosmos-account-status\.is-jailed \{ color: var\(--color-error\); \}/)
})

test('validator monikers use the shared Cosmos bright-to-accent color contract', () => {
  assert.doesNotMatch(page, /className="accent-value"/)
  assert.match(css, /\.cosmos-account-validator > a \{[^}]*color: var\(--color-text-bright\)/)
  assert.match(css, /\.cosmos-account-validator > a:hover,[^}]*focus-visible \{ color: var\(--color-accent\); \}/)
})

test('reward summary stays multi-asset and prefers the configured primary denom for the headline', () => {
  assert.match(page, /visibleRewards = \(account\.rewards_total \|\| \[\]\)\.filter\(hasAmount\)/)
  assert.match(page, /rewardHeadline = coinFor\(visibleRewards, primaryDenom\) \|\| visibleRewards\[0\]/)
  assert.match(page, /otherRewardCount = visibleRewards\.filter/)
  assert.match(page, /<SummaryCard label="Rewards"/)
  assert.doesNotMatch(page, /visibleRewards\.map/)
})

test('unbonding follows the consolidated delegations section and stays before technical details', () => {
  const delegationsIndex = page.indexOf('cosmos-account-delegations')
  const unbondingIndex = page.indexOf('cosmos-account-unbonding')
  const technicalIndex = page.indexOf('cosmos-account-technical')
  assert.ok(delegationsIndex > -1 && unbondingIndex > delegationsIndex && technicalIndex > unbondingIndex)
})

test('account page keeps wallet delegations unbonding reward summary and technical surfaces', () => {
  for (const label of ['Wallet assets', 'Delegations', 'Unbonding', 'Technical details']) {
    assert.ok(page.includes(label), `missing ${label}`)
  }
  assert.match(page, /<SummaryCard label="Rewards"/)
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
  assert.match(page, /card status-card cosmos-validator-summary__card cosmos-account-summary-card/)
  assert.match(css, /radial-gradient\(circle at 48px 44px, var\(--color-accent-soft\), transparent 150px\), var\(--color-card\)/)
  assert.match(css, /var\(--color-border\)/)
  assert.match(css, /var\(--color-accent\)/)
  assert.match(css, /var\(--color-text-secondary\)/)
  assert.match(css, /\.cosmos-account-technical dl \{ display: grid; grid-template-columns: repeat\(2/)
  assert.match(css, /@media \(max-width: 680px\)/)
})