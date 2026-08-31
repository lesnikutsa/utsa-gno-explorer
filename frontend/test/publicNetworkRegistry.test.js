import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizePublicCosmosNetwork } from '../src/utils/publicNetworkRegistry.js'

const atomone = {
  id: 'atomone-mainnet', family: 'cosmos', chain_id: 'atomone-1',
  display_name: 'AtomOne', network_name: 'Mainnet',
  logo_url: 'https://raw.githubusercontent.com/lesnikutsa/explorer/master/public/logos/Atomone.png',
  assets: [{ base: 'uatone', display: 'atone', symbol: 'ATONE', exponent: 6 }],
  address_prefixes: { account: 'atone', validator_operator: 'atonevaloper', validator_consensus: 'atonevalcons' },
  capabilities: ['overview', 'blocks', 'network-parameters'],
}

test('backend public metadata becomes selector presentation without endpoint fields', () => {
  const network = normalizePublicCosmosNetwork(atomone)
  assert.equal(network.id, 'atomone-mainnet')
  assert.equal(network.expectedChainId, 'atomone-1')
  assert.equal(network.presentation.networkIconSrc, atomone.logo_url)
  assert.deepEqual(network.capabilities, atomone.capabilities)
  assert.equal('rpc_endpoints' in network, false)
  assert.equal('rest_endpoints' in network, false)
})

test('invalid or non-HTTPS public metadata fails closed', () => {
  assert.equal(normalizePublicCosmosNetwork({ ...atomone, logo_url: 'http://example.test/logo.png' }), null)
  assert.equal(normalizePublicCosmosNetwork({ ...atomone, assets: [] }), null)
})
