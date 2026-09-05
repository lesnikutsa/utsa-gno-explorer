import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const search = fs.readFileSync(new URL('../src/components/NetworkBlockSearch.jsx', import.meta.url), 'utf8')

test('Cosmos shared search routes account addresses with the configured network prefix', () => {
  assert.match(search, /const accountPrefix = `\$\{network\.addressPrefixes\.account\}1`/)
  assert.match(search, /value\.startsWith\(accountPrefix\)/)
  assert.match(search, /`\/networks\/\$\{networkId\}\/accounts\/\$\{encodeURIComponent\(value\)\}`/)
  assert.match(search, /account address, or validator/)
  assert.doesNotMatch(search, /atone1/)
})

test('account addresses do not trigger validator autocomplete before submit', () => {
  assert.match(search, /TRANSACTION_HASH\.test\(value\) \|\| value\.startsWith\(accountPrefix\) \|\| value\.length > 128/)
  assert.match(search, /blocks, transactions, account addresses, or validators/)
})
