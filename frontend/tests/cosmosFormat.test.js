import test from 'node:test'
import assert from 'node:assert/strict'
import { formatBaseAmount, formatMarketPercent, formatRatio, mergeBlockWindow, validateCosmosHeight } from '../src/utils/cosmosFormat.js'

test('formats large base-denom integers without floating point precision loss', () => {
  assert.equal(formatBaseAmount('1234567890123456789012345', 6), '1,234,567,890,123,456,789.012345')
  assert.equal(formatBaseAmount('0', 6), '0')
})

test('distinguishes ratios from market percentages and preserves zero', () => {
  assert.equal(formatRatio('0.1234'), '12.34%')
  assert.equal(formatMarketPercent('12.34'), '12.34%')
  assert.equal(formatMarketPercent('0'), '0%')
})

test('height validation rejects rounding, exponent notation, zero and unsafe integers', () => {
  for (const invalid of ['0', '-1', '1.2', '1e6', '9007199254740992', '']) assert.ok(validateCosmosHeight(invalid).error)
  assert.deepEqual(validateCosmosHeight('9007199254740991'), { height: '9007199254740991' })
})

test('rolling block window deduplicates, sorts and caps at twenty', () => {
  const first = Array.from({ length: 10 }, (_, index) => ({ height: String(100 - index) }))
  const update = [{ height: '102' }, { height: '101' }, { height: '100' }]
  const merged = mergeBlockWindow(first, update)
  assert.deepEqual(merged.slice(0, 4).map(({ height }) => height), ['102', '101', '100', '99'])
  assert.equal(new Set(merged.map(({ height }) => height)).size, merged.length)
  assert.ok(merged.length <= 20)
})

test('a large head jump replaces rather than backfills the rolling window', () => {
  const previous = [{ height: '100' }, { height: '99' }]
  const current = [{ height: '150' }, { height: '149' }]
  assert.deepEqual(mergeBlockWindow(previous, current), current)
})
