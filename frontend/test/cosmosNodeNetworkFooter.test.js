import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('Cosmos pages share the Node / Network strip above the common footer', () => {
  const layout = read('../src/layouts/CosmosExplorerLayout.jsx')
  const strip = read('../src/components/CosmosNodeNetworkStrip.jsx')
  const overview = read('../src/pages/CosmosOverview.jsx')

  assert.match(layout, /usePathname\(\)/)
  assert.match(layout, /const overviewPath = `\/networks\/\$\{network\.id\}`/)
  assert.match(layout, /!isOverview && <CosmosNodeNetworkStrip network=\{network\} overview=\{overview\} \/>/)
  assert.match(layout, /<CosmosResourceFooter \/>/)

  // Overview already owns the same strip at the same visual position, so it is not duplicated there.
  assert.match(overview, /className="panel cosmos-node-strip"/)

  assert.match(strip, /Node \/ Network/)
  assert.match(strip, /endpoint-status/)
  assert.match(strip, /subscribeCosmosEndpointProvider/)
  assert.match(strip, /lowest_available_height/)
  assert.match(strip, /selectedTxIndex/)
  assert.match(strip, /RPC provider/)
  assert.match(strip, /RPC: \{rpcProvider\.label\}/)
})
