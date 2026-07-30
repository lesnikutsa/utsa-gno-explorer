import assert from 'node:assert/strict'
import test from 'node:test'
import { endpointHostname, endpointStatus, hoverPopoverState, normalizeRpcPool, poolSummary, togglePopoverState } from '../src/utils/rpcPool.js'

const pool = (total, available) => ({ total, available, last_checked_at: null, endpoints: [] })
const endpoint = (index, selected = false) => ({
  url: `https://rpc-${index}.example`, selected, state: 'healthy', latency_ms: 10 + index, lag: 0, last_checked_at: null,
})

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
  assert.equal(normalizeRpcPool({ total: 2, available: 1, endpoints: [endpoint(0)] }), null)
  assert.equal(normalizeRpcPool({ total: 1, available: 1, endpoints: [{ ...endpoint(0), selected: 'yes' }] }), null)
  assert.equal(normalizeRpcPool({ total: 1, available: 1, endpoints: [{ ...endpoint(0), latency_ms: 30001 }] }), null)
  assert.equal(normalizeRpcPool({ total: 1, available: 1, endpoints: [{ ...endpoint(0), lag: -1 }] }), null)
  assert.equal(normalizeRpcPool({ total: 2, available: 2, endpoints: [endpoint(0, true), endpoint(1, true)] }), null)
  const valid = { total: 5, available: 5, last_checked_at: '2026-07-30T13:45:00Z', endpoints: Array.from({ length: 5 }, (_, index) => endpoint(index, index === 0)) }
  assert.equal(normalizeRpcPool(valid), valid)
})

test('touch pointer enter does not consume the first tap', () => {
  let open = hoverPopoverState(false, 'touch')
  assert.equal(open, false)
  open = togglePopoverState(open)
  assert.equal(open, true)
  open = togglePopoverState(open)
  assert.equal(open, false)
  assert.equal(hoverPopoverState(false, 'mouse'), true)
})
