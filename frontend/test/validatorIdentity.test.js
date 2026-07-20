import assert from 'node:assert/strict'
import test from 'node:test'

import {
  compareValidatorIdentity,
  hasValidatorMoniker,
  matchesValidatorSearch,
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

test('empty and whitespace-only searches match every validator', () => {
  assert.equal(matchesValidatorSearch(validator('g1address', 'UTSA'), ''), true)
  assert.equal(matchesValidatorSearch(validator('g1address', 'UTSA'), ' \t '), true)
})

test('moniker search supports exact, partial, and case-insensitive matches', () => {
  assert.equal(matchesValidatorSearch(validator('g1address', 'UTSA'), 'UTSA'), true)
  assert.equal(matchesValidatorSearch(validator('g1address', 'gfantom-1'), 'fantom'), true)
  assert.equal(matchesValidatorSearch(validator('g1address', 'UTSA'), 'utsa'), true)
})

test('signing address search supports exact, prefix, and suffix matches', () => {
  const row = validator('g15sysd4example2vwpves', 'Node')
  assert.equal(matchesValidatorSearch(row, row.address), true)
  assert.equal(matchesValidatorSearch(row, 'g15sysd4'), true)
  assert.equal(matchesValidatorSearch(row, '2vwpves'), true)
})

test('unrelated searches and unusable monikers do not match', () => {
  assert.equal(matchesValidatorSearch(validator('g1address', 'UTSA'), 'unknown'), false)
  assert.equal(matchesValidatorSearch(validator('g1address', null), 'utsa'), false)
  assert.equal(matchesValidatorSearch(validator('g1address', '   '), ' '), true)
  assert.equal(matchesValidatorSearch(validator('g1address', '   '), 'utsa'), false)
  assert.equal(matchesValidatorSearch({ moniker: null }, 'utsa'), false)
})

test('duplicate monikers can both match without mutation', () => {
  const rows = [Object.freeze(validator('g1a', 'Node')), Object.freeze(validator('g1b', 'Node'))]
  assert.deepEqual(rows.filter((row) => matchesValidatorSearch(row, 'node')), rows)
  assert.deepEqual(rows, [{ address: 'g1a', moniker: 'Node' }, { address: 'g1b', moniker: 'Node' }])
})
