import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
const page = fs.readFileSync(new URL('../src/pages/CosmosValidatorDetail.jsx', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
const list = fs.readFileSync(new URL('../src/pages/CosmosValidators.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
test('Cosmos validator detail route and independent list identity link are present', () => {
  assert.match(app, /CosmosValidatorDetail network=\{network\} operatorAddress=\{cosmosMatch\[3\]\}/)
  assert.match(list, /CosmosValidatorIdentity[^>]+href=\{`\/networks\/\$\{network.id\}\/validators\/\$\{encodeURIComponent/)
  assert.match(list, /<button className=\{`validator-favorite[\s\S]+onClick=\{\(\) => toggleFavorite/)
})
test('detail presents validator-only identity, metrics, signing, slashing and parameters', () => {
  for (const text of ['Account Address', 'Hex Address', 'Bonded', 'Jailed', 'Identity', 'Voting Power', 'Stake Share', '≈24h Change', 'Commission', 'Recent finalized participation', 'Protocol slashing window', 'Validator Parameters', 'Consensus Identity', 'Consensus Public Key']) assert.match(page, new RegExp(text))
  assert.match(page, /Recent 50-block canonical signing panel/)
  assert.match(page, /aria-label=\{`Block #\$\{p.height\} · \$\{label\(p.status\)\}/)
  assert.match(page, /CopyButton value=\{value\}/)
  for (const forbidden of ['Delegate', 'Undelegate', 'Withdraw rewards', 'wallet connection']) assert.doesNotMatch(page, new RegExp(forbidden, 'i'))
  assert.match(page, /theme-compatible/)
  assert.match(css, /var\(--color-card\)/)
})

test('validator identities link consistently across Cosmos explorer surfaces', () => {
  const files = ['CosmosOverview.jsx', 'CosmosBlocks.jsx', 'CosmosBlockDetail.jsx']
  for (const file of files) {
    const source = fs.readFileSync(new URL(`../src/pages/${file}`, import.meta.url), 'utf8')
    assert.match(source, /CosmosValidatorIdentity[\s\S]*?href=\{/)
    assert.match(source, /\/networks\/\$\{network.id\}\/validators/)
  }
})

test('shared validator identity owns one semantic color contract', () => {
  assert.match(css, /\.cosmos-validator strong\s*\{\s*color:\s*var\(--color-text-bright\)/)
  assert.match(css, /\.cosmos-validator > span\s*\{\s*color:\s*var\(--color-text-secondary\)/)
  assert.match(css, /\.cosmos-validator-identity-link:hover \.cosmos-validator strong,[\s\S]*?focus-visible \.cosmos-validator strong\s*\{\s*color:\s*var\(--color-accent\)/)
  assert.match(css, /\.cosmos-validator-identity-link:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--color-accent\)/)
  assert.doesNotMatch(css, /\.cosmos-blocks \.cosmos-validator strong\s*\{[^}]*color:/)
  assert.doesNotMatch(css, /\.cosmos-validator-hero__main \.cosmos-validator strong\s*\{[^}]*color:/)
})
