import assert from 'node:assert/strict'
import test from 'node:test'

import { formatTokenSupply } from '../src/utils/tokenSupply.js'

test('formats token supplies without numeric precision loss', () => {
  assert.equal(formatTokenSupply('0'), '0')
  assert.equal(formatTokenSupply('300000000'), '300,000,000')
  assert.equal(formatTokenSupply('102569491.938420'), '102,569,491.93842')
  assert.equal(
    formatTokenSupply('184467440737095516161844674407370955161'),
    '184,467,440,737,095,516,161,844,674,407,370,955,161',
  )
  assert.equal(formatTokenSupply(null), '—')
})
