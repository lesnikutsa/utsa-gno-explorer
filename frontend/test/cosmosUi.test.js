import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { formatProtocolDuration, formatProtocolPercent, formatSignedTokenAmount, formatTokenAmount } from '../src/utils/cosmosFormat.js'
import { normalizePublicCosmosNetwork } from '../src/utils/publicNetworkRegistry.js'
import { deriveBlockTimeMetrics } from '../src/utils/cosmosBlockTime.js'
import { cosmosLivenessRisk } from '../src/utils/cosmosSlashing.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const layout = read('../src/layouts/ExplorerLayout.jsx')
const sidebar = read('../src/components/Sidebar.jsx')
const overview = read('../src/pages/CosmosOverview.jsx')
const blocks = read('../src/pages/CosmosBlocks.jsx')
const transactions = read('../src/pages/CosmosTransactions.jsx')
const cosmosLayout = read('../src/layouts/CosmosExplorerLayout.jsx')
const topbar = read('../src/components/TopBar.jsx')
const networkSearch = read('../src/components/NetworkBlockSearch.jsx')
const parameterHelp = read('../src/components/ParameterHelp.jsx')
const validatorIdentity = read('../src/components/CosmosValidatorIdentity.jsx')
const networkMetadata = JSON.parse(read('../../networks/atomone-mainnet/network.json'))

test('AtomOne routes use the shared ExplorerLayout and retain block list and detail routes', () => {
  assert.doesNotMatch(app, /CosmosLayout/)
  assert.match(app, /<CosmosExplorerLayout network=\{network\}>/)
  assert.match(cosmosLayout, /<ExplorerLayout/)
  assert.match(app, /<CosmosBlocks network=\{network\}/)
  assert.match(app, /<CosmosBlockDetail network=\{network\} height=\{rawHeight\}/)
  assert.match(blocks, /\/blocks\/\$\{height\}/)
  assert.match(layout, /<Sidebar/)
  assert.match(layout, /<TopBar/)
})

