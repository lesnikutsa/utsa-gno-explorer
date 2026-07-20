import assert from 'node:assert/strict'
import test from 'node:test'

import {
  compareValidatorIdentity,
  hasValidatorMoniker,
} from '../src/utils/validatorIdentity.js'

const validator = (address, moniker = null) => ({ address, moniker })

test('moniker availability preserves matched content and rejects unavailable values', () => {
  assert.equal(hasValidatorMoniker(validator('g1address', '  Alice  Node ')), true)
  for (const moniker of [null, '', ' \t ']) {
    const row = validator('g1address', moniker)
    assert.equal(hasValidatorMoniker(row), false)
  }
})

test('matched validators sort by moniker case-insensitively', () => {
  assert.ok(compareValidatorIdentity(validator('g1z', 'alpha'), validator('g1a', 'Beta')) < 0)
  assert.ok(compareValidatorIdentity(validator('g1z', 'ALPHA'), validator('g1a', 'alpha')) > 0)
})

test('duplicate monikers use signing address as a deterministic tie-breaker', () => {
  assert.ok(compareValidatorIdentity(validator('g1a', 'Node'), validator('g1b', 'node')) < 0)
})

test('matched validators precede unmatched validators in ascending order', () => {
  assert.ok(compareValidatorIdentity(validator('g1z', 'Node'), validator('g1a')) < 0)
})

test('unmatched validators sort by signing address', () => {
  assert.ok(compareValidatorIdentity(validator('g1a'), validator('g1b', '')) < 0)
})

test('reversing the final comparison provides deterministic descending order', () => {
  const rows = [validator('g1b'), validator('g1a', 'Beta'), validator('g1z', 'alpha')]
  const ascending = [...rows].sort(compareValidatorIdentity)
  const descending = [...rows].sort((left, right) => -compareValidatorIdentity(left, right))
  assert.deepEqual(descending, [...ascending].reverse())
})

test('identity helpers do not mutate validator objects', () => {
  const left = Object.freeze(validator('g1b', 'Beta'))
  const right = Object.freeze(validator('g1a', 'alpha'))
  compareValidatorIdentity(left, right)
  hasValidatorMoniker(left)
  assert.deepEqual(left, { address: 'g1b', moniker: 'Beta' })
})
