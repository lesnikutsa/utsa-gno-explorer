import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chooseValidatorResult,
  findUniqueExactValidatorMatch,
  isExactBase64BlockHash,
  isExactHexBlockHash,
  isPositiveBlockHeight,
  shouldSearchValidators,
} from '../src/utils/globalSearch.js'

const first = { address: 'g1signing-one', operator_address: 'g1operator-one', moniker: 'UTSA' }
const second = { address: 'g1signing-two', operator_address: 'g1operator-two', moniker: 'UTSA' }

test('recognizes only positive block heights', () => {
  assert.equal(isPositiveBlockHeight(' 42 '), true)
  for (const value of ['0', '-1', '1.5', 'utsa']) assert.equal(isPositiveBlockHeight(value), false)
})

test('recognizes exact hexadecimal hashes with optional prefix', () => {
  assert.equal(isExactHexBlockHash('a'.repeat(64)), true)
  assert.equal(isExactHexBlockHash(`0x${'A'.repeat(64)}`), true)
  assert.equal(isExactHexBlockHash('a'.repeat(63)), false)
})

test('recognizes exact Base64 hashes', () => {
  assert.equal(isExactBase64BlockHash(`${'A'.repeat(43)}=`), true)
  assert.equal(isExactBase64BlockHash('not-a-hash'), false)
})

test('classifies monikers and signing or operator addresses as validator searches', () => {
  for (const value of ['utsa', 'g1signing', 'g1operator']) assert.equal(shouldSearchValidators(value), true)
  assert.equal(shouldSearchValidators('x'), false)
  assert.equal(shouldSearchValidators('12'), false)
  assert.equal(shouldSearchValidators('f'.repeat(64)), false)
})

test('exact signing address has priority and comparisons are case-insensitive', () => {
  assert.equal(findUniqueExactValidatorMatch(' G1SIGNING-ONE ', [first, second]), first)
})

test('exact operator address resolves to the signing identity', () => {
  assert.equal(findUniqueExactValidatorMatch('G1OPERATOR-TWO', [first, second]), second)
})

test('unique exact moniker resolves but duplicate exact monikers remain ambiguous', () => {
  assert.equal(findUniqueExactValidatorMatch('utsa', [first]), first)
  assert.equal(findUniqueExactValidatorMatch('utsa', [first, second]), null)
})

test('one result is selectable while multiple partial results are not arbitrary', () => {
  assert.equal(chooseValidatorResult('uts', [first]), first)
  assert.equal(chooseValidatorResult('uts', [first, second]), null)
  assert.equal(chooseValidatorResult('uts', [first, second], 1), second)
})
