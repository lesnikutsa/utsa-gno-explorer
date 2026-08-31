import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { formatProtocolDuration, formatProtocolPercent, formatTokenAmount } from '../src/utils/cosmosFormat.js'
import { normalizePublicCosmosNetwork } from '../src/utils/publicNetworkRegistry.js'
import { deriveBlockTimeMetrics } from '../src/utils/cosmosBlockTime.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const layout = read('../src/layouts/ExplorerLayout.jsx')
const sidebar = read('../src/components/Sidebar.jsx')
const overview = read('../src/pages/CosmosOverview.jsx')
const blocks = read('../src/pages/CosmosBlocks.jsx')
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
  assert.deepEqual(networkMetadata.capabilities, ['overview', 'blocks', 'network-parameters'])
  for (const capability of ['transactions', 'validators', 'governance', 'realms', 'tokens']) {
    assert.ok(!networkMetadata.capabilities.includes(capability))
  }
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
})

test('Cosmos TopBar keeps the shared search and block-time UI while scoping block navigation', () => {
  assert.doesNotMatch(topbar, /UTSA Explorer/)
  assert.match(topbar, /NetworkBlockSearch/)
  assert.match(networkSearch, /Search blocks by height/)
  assert.match(networkSearch, /`\/networks\/\$\{network\.id\}\/blocks\/\$\{value\}`/)
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
  assert.match(parameterHelp, /onClick=\{\(\) => setOpen/)
  assert.match(validatorIdentity, /onError=\{\(\) => setFailed\(true\)\}/)
  assert.match(validatorIdentity, /initials\(moniker\)/)
})

test('market history and advanced parameter failures stay optional', () => {
  assert.match(overview, /history\?\.points \|\| \[\]/)
  assert.match(overview, /path && <svg/)
  assert.match(overview, /Optional market enrichment/)
  assert.match(overview, /<summary>More parameters<\/summary>/)
})
