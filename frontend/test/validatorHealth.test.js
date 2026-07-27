import assert from 'node:assert/strict'
import test from 'node:test'

import { getMissedBlocks, getValidatorHealth } from '../src/utils/validatorHealth.js'

const uptime = (active_blocks, nil_blocks, absent_blocks = 0, invalid_blocks = 0, unknown_blocks = 0) => ({
  active_blocks,
  signed_blocks: active_blocks - nil_blocks - absent_blocks - invalid_blocks - unknown_blocks,
  nil_blocks,
  absent_blocks,
  invalid_blocks,
  unknown_blocks,
})

test('validator health uses missed-rate boundaries over the active denominator', () => {
  const cases = [
    [uptime(1000, 0), 'Healthy'],
    [uptime(1000, 3, 3, 3), 'Healthy'],
    [uptime(1000, 4, 3, 3), 'Degraded'],
    [uptime(1000, 20, 20, 9), 'Degraded'],
    [uptime(1000, 20, 20, 10), 'Critical'],
    [uptime(1000, 333, 333, 333), 'Critical'],
    [uptime(1000, 334, 333, 333), 'No signatures'],
    [uptime(200, 1), 'Healthy'],
    [uptime(200, 1, 1), 'Degraded'],
  ]

  for (const [value, expected] of cases) assert.equal(getValidatorHealth(value).label, expected)
})

test('unknown blocks remain separate and special no-data semantics are preserved', () => {
  const unknown = uptime(1000, 0, 0, 0, 1)
  assert.equal(getMissedBlocks(unknown), 0)
  assert.equal(getValidatorHealth(unknown).label, 'Unknown')
  assert.equal(getValidatorHealth(uptime(0, 0)).label, 'No data')
})
