import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('Cosmos pages share the compact node metrics strip above the common footer', () => {
  const layout = read('../src/layouts/CosmosExplorerLayout.jsx')
  const strip = read('../src/components/CosmosNodeNetworkStrip.jsx')
  const overview = read('../src/pages/CosmosOverview.jsx')

  assert.match(layout, /usePathname\(\)/)
  assert.match(layout, /const overviewPath = `\/networks\/\$\{network\.id\}`/)
  assert.match(layout, /!isOverview && <CosmosNodeNetworkStrip network=\{network\} overview=\{overview\} \/>/)
  assert.match(layout, /<CosmosResourceFooter \/>/)

  // Overview keeps its full titled Node / Network panel; other Cosmos pages use only the metric row.
  assert.match(overview, /<h2>Node \/ Network<\/h2>/)
  assert.doesNotMatch(strip, /<h2>Node \/ Network<\/h2>/)
  assert.doesNotMatch(strip, /panel__heading/)

  assert.match(strip, /endpoint-status/)
  assert.match(strip, /subscribeCosmosEndpointProvider/)
  assert.match(strip, /lowest_available_height/)
  assert.match(strip, /selectedTxIndex/)
  assert.match(strip, /RPC provider/)
})
