import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
const page = fs.readFileSync(new URL('../src/pages/CosmosValidatorDetail.jsx', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const list = fs.readFileSync(new URL('../src/pages/CosmosValidators.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
test('Cosmos validator detail route and independent list identity link are present', () => {
  assert.match(app, /CosmosValidatorDetail network=\{network\} operatorAddress=\{cosmosMatch\[3\]\}/)
  assert.match(list, /cosmos-validator-identity-link[^>]+validators\/\$\{encodeURIComponent/)
  assert.match(list, /<button className=\{`validator-favorite[\s\S]+onClick=\{\(\) => toggleFavorite/)
})
test('detail presents validator-only identity, metrics, signing, slashing and parameters', () => {
  for (const text of ['Voting Power', 'Stake Share', '≈24h Change', 'Commission', 'Recent finalized participation', 'Protocol slashing window', 'Validator Parameters', 'Consensus Identity', 'Consensus Public Key']) assert.match(page, new RegExp(text))
  assert.match(page, /Recent 50-block canonical signing panel/)
  assert.match(page, /aria-label=\{`Block #\$\{p.height\} · \$\{label\(p.status\)\}/)
  assert.match(page, /CopyButton value=\{value\}/)
  for (const forbidden of ['Delegate', 'Undelegate', 'Withdraw rewards', 'wallet connection']) assert.doesNotMatch(page, new RegExp(forbidden, 'i'))
  assert.match(page, /theme-compatible/)
  assert.match(css, /var\(--color-card\)/)
})
