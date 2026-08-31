import assert from 'node:assert/strict'
import test from 'node:test'

import { countdownParts, formatAverageBlockTime, formatEstimatedArrival } from '../src/utils/futureBlock.js'

test('countdown splits a distant ETA into bounded calendar units', () => {
  const now = Date.parse('2026-08-31T00:00:00Z')
  const estimatedAt = new Date(now + 5_572_341_000).toISOString()
  assert.deepEqual(countdownParts(estimatedAt, now), {
    days: 64, hours: 11, minutes: 52, seconds: 21, totalSeconds: 5_572_341,
  })
})

test('countdown stops at zero after the ETA and rejects invalid dates', () => {
  const now = Date.parse('2026-08-31T00:00:00Z')
  assert.deepEqual(countdownParts('2026-08-30T23:59:59Z', now), {
    days: 0, hours: 0, minutes: 0, seconds: 0, totalSeconds: 0,
  })
  assert.equal(countdownParts('invalid', now), null)
})

test('future block values use stable English formatting', () => {
  assert.equal(formatAverageBlockTime(5.795), '5.795 s')
  assert.equal(formatAverageBlockTime(Number.NaN), '—')
  assert.equal(formatEstimatedArrival('2026-11-04T07:24:03.123456Z'), '04 Nov 2026 · 07:24:03 UTC')
  assert.equal(formatEstimatedArrival('invalid'), '—')
})
