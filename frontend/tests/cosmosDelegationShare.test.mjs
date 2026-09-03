import assert from 'node:assert/strict'
import test from 'node:test'

import { formatDelegationShare } from '../src/utils/cosmosFormat.js'

test('formats delegation share percentages with exact decimal arithmetic', () => {
  assert.equal(formatDelegationShare('124387', '1000000'), '12.4387%')
  assert.equal(formatDelegationShare('396', '1000000'), '0.0396%')
  assert.equal(formatDelegationShare('4', '1000000'), '0.0004%')
  assert.equal(formatDelegationShare('1', '10000000000'), '<0.0001%')
  assert.equal(formatDelegationShare('79800000.000000000000000001', '79800000.000000000000000001'), '100%')
})

test('handles zero shares and unavailable denominators safely', () => {
  assert.equal(formatDelegationShare('0', '100'), '0%')
  assert.equal(formatDelegationShare('1', '0'), '—')
  assert.equal(formatDelegationShare('1', null), '—')
  assert.equal(formatDelegationShare('invalid', '100'), '—')
})
