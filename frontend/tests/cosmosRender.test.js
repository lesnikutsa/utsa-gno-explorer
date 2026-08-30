import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } })
after(() => vite.close())
const overview = await vite.ssrLoadModule('/src/pages/CosmosOverview.jsx')
const blocks = await vite.ssrLoadModule('/src/pages/CosmosBlocks.jsx')
const detail = await vite.ssrLoadModule('/src/pages/CosmosBlockDetail.jsx')
const topbar = await vite.ssrLoadModule('/src/components/TopBar.jsx')
const h = (component, props, ...children) => renderToStaticMarkup(React.createElement(component, props, ...children))

test('Overview metrics and validator section render real content', () => {
  assert.match(h(overview.CosmosSection, { title: 'Staking', data: {} }, React.createElement(overview.CosmosMetric, { label: 'Bonded ratio' }, '67.2%')), /Bonded ratio.*67.2%/s)
  const validators = [{ operator_address: 'atonevaloper1', moniker: 'Alice', missed_blocks_counter: 4, remaining_misses_before_threshold: 6, jailed: false, tombstoned: false }]
  assert.match(h(overview.ValidatorMissesSection, { data: validators }), /Alice.*4 missed.*6 to threshold/s)
  assert.match(h(overview.ValidatorMissesSection, { data: [] }), /No active validator misses are reported/)
  assert.match(h(overview.ValidatorMissesSection, { data: { error: { code: 'section_unavailable' } } }), /temporarily unavailable/)
})

test('Blocks table renders the #182 timestamp and fields', () => {
  const markup = h(blocks.CosmosBlocksTable, { network: { routePrefix: '/networks/atomone-mainnet' }, blocks: [{ height: 123, timestamp: '2026-01-02T03:04:05Z', proposer: 'ABCDEF0123456789', transaction_count: 2, hash: '0123456789ABCDEF' }] })
  assert.match(markup, /\/networks\/atomone-mainnet\/blocks\/123/)
  assert.match(markup, /2/)
  assert.doesNotMatch(markup, />—<\/td>/)
})

test('Cosmos top bar renders height-only search without mounting Gno search behavior', () => {
  const markup = h(topbar.CosmosTopBar, { onMenuClick() {}, healthState: 'healthy', theme: 'dark', onToggleTheme() {}, network: { routePrefix: '/networks/atomone-mainnet' } })
  assert.match(markup, /Search AtomOne block height/)
  assert.doesNotMatch(markup, /transactions, accounts, or validators/)
})

const cases = [
  [{ state: 'available', block: { height: 100, timestamp: '2026-01-02T03:04:05Z', hash: 'HASH', proposer: 'PROPOSER', transaction_count: 3 } }, /Completed block.*HASH.*PROPOSER/s],
  [{ state: 'future', target_height: 110, current_height: 100, eta: { status: 'estimated', remaining_blocks: 10, estimated_at: '2026-01-02T03:05:05Z', average_interval_seconds: '6.5', sample_interval_count: 99 } }, /Estimated.*Average interval.*6.5s.*Sample size.*99/s],
  [{ state: 'future', target_height: 110, current_height: 100, eta: null, eta_unavailable_reason: 'insufficient_sample' }, /Not enough completed block intervals/],
  [{ state: 'node_not_synced', current_height: 90 }, /synchronized only to height 90/],
  [{ state: 'history_unavailable', lowest_available_height: 50 }, /Lowest confirmed available height: 50/],
]
for (const [data, expected] of cases) test(`block detail renders ${data.state}`, () => assert.match(h(detail.CosmosBlockDetailContent, { data, height: 110, clock: Date.parse('2026-01-02T03:04:00Z') }), expected))
