import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync(new URL('../src/pages/CosmosValidators.jsx', import.meta.url), 'utf8')
test('Cosmos validator list exposes tabs, sorting, search and partial states', () => {
  for (const text of ['active', 'inactive', 'jailed', 'Search validators', 'History unavailable', 'Loading recent signing history…']) assert.match(source, new RegExp(text, 'i'))
  for (const key of ['tokens', 'change_24h', 'commission', 'missed_blocks', 'moniker']) assert.match(source, new RegExp(key))
})
test('Cosmos validator list includes all delta tones and compact strip', () => {
  for (const tone of ['positive', 'negative', 'neutral']) assert.match(source, new RegExp(`is-\\$\\{tone\\}`))
  assert.match(source, /Recent 50-block signing history/)
  assert.match(source, /Liveness unavailable/)
  assert.match(source, /imageSrc=\{validator\.avatar_url\}/)
})
test('Cosmos validators reuse sort arrows, scoped favorites, and risk tones', () => {
  for (const arrow of ['↕', '↑', '↓']) assert.match(source, new RegExp(arrow))
  assert.match(source, /loadValidatorFavorites\(`cosmos:\$\{network\.id\}`\)/)
  assert.match(source, /saveValidatorFavorites\(`cosmos:\$\{network\.id\}`/)
  assert.match(source, /favorites\.has\(right\.operator_address\)/)
  assert.match(source, /cosmosRiskToneFromUsage\(usage\)/)
})
test('signing points render exact block context without another request', () => {
  assert.match(source, /Block #\$\{point\.height\}/)
  assert.match(source, /point\.status/)
  assert.match(source, /title=\{pointTitle\(point\)\}/)
  assert.match(source, /tabIndex="0"/)
  assert.doesNotMatch(source, /fetch\([^)]*point/)
})
