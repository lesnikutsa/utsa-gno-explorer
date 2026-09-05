import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')

test('account delegation and unbonding validator rows reuse the shared validator identity with logos', () => {
  assert.match(page, /import \{ CosmosValidatorIdentity \} from '\.\.\/components\/CosmosValidatorIdentity'/)
  assert.match(page, /imageSrc=\{validator\.avatar_url\}/)
  assert.match(page, /fullAddress/)
  assert.match(page, /href=\{`\/networks\/\$\{network\.id\}\/validators\/\$\{encodeURIComponent\(validator\.operator_address\)\}`\}/)
  assert.match(page, /<ValidatorName network=\{network\} validator=\{row\.validator\} \/>/)
  assert.match(page, /<ValidatorName network=\{network\} validator=\{group\.validator\} \/>/)
})

test('shared account validator identity is wrapped in a grid cell so unbonding aligns with delegations', () => {
  assert.match(page, /function ValidatorName[\s\S]*?return <div className="cosmos-account-validator-cell">[\s\S]*?<CosmosValidatorIdentity/)
})
