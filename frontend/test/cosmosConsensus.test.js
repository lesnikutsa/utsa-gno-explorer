import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosConsensus.jsx')
const styles = read('../src/styles/cosmos-consensus.css')
const app = read('../src/App.jsx')
const navigation = read('../src/config/navigation.js')
const publicRegistry = read('../src/utils/publicNetworkRegistry.js')

test('Cosmos consensus is a live 1 second route and Cosmos-only capability', () => {
  assert.match(page, /useCosmosResource\(`\/api\/networks\/\$\{network\.id\}\/consensus`, 1000\)/)
  assert.match(app, /blocks\|transactions\|validators\|governance\|consensus/)
  assert.match(app, /<CosmosConsensus network=\{network\}/)
  assert.match(navigation, /label: 'Consensus'.+href: '\/consensus'.+NetworkCapability\.CONSENSUS/)
  assert.match(publicRegistry, /value\.capabilities\.includes\('validators'\).+!value\.capabilities\.includes\('consensus'\)/s)
})

test('Consensus page exposes quorum, hash diagnostics, validator vote phases and RPC views', () => {
  for (const text of ['Live Consensus', 'Prevote', 'Precommit', 'Proposal hash', 'Locked hash', 'Valid hash', 'RPC views']) {
    assert.match(page, new RegExp(text))
  }
  assert.match(page, /validator\.prevote/)
  assert.match(page, /validator\.precommit/)
  assert.match(page, /competing_precommit_hashes/)
  assert.match(page, /rpc_diverged/)
  assert.match(styles, /left:\s*66\.6667%/)
})

test('Consensus avoids native white tooltips and stays responsive', () => {
  assert.doesNotMatch(page, /title=/)
  assert.doesNotMatch(page, /data-tip=/)
  assert.match(styles, /@media \(max-width: 760px\)/)
  assert.match(styles, /grid-template-columns:\s*repeat\(4/)
  assert.match(styles, /\.cosmos-consensus__vote-indicator\.is-divergent/)
})
