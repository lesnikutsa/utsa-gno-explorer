import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')

test('unbonding summary shows the same optional native-token USD value as the other headline cards', () => {
  assert.match(page, /const unbondingCoin = account\.bond_denom && unbondingAmount != null \? \{ denom: account\.bond_denom, amount: unbondingAmount \} : null/)
  assert.match(page, /const unbondingUsd = unbondingAvailable \? approximateUsd\(unbondingCoin, network, market\.data\) : null/)
  assert.match(page, /<SummaryCard label="Unbonding" usd=\{unbondingUsd\}/)
})
