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

test('manual provider rewrites only Cosmos network API requests to a private alias', async () => {
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
    assert.equal(rewriteCosmosApiUrl('/api/network'), '/api/network')
    assert.equal(events.at(-1)?.detail?.providerId, 'utsa')

    setCosmosEndpointProvider('atomone-mainnet', 'auto')
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'auto')
    assert.equal(rewriteCosmosApiUrl(canonical), canonical)
  })
})

test('disabled browser storage safely falls back to Auto mode', async () => {
  const originalWindow = globalThis.window
  globalThis.window = {}
  Object.defineProperty(globalThis.window, 'localStorage', {
    configurable: true,
    get() { throw new Error('disabled') },
  })
  try {
    assert.equal(getCosmosEndpointProvider('atomone-mainnet'), 'auto')
    assert.equal(
      rewriteCosmosApiUrl('/api/networks/atomone-mainnet/blocks'),
      '/api/networks/atomone-mainnet/blocks',
    )
  } finally {
    if (originalWindow === undefined) delete globalThis.window
    else globalThis.window = originalWindow
  }
})

test('endpoint popup exposes Auto, paired manual mode, mixed routing, and bounded diagnostics', () => {
  const component = read('../src/components/CosmosRpcStatus.jsx')
  const hook = read('../src/hooks/useCosmosResource.js')
  const service = read('../src/services/api.js')
  const styles = read('../src/styles/cosmos-endpoint-mode.css')

  assert.match(component, /<strong>Endpoint mode<\/strong>/)
  assert.match(component, /<strong>Auto<\/strong>/)
  assert.match(component, /Pin this RPC \+ API pair/)
  assert.match(component, /Manual pair · no cross-provider fallback/)
  assert.match(component, /Mixed providers · selected independently by current health and latency/)
  assert.match(component, /Manual mode does not silently switch to another provider/)
  assert.match(component, /window\.setInterval\(load, 30000\)/)
  assert.match(component, /if \(document\.hidden\) return/)
  assert.match(component, /endpoint-status/)
  assert.match(hook, /rewriteCosmosApiUrl\(url\)/)
  assert.match(hook, /subscribeCosmosEndpointProvider/)
  assert.match(service, /rewriteCosmosApiUrl\(`\$\{API_ROOT\}\$\{path\}`\)/)
  assert.match(styles, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
})
