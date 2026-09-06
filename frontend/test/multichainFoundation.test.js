import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { adjacentOptionIndex } from '../src/utils/networkSelector.js'
import { networkIdForPath } from '../src/utils/networkSelection.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const registry = read('../src/config/networkRegistry.js')
const navigation = read('../src/config/navigation.js')
const sidebar = read('../src/components/Sidebar.jsx')
const context = read('../src/context/SelectedNetworkContext.jsx')
const app = read('../src/App.jsx')
const identity = read('../src/hooks/useChainIdentity.js')

test('static registry contains only Pearl while Cosmos networks come from public metadata', () => {
  const ids = [...registry.matchAll(/\bid: '([^']+)'/g)].map((match) => match[1])
  assert.deepEqual(ids, ['gno-pearl'])
  assert.equal(new Set(ids).size, ids.length)
  assert.match(registry, /family: NetworkFamily\.GNO/)
  assert.match(registry, /expectedChainId: 'pearl-1'/)
  assert.doesNotMatch(registry, /atomone|uatone|uphoton/i)
  assert.match(context, /fetch\('\/api\/networks'/)
  assert.match(context, /normalizePublicCosmosNetwork/)
  assert.doesNotMatch(registry, /(?:rpc|rest)(?:Url|Endpoint)|VITE_(?:RPC|REST)/i)
})

test('Pearl enables every existing feature while future capabilities stay disabled', () => {
  for (const capability of ['OVERVIEW', 'BLOCKS', 'TRANSACTIONS', 'REALMS', 'TOKENS', 'VALIDATORS', 'GOVERNANCE', 'NETWORK_DISTRIBUTION', 'VALIDATOR_SIGNING_HISTORY', 'TELEGRAM_MONITORING']) {
    assert.match(registry, new RegExp(`NetworkCapability\\.${capability},`))
  }
  const enabledCapabilities = registry.slice(registry.indexOf('capabilities: Object.freeze(['), registry.indexOf(']),', registry.indexOf('capabilities: Object.freeze([')))
  for (const capability of ['CONSENSUS', 'NETWORK_PARAMETERS', 'CONSENSUS_DIAGNOSTICS']) {
    assert.match(registry, new RegExp(`${capability}:`))
    assert.doesNotMatch(enabledCapabilities, new RegExp(`NetworkCapability\\.${capability}`))
  }
})

test('navigation order stays declarative and is filtered by capability', () => {
  const items = [...navigation.matchAll(/label: '([^']+)'[^\n]+href: '([^']+)'[^\n]+capability: NetworkCapability\.(\w+)/g)]
    .map(([, label, href, capability]) => ({ label, href, capability }))
  assert.deepEqual(items, [
    { label: 'Overview', href: '/', capability: 'OVERVIEW' },
    { label: 'Blocks', href: '/blocks', capability: 'BLOCKS' },
    { label: 'Transactions', href: '/transactions', capability: 'TRANSACTIONS' },
    { label: 'Realms', href: '/realms', capability: 'REALMS' },
    { label: 'Tokens', href: '/tokens', capability: 'TOKENS' },
    { label: 'Validators', href: '/validators', capability: 'VALIDATORS' },
    { label: 'Governance', href: '/governance', capability: 'GOVERNANCE' },
    { label: 'Consensus', href: '/consensus', capability: 'CONSENSUS' },
  ])
  assert.match(sidebar, /navigationItems\.filter\(\(\{ capability \}\) => hasNetworkCapability\(selectedNetwork, capability\)\)/)
})

test('selector is registry-driven, keyboard accessible, focused, and selection updates the route', () => {
  assert.match(sidebar, /supportedNetworks\.map\(\(network, index\) =>/)
  assert.match(sidebar, /aria-haspopup="listbox"/)
  assert.match(sidebar, /aria-expanded=\{networkMenuOpen\}/)
  assert.match(sidebar, /role="option" aria-selected=\{selected\}/)
  assert.match(sidebar, /role="listbox" aria-label="Supported networks" onKeyDown=\{handleNetworkOptionsKeyDown\}/)
  assert.match(sidebar, /event\.key === 'Escape'/)
  assert.match(sidebar, /event\.key === 'ArrowDown' \|\| event\.key === 'ArrowUp'/)
  assert.match(sidebar, /networkOptions\.current\[focusedNetworkIndex\]\?\.focus\(\)/)
  assert.match(sidebar, /networkSelectorTrigger\.current\?\.focus\(\)/)
  assert.match(sidebar, /tabIndex=\{focusedNetworkIndex === index \? 0 : -1\}/)
  assert.match(sidebar, /event\.key === 'Enter' \|\| event\.key === ' '/)
  const selectionHandler = sidebar.slice(sidebar.indexOf('const handleNetworkSelection'), sidebar.indexOf('const isActive'))
  assert.match(selectionHandler, /selectNetwork\(networkId\)/)
  assert.match(selectionHandler, /navigateInternal\(networkId === 'gno-pearl' \? '\/' : `\/networks\/\$\{networkId\}`\)/)
  assert.match(context, /if \(getNetworkById\(networkId\)\) setSelectedNetworkId\(networkId\)/)
  assert.doesNotMatch(context, /localStorage/)
})

test('URL is authoritative for direct links and Gno/AtomOne back-forward transitions', () => {
  const lookup = (id) => id === 'atomone-mainnet' ? { family: 'cosmos' } : id === 'gno-pearl' ? { family: 'gno' } : null
  const selected = (path) => networkIdForPath(path, lookup, 'gno-pearl')
  assert.equal(selected('/'), 'gno-pearl')
  assert.equal(selected('/validators/example'), 'gno-pearl')
  assert.equal(selected('/networks/atomone-mainnet'), 'atomone-mainnet')
  assert.equal(selected('/networks/atomone-mainnet/blocks/42'), 'atomone-mainnet')
  assert.equal(selected('/networks/unknown'), 'gno-pearl')
  assert.match(context, /window\.addEventListener\('popstate', synchronizeWithUrl\)/)
  assert.match(context, /window\.addEventListener\(INTERNAL_NAVIGATION_EVENT, synchronizeWithUrl\)/)
  assert.match(context, /networkIdForPath\(window\.location\.pathname, getNetworkById, DEFAULT_NETWORK_ID\)/)
})

test('selector focus wraps predictably for any registry size', () => {
  assert.equal(adjacentOptionIndex(0, 3, 'next'), 1)
  assert.equal(adjacentOptionIndex(2, 3, 'next'), 0)
  assert.equal(adjacentOptionIndex(2, 3, 'previous'), 1)
  assert.equal(adjacentOptionIndex(0, 3, 'previous'), 2)
  assert.equal(adjacentOptionIndex(-1, 3, 'next'), 0)
  assert.equal(adjacentOptionIndex(-1, 3, 'previous'), 2)
  assert.equal(adjacentOptionIndex(0, 0, 'next'), -1)
})

test('selector closes for outside interaction, navigation, and mobile close with listener cleanup', () => {
  assert.match(sidebar, /document\.addEventListener\('pointerdown', handleOutsidePointerDown\)/)
  assert.match(sidebar, /return \(\) => document\.removeEventListener\('pointerdown', handleOutsidePointerDown\)/)
  assert.match(sidebar, /if \(!networkSelector\.current\?\.contains\(event\.target\)\) setNetworkMenuOpen\(false\)/)
  assert.match(sidebar, /if \(previousSidebarOpen\.current && !open\) setNetworkMenuOpen\(false\)/)
  assert.match(sidebar, /const handleNavigation = \(event, href\) => \{\s*closeNetworkMenu\(\{ restoreFocus: false \}\)/)
  assert.match(sidebar, /const handleSidebarClose = \(\) => \{\s*closeNetworkMenu\(\{ restoreFocus: false \}\)\s*onClose\(\)/)
  assert.match(sidebar, /onClick=\{handleSidebarClose\}/)
  assert.match(sidebar, /setNetworkIconFailed\(false\)\s*\}, \[selectedNetwork\.id, networkProfile\.networkIconSrc\]\)/)
})

test('all legacy Pearl list and detail routes remain unprefixed', () => {
  for (const route of ["path === '/blocks'", "path === '/transactions'", "path === '/realms'", "path === '/tokens'", "path === '/validators'", "path === '/governance'", "path.match(/^\\/governance\\/", "path.match(/^\\/validators\\/", "path.match(/^\\/accounts\\/", "path.match(/^\\/blocks\\/", "path.startsWith('/blocks/')"]) {
    assert.ok(app.includes(route), `missing legacy route contract: ${route}`)
  }
  assert.match(app, /return <OverviewPage \/>/)
})

test('live chain identity remains health-driven and introduces no new timer', () => {
  assert.match(identity, /const health = await getHealth\(\)/)
  assert.match(identity, /CHAIN_IDENTITY_POLL_MS = 30_000/)
  assert.equal((identity.match(/setTimeout/g) ?? []).length, 1)
  for (const source of [registry, navigation, sidebar, context]) assert.doesNotMatch(source, /set(?:Timeout|Interval)/)
  assert.doesNotMatch(registry, /getHealth|chain_id/)
  assert.doesNotMatch(identity, /networkRegistry|expectedChainId/)
})