test('capability menu resolves only implemented AtomOne routes inside the selected network', () => {
  assert.match(sidebar, /hasNetworkCapability\(selectedNetwork, capability\)/)
  assert.match(sidebar, /selectedNetwork\.family === 'cosmos'/)
  assert.match(sidebar, /`\/networks\/\$\{selectedNetwork\.id\}/)
  assert.deepEqual(networkMetadata.capabilities, ['overview', 'blocks', 'transactions', 'validators', 'governance', 'network-parameters'])
  assert.match(app, /<CosmosTransactions network=\{network\}/)
  assert.match(app, /<CosmosValidators network=\{network\}/)
  assert.ok(networkMetadata.capabilities.includes('transactions'))
  assert.ok(networkMetadata.capabilities.includes('governance'))
  for (const capability of ['realms', 'tokens']) {
    assert.ok(!networkMetadata.capabilities.includes(capability))
  }
})

test('Cosmos Transactions route and compact list preserve Explorer contracts', () => {
  assert.match(app, /<CosmosTransactions network=\{network\}/)
  assert.match(transactions, /<h1>Transactions<\/h1>/)
  for (const heading of ['Time', 'Type', 'Tx hash', 'Block', 'Status', 'Fee', 'Gas']) assert.match(transactions, new RegExp(`<th>${heading}`))
  assert.match(transactions, /dateTime=\{row\.timestamp\} data-tooltip=\{row\.timestamp\}/)
  assert.doesNotMatch(transactions, /dateTime=\{row\.timestamp\} title=/)
  assert.match(transactions, /relativeTime\(row\.timestamp\)/)
  assert.match(transactions, /transactions\/history\?limit=20/)
  assert.match(transactions, /cursor \? null : 30000/)
  assert.match(transactions, /encodeURIComponent\(cursor\)/)
  assert.match(transactions, /resource\.data\.newer_cursor/)
  assert.match(transactions, /resource\.data\.older_cursor/)
  assert.match(transactions, /Live · every 30s/)
  assert.match(transactions, /Stale · last successful data/)
  assert.match(transactions, /indexing_unavailable/)
  assert.match(transactions, /No transactions in this result window/)
  assert.match(transactions, /message_count > 1/)
  assert.match(transactions, /blocks\/\$\{row\.height\}/)
  assert.doesNotMatch(transactions, /transactions\/\$\{row\.tx_hash\}/)
})

test('AtomOne overview shares dashboard cards and tables without raw responsive definitions', () => {
  assert.match(overview, /className="status-grid"/)
  assert.match(overview, /className="dashboard-grid cosmos-dashboard-grid"/)
  assert.match(overview, /<Card eyebrow="Latest Block"/)
  assert.match(overview, /<DataTable columns=\{blockColumns\}/)
  assert.match(overview, /Validators by Missed Blocks/)
  assert.doesNotMatch(overview, /AtomOne Overview|Cosmos network/)
  assert.match(overview, /updating=\{updatedHeight === latestHeight\}/)
  assert.match(overview, /'is-new-row' : 'is-settling-row'/)
  assert.match(overview, /imageSrc=\{row\.avatar_url\}/)
  assert.match(overview, /imageSrc=\{row\.proposer_avatar_url\}/)
  assert.match(overview, /imageSrc=\{row\.avatar_url\} showTitles=\{false\}/)
  assert.match(overview, /imageSrc=\{row\.proposer_avatar_url\} showTitles=\{false\}/)
  assert.doesNotMatch(overview, /title=\{row\.proposer\}/)
})

test('Cosmos TopBar keeps the shared search and block-time UI while scoping block navigation', () => {
  assert.doesNotMatch(topbar, /UTSA Explorer/)
  assert.match(topbar, /NetworkBlockSearch/)
  assert.match(networkSearch, /Search blocks, transactions, accounts, or validators/)
  assert.match(networkSearch, /`\/networks\/\$\{network\.id\}\/blocks\/\$\{value\}`/)
  assert.match(networkSearch, /\^\[0-9A-Fa-f\]\{64\}\$/)
  assert.match(networkSearch, /transactions\/\$\{encodeURIComponent\(value\)\}/)
  assert.match(networkSearch, /blocks\/\$\{transaction\.height\}\/transactions\/\$\{transaction\.index\}/)
  assert.match(topbar, /Search blocks, transactions, accounts, or validators/)
  assert.match(cosmosLayout, /averageBlockTimeSeconds=\{blockTime\.average\}/)
  assert.doesNotMatch(app, /healthState="healthy"/)
})

test('Cosmos block-time metrics use consecutive recent timestamps', () => {
  const metrics = deriveBlockTimeMetrics([
    { height: 3, timestamp: '2026-08-30T00:00:12Z' },
    { height: 2, timestamp: '2026-08-30T00:00:05Z' },
    { height: 1, timestamp: '2026-08-30T00:00:00Z' },
  ])
  assert.deepEqual(metrics, { average: 6, intervals: [5, 7], sampleSize: 3 })
})

test('Cosmos root route is exact while Blocks owns list and detail routes', () => {
  assert.match(sidebar, /pathname === href \|\| pathname === `\$\{href\}\/`/)
  assert.match(sidebar, /pathname === href \|\| pathname\.startsWith\(`\$\{href\}\/`\)/)
})

test('Cosmos protocol values format readably without floating point arithmetic', () => {
  assert.equal(formatProtocolPercent('0.394996939290177773'), '39.50%')
  assert.equal(formatProtocolPercent('0.200435214001358364'), '20.04%')
  assert.equal(formatProtocolDuration('1814400s'), '21 days')
  assert.equal(formatTokenAmount('60810000000000', 6, 'ATONE'), '60.81M ATONE')
  assert.equal(formatSignedTokenAmount('-40000', 6, 'ATONE'), '-0.04 ATONE')
  assert.equal(formatSignedTokenAmount('40000', 6, 'ATONE'), '+0.04 ATONE')
})

test('external AtomOne logo remains configuration-driven and normalizes into selector metadata', () => {
  const normalized = normalizePublicCosmosNetwork({ ...networkMetadata, address_prefixes: {} })
  assert.equal(normalized.presentation.networkIconSrc, networkMetadata.logo_url)
  assert.match(networkMetadata.logo_url, /^https:\/\//)
  assert.doesNotMatch(sidebar, /Atomone\.png|atomone.*logo/i)
  assert.match(sidebar, /chain-select__network-identity/)
})

test('parameter help and validator identity have keyboard, touch, and failure fallbacks', () => {
  assert.match(parameterHelp, /aria-expanded=\{open\}/)
  assert.match(parameterHelp, /event\.key === 'Escape'/)
  assert.match(parameterHelp, /document\.addEventListener\('pointerdown'/)
  assert.match(parameterHelp, /pointerType\.current === 'touch'/)
  assert.match(parameterHelp, /createPortal/)
  assert.match(validatorIdentity, /onError=\{\(\) => setFailed\(true\)\}/)
  assert.match(validatorIdentity, /initials\(moniker\)/)
})

test('market history and advanced parameter failures stay optional', () => {
  assert.match(overview, /history\?\.points \|\| \[\]/)
  assert.match(overview, /path && <svg/)
  assert.match(overview, /Optional market enrichment/)
  assert.match(overview, /<summary>More parameters<\/summary>/)
})

test('Cosmos SDK liveness boundaries preserve strict greater-than semantics', () => {
  const base = { startHeight: 100, currentHeight: 201, signedWindow: 100, minimumSigned: '0.5', averageBlockSeconds: 5 }
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 50 }).overThreshold, false)
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 51 }).overThreshold, true)
  const initialWindow = cosmosLivenessRisk({ ...base, currentHeight: 150, missedBlocks: 50 })
  assert.equal(initialWindow.overThreshold, false)
  assert.equal(initialWindow.earliestBlocks, 51)
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 0 }).budgetLeft, 50)
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 24 }).tone, 'healthy')
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 25 }).tone, 'warning-low')
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 38 }).tone, 'warning-high')
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 45 }).tone, 'danger')
  assert.equal(cosmosLivenessRisk({ ...base, missedBlocks: 51 }).tone, 'danger')
})

test('native and community amounts use configured denom metadata without AtomOne hardcoding', () => {
  assert.equal(formatTokenAmount('4792296226638.817868034474200083', 6, 'COIN'), '4.79M COIN')
  const stakingSource = overview.slice(overview.indexOf('Staking / Validator Set'), overview.indexOf('Inflation / Mint'))
  assert.doesNotMatch(stakingSource, /ATONE|, 6,/)
  assert.match(overview, /network\.assets\?\.find\(\(item\) => item\.base === denom\)/)
})

test('final Cosmos polish exposes stale, footer, product, Mint, and node strip contracts', () => {
  const cosmosLayoutSource = read('../src/layouts/CosmosExplorerLayout.jsx')
  const footer = read('../src/components/CosmosResourceFooter.jsx')
  const explorerLayout = read('../src/layouts/ExplorerLayout.jsx')
  assert.match(overview, /Stale · last successful data/)
  assert.match(cosmosLayoutSource, /blocks\.stale \? 'degraded'/)
  assert.match(explorerLayout, /enabled: chainIdOverride === undefined/)
  assert.match(sidebar, /<UtsaLogo projectName=\{networkProfile\.projectName\}/)
  assert.match(footer, /https:\/\/utsa\.gitbook\.io\/services/)
  assert.match(footer, /https:\/\/teletype\.media\/@lesnik13utsa/)
  assert.match(footer, /target="_blank" rel="noopener noreferrer"/)
  const mintSource = overview.slice(overview.indexOf('Inflation / Mint'), overview.indexOf('Governance'))
  assert.doesNotMatch(mintSource, /<Advanced>/)
  assert.match(overview, /className="panel cosmos-node-strip"/)
})

test('RPC, edge help, validator risk, chart, and footer polish follow shared interactions', () => {
  const rpc = read('../src/components/CosmosRpcStatus.jsx')
  const footer = read('../src/components/CosmosResourceFooter.jsx')
  assert.match(rpc, /onPointerEnter=.*pointerType === 'mouse'/)
  assert.match(rpc, /onFocus=\{\(\) => setOpen\(true\)\}/)
  assert.match(rpc, /marker = 'Manual'/)
  assert.match(rpc, /Automatic bounded failover/)
  assert.match(parameterHelp, /getBoundingClientRect/)
  assert.match(parameterHelp, /window\.innerWidth - width - 10/)
  assert.match(parameterHelp, /document\.body/)
  assert.match(overview, /cosmos-market__guides/)
  assert.match(overview, /Budget left:/)
  assert.match(footer, /className="page-footer"/)
})

test('liveness risk layout keeps help, secondary type, and equal tracks scoped to one cell', () => {
  const styles = read('../src/styles/app.css')
  assert.match(overview, /className="cosmos-risk__summary"/)
  assert.match(overview, /className="cosmos-risk__secondary">Budget left:/)
  assert.match(overview, /className="cosmos-risk__secondary">Penalty ETA:/)
  assert.match(styles, /cosmos-risk__summary \{[^}]*grid-template-columns: max-content max-content minmax\(0, 1fr\) 15px/)
  assert.match(styles, /cosmos-risk__summary \.parameter-help \{ grid-column: 4; justify-self: end/)
  assert.match(styles, /cosmos-risk__bar \{[^}]*width: 100%/)
  assert.match(styles, /cosmos-risk__secondary, \.cosmos-validator > span/)
  assert.match(overview, /\.slice\(0, 6\)/)
})

test('market uses a responsive three-column composition without a chart dependency', () => {
  const styles = read('../src/styles/app.css')
  assert.match(styles, /cosmos-market \{[^}]*grid-template-columns: minmax\(190px, \.7fr\) minmax\(180px, \.7fr\) minmax\(360px, 1\.6fr\)/)
  assert.match(styles, /@media \(max-width: 800px\)[^{]*\{ \.cosmos-market \{ grid-template-columns: repeat\(2/)
  assert.match(overview, /cosmos-market__guides/)
})
