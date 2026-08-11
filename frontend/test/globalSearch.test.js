import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chooseValidatorResult,
  findUniqueExactValidatorMatch,
  isExactBase64BlockHash,
  isExactHexBlockHash,
  isPositiveBlockHeight,
  isValidAccountAddress,
  resolveAccountAddressDestination,
  shouldSearchValidators,
} from '../src/utils/globalSearch.js'

const validAccount = 'g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75'

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

test('strictly validates Gno account addresses', () => {
  assert.equal(isValidAccountAddress(validAccount), true)
  assert.equal(isValidAccountAddress(` \t${validAccount}\n`), true)
  assert.equal(isValidAccountAddress(`${validAccount.slice(0, -1)}q`), false)
  assert.equal(isValidAccountAddress(validAccount.toUpperCase()), false)
  assert.equal(isValidAccountAddress(`G${validAccount.slice(1)}`), false)
  assert.equal(isValidAccountAddress(`x${validAccount.slice(1)}`), false)
  assert.equal(isValidAccountAddress(`${validAccount.slice(0, -1)}i`), false)
  assert.equal(isValidAccountAddress('g1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq0lj0qc'), false)
  assert.equal(isValidAccountAddress(null), false)
})

test('complete accounts skip validator autocomplete while partial addresses do not', () => {
  assert.equal(shouldSearchValidators(validAccount), false)
  assert.equal(shouldSearchValidators('g1abc'), true)
})

test('account destinations only give exact validator addresses precedence', () => {
  const signing = { address: validAccount, operator_address: 'g1operator', moniker: 'signer' }
  assert.equal(resolveAccountAddressDestination(validAccount, []), `/accounts/${validAccount}`)
  assert.equal(resolveAccountAddressDestination(validAccount, [signing]), `/validators/${validAccount}`)

  const operator = { address: 'g1signing-identity', operator_address: validAccount, moniker: 'operator' }
  assert.equal(resolveAccountAddressDestination(validAccount, [operator]), '/validators/g1signing-identity')
  assert.equal(resolveAccountAddressDestination(validAccount, [
    { address: 'g1partial', operator_address: 'g1other', moniker: validAccount },
  ]), `/accounts/${validAccount}`)
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
