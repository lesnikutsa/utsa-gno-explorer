import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  cosmosApiNetworkId,
  cosmosProviderAlias,
  getCosmosEndpointProvider,
  rewriteCosmosApiUrl,
  setCosmosEndpointProvider,
} from '../src/utils/cosmosEndpointProvider.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

const withBrowserStorage = async (callback) => {
  const originalWindow = globalThis.window
  const originalCustomEvent = globalThis.CustomEvent
  const values = new Map()
  const events = []
  class TestCustomEvent {
    constructor(type, init = {}) { this.type = type; this.detail = init.detail }
  }
  globalThis.CustomEvent = TestCustomEvent
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.has(key) ? values.get(key) : null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key),
    },
    dispatchEvent: (event) => { events.push(event); return true },
    addEventListener: () => {},
    removeEventListener: () => {},
  }
  try {
    await callback({ values, events })
  } finally {
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
    if (originalCustomEvent === undefined) delete globalThis.CustomEvent
    else globalThis.CustomEvent = originalCustomEvent
  }
}

test('manual provider rewrites only provider-backed Cosmos network API requests', async () => {
  await withBrowserStorage(async ({ events }) => {
    const canonical = '/api/networks/atomone-mainnet/overview'
    assert.equal(cosmosApiNetworkId(canonical), 'atomone-mainnet')
    assert.equal(cosmosProviderAlias('atomone-mainnet', 'utsa'), 'atomone-mainnet-provider-utsa')
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'auto')
    assert.equal(rewriteCosmosApiUrl(canonical), canonical)

    setCosmosEndpointProvider('atomone-mainnet', 'utsa')
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'utsa')
    assert.equal(
      rewriteCosmosApiUrl(canonical),
      '/api/networks/atomone-mainnet-provider-utsa/overview',
    )
    assert.equal(
      rewriteCosmosApiUrl('/api/networks/atomone-mainnet/endpoint-status'),
      '/api/networks/atomone-mainnet/endpoint-status',
    )
    assert.equal(
      rewriteCosmosApiUrl('/api/networks/atomone-mainnet/market/history'),
      '/api/networks/atomone-mainnet/market/history',
    )
    assert.equal(rewriteCosmosApiUrl('/api/network'), '/api/network')
    assert.equal(events.at(-1)?.detail?.providerId, 'utsa')

    setCosmosEndpointProvider('atomone-mainnet', 'auto')
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'auto')
    assert.equal(rewriteCosmosApiUrl(canonical), canonical)
  })
})

test('disabled browser storage keeps an in-memory manual choice in the current tab', async () => {
  const originalWindow = globalThis.window
  globalThis.window = {
    dispatchEvent: () => true,
  }
  Object.defineProperty(globalThis.window, 'localStorage', {
    configurable: true,
    get() { throw new Error('disabled') },
  })
  try {
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'auto')
    setCosmosEndpointProvider('atomone-mainnet', 'itrocket')
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'itrocket')
    assert.equal(
      rewriteCosmosApiUrl('/api/networks/atomone-mainnet/blocks'),
      '/api/networks/atomone-mainnet-provider-itrocket/blocks',
    )
    setCosmosEndpointProvider('atomone-mainnet', 'auto')
  } finally {
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
  }
})

test('endpoint popup stays compact while exposing Auto and paired manual mode', () => {
  const component = read('../src/components/CosmosRpcStatus.jsx')
  const overview = read('../src/pages/CosmosOverview.jsx')
  const hook = read('../src/hooks/useCosmosResource.js')
  const service = read('../src/services/api.js')
  const styles = read('../src/styles/cosmos-endpoint-mode.css')

  assert.match(component, /<strong>Endpoint mode<\/strong>/)
  assert.match(component, /<strong>Auto<\/strong>/)
  assert.match(component, /Pin this RPC \+ API pair/)
  assert.match(component, /Automatic bounded failover/)
  assert.match(component, /Manual RPC \+ API pair/)
  assert.match(component, /Auto is currently using different RPC and API providers/)
  assert.match(component, /Provider health/)
  assert.match(component, /marker = 'Manual · '/)
  assert.match(component, /cosmos-endpoint-mode__height/)
  assert.match(component, /Height \{height\(provider\.rpc\.height\)\}/)
  assert.doesNotMatch(component, /<small>Height ·/)
  assert.doesNotMatch(component, /Reachable only means/)
  assert.doesNotMatch(component, /blockHeight/)
  assert.match(component, /onDiagnostics\?\.\(data\)/)
  assert.match(component, /onProviderMode\?\.\(providerMode\)/)
  assert.match(component, /window\.setInterval\(load, 30000\)/)
  assert.match(component, /if \(document\.hidden\) return/)
  assert.match(component, /endpoint-status/)

  assert.match(overview, /lowest_available_height/)
  assert.match(overview, /selectedTxIndex/)
  assert.match(overview, /formatRetainedBlocks/)
  assert.match(overview, /RPC: \{rpcProvider\.label\}/)
  assert.match(overview, /onDiagnostics=\{setEndpointDiagnostics\}/)
  assert.match(overview, /onProviderMode=\{setEndpointProviderMode\}/)

  assert.match(hook, /rewriteCosmosApiUrl\(url\)/)
  assert.match(hook, /subscribeCosmosEndpointProvider/)
  assert.match(service, /rewriteCosmosApiUrl\(`\$\{API_ROOT\}\$\{path\}`\)/)
  assert.match(styles, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.cosmos-endpoint-mode__health \{/)
  assert.match(styles, /\.cosmos-endpoint-mode__height \{/)
})
