import assert from 'node:assert/strict'
import test from 'node:test'

import { GNOT_TOKENOMICS } from '../src/config/gnotTokenomics.js'

test('official GNOT allocation is centralized and internally exact', () => {
  assert.equal(GNOT_TOKENOMICS.allocations.length, 7)
  assert.equal(GNOT_TOKENOMICS.allocations.reduce((sum, item) => sum + item.amount, 0), 1_333_000_000)
  assert.equal(GNOT_TOKENOMICS.total, 1_333_000_000)
  assert.deepEqual(GNOT_TOKENOMICS.allocations.map((item) => item.percentage),
    ['26.26%', '24.91%', '22.51%', '17.33%', '4.50%', '3.00%', '1.50%'])
  assert.equal(GNOT_TOKENOMICS.sourceUrl, 'https://sale.gno.land/')
})

test('official TGE circulation is configured locally', () => {
  assert.equal(GNOT_TOKENOMICS.circulatingAtTge.amount, 197_320_000)
  assert.equal(GNOT_TOKENOMICS.circulatingAtTge.percentage, '14.8%')
})
