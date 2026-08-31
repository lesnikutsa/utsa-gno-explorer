import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { formatProtocolDuration, formatProtocolPercent, formatTokenAmount } from '../src/utils/cosmosFormat.js'
import { normalizePublicCosmosNetwork } from '../src/utils/publicNetworkRegistry.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const layout = read('../src/layouts/ExplorerLayout.jsx')
const sidebar = read('../src/components/Sidebar.jsx')
const overview = read('../src/pages/CosmosOverview.jsx')
const blocks = read('../src/pages/CosmosBlocks.jsx')
const networkMetadata = JSON.parse(read('../../networks/atomone-mainnet/network.json'))

test('AtomOne routes use the shared ExplorerLayout and retain block list and detail routes', () => {
  assert.doesNotMatch(app, /CosmosLayout/)
  assert.match(app, /<ExplorerLayout chainId=\{network\.expectedChainId\}/)
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
  assert.match(overview, /title=\{exactTitle\(raw\)\}/)
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
})
