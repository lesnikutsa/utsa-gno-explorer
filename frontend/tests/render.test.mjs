import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', optimizeDeps: { noDiscovery: true } })
test.after(async () => server.close())

test('Cosmos overview renders data, zero values, empty validators, and SectionError', async () => {
  const { CosmosOverviewView } = await server.ssrLoadModule('/src/pages/CosmosOverview.jsx')
  const error = { error: { code: 'section_unavailable' } }
  const data = {
    network: { operational_state: 'healthy', current_local_height: 42, latest_block_time: '2026-08-30T00:00:00Z', catching_up: false },
    assets_and_supply: { assets: [{ base: 'uatone', symbol: 'ATONE', exponent: 6, total_supply: '0' }] },
    staking: { bonded_tokens: '0', bonded_ratio: '0', active_validator_count: 0 },
    mint: error, slashing: { signed_blocks_window: 100, allowed_missed_threshold: 50 },
    governance: { quorum: '0.4', threshold: '0.5', voting_period: '1s' },
    distribution: { community_tax: '0', withdraw_address_enabled: false },
    top_active_validators_by_missed_blocks: [],
  }
  const network = { presentation: { projectName: 'AtomOne' }, assets: [{ symbol: 'ATONE' }] }
  const html = renderToStaticMarkup(React.createElement(CosmosOverviewView, { data, network, market: null, marketError: 'offline' }))
  assert.match(html, /AtomOne Overview/)
  assert.match(html, /0\.0/)
  assert.match(html, /Section unavailable/)
  assert.match(html, /No active validator misses reported/)
})

test('existing Gno Card still renders its children', async () => {
  const { Card } = await server.ssrLoadModule('/src/components/Card.jsx')
  const html = renderToStaticMarkup(React.createElement(Card, { eyebrow: 'Gno card', value: 'preserved', meta: 'contract' }))
  assert.match(html, /preserved/)
})
