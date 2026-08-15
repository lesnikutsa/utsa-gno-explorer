import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeBlockTimeIntervals } from '../src/utils/blockTime.js'

test('block time intervals are copied, bounded, and keep chronological order', () => {
  const source = [4.2, 3.1, 3.8, 3.4, 4, 3.7, 3.6, 3.9, 3.5, 9]
  assert.deepEqual(normalizeBlockTimeIntervals(source), source.slice(0, 9))
  assert.deepEqual(source, [4.2, 3.1, 3.8, 3.4, 4, 3.7, 3.6, 3.9, 3.5, 9])
})

test('block time intervals fail closed for invalid input and values', () => {
  assert.deepEqual(normalizeBlockTimeIntervals(null), [])
  assert.deepEqual(normalizeBlockTimeIntervals('3.5'), [])
  assert.deepEqual(
    normalizeBlockTimeIntervals([3, '4', null, NaN, Infinity, 0, -1, 2]),
    [3, 2],
  )
})
