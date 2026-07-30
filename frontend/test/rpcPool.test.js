import assert from 'node:assert/strict'
import test from 'node:test'
import { endpointHostname, endpointStatus, normalizeRpcPool, poolSummary } from '../src/utils/rpcPool.js'

const pool = (total, available) => ({ total, available, last_checked_at: null, endpoints: [] })

test('pool summary tones cover availability levels', () => {
  assert.deepEqual(poolSummary(pool(5, 5)), { tone: 'success', label: '5/5 available' })
  assert.equal(poolSummary(pool(5, 3)).label, 'Reduced redundancy')
  assert.equal(poolSummary(pool(5, 1)).label, 'At risk')
  assert.equal(poolSummary(pool(5, 0)).label, 'Unavailable')
  assert.equal(poolSummary(pool(0, 0)).label, 'RPC unavailable')
})

test('endpoint presentation is safe and hides healthy lag', () => {
  assert.equal(endpointHostname('https://rpc.example.test/path'), 'rpc.example.test')
  assert.equal(endpointStatus({ state: 'healthy', lag: 1 }), 'Healthy')
  assert.equal(endpointStatus({ state: 'stale', lag: 18 }), '18 blocks behind')
  assert.equal(endpointStatus({ state: 'wrong_chain' }), 'Wrong network')
})

test('malformed pools are rejected for rolling deployment fallback', () => {
  assert.equal(normalizeRpcPool(null), null)
  assert.equal(normalizeRpcPool({ total: 1, available: 2, endpoints: [] }), null)
  assert.equal(normalizeRpcPool({ total: 1, available: 1, endpoints: [{ url: 'https://rpc.example', state: 'raw-error' }] }), null)
})
