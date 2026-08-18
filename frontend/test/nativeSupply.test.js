import assert from 'node:assert/strict'
import test from 'node:test'

import { formatNativeSupply } from '../src/utils/tokenSupply.js'

test('rounds huge native supply exactly with narrow no-break grouping', () => {
  assert.deepEqual(formatNativeSupply('3000000000209.931689'), {
    display: '≈ 3\u202f000\u202f000\u202f000\u202f210',
    exact: '3\u202f000\u202f000\u202f000\u202f209.931689',
  })
})

test('keeps integer native supply exact without approximation', () => {
  assert.deepEqual(formatNativeSupply('1333000000'), {
    display: '1\u202f333\u202f000\u202f000',
    exact: '1\u202f333\u202f000\u202f000',
  })
})

test('rounds fractions around the half boundary without floating point', () => {
  assert.equal(formatNativeSupply('100.499999').display, '≈ 100')
  assert.equal(formatNativeSupply('100.500000').display, '≈ 101')
  assert.equal(formatNativeSupply('100.000000').display, '100')
})

test('returns recoverable exact native supply for secondary display', () => {
  assert.equal(formatNativeSupply('999999999999999999.000001').exact, '999\u202f999\u202f999\u202f999\u202f999\u202f999.000001')
})
