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
  for (const text of ['Contact', 'Minimum Self Delegation', 'Account Address', 'Hex Address', 'Bonded', 'Jailed', 'Identity', 'Voting Power', 'Stake Share', '≈24h Change', 'Commission', 'Recent finalized participation', 'Protocol slashing window', 'Validator Parameters', 'Consensus Identity', 'Consensus Public Key']) assert.match(page, new RegExp(text))
  assert.match(page, /Recent 50-block canonical signing panel/)
  assert.match(page, /aria-label=\{`Block #\$\{p.height\} · \$\{label\(p.status\)\}/)
  assert.match(page, /CopyButton value=\{value\}/)
  for (const forbidden of ['Delegate', 'Undelegate', 'Withdraw rewards', 'wallet connection']) assert.doesNotMatch(page, new RegExp(forbidden, 'i'))
  assert.match(page, /theme-compatible/)
  assert.match(css, /var\(--color-card\)/)
  assert.match(page, /Past #\{oldestPoint\.height\.toLocaleString\(\)\}/)
  assert.match(page, /Latest finalized #\{newestPoint\.height\.toLocaleString\(\)\}/)
  assert.match(css, /\.cosmos-validator-signing__monitor\s*\{[^}]*margin:\s*0 auto/)
  assert.match(css, /\.cosmos-validator-hero__main \.cosmos-validator-avatar\s*\{[^}]*width:\s*86px/)
  assert.match(css, /\.cosmos-validator-hero__main \.cosmos-validator-avatar\s*\{[^}]*border-radius:\s*11px/)
  assert.match(page, /cosmos-validator-hero__metrics/)
  assert.doesNotMatch(page, /cosmos-validator-detail__metrics/)
  assert.match(css, /\.cosmos-validator-hero__profile\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) minmax\(220px, \.42fr\)/)
  assert.match(css, /\.cosmos-validator-hero__metadata > div\s*\{[^}]*grid-template-columns:\s*64px minmax\(0, 1fr\)/)
  assert.match(css, /\.cosmos-validator-hero__metrics\s*\{[^}]*border:\s*1px solid var\(--color-border-soft\)[^}]*border-radius:\s*6px/)
  assert.match(css, /\.cosmos-validator-hero__metrics article\s*\{[^}]*padding:\s*9px 10px[^}]*border-radius:\s*5px[^}]*background:\s*var\(--color-surface-subtle\)/)
  assert.match(page, /fullAddress metadata=\{v\.identity\} action=/)
  assert.doesNotMatch(page, /Field label="Identity"/)
  assert.match(page, /className="cosmos-back block-detail__back"/)
  assert.match(page, /minimumSelfDelegation\(v\.min_self_delegation, asset\)/)
  assert.match(page, /formatSignedTokenAmount\(v\.change_24h, asset\.exponent, asset\.symbol\)/)
  assert.doesNotMatch(page, /v\.change_24h_percent/)
  assert.ok(page.indexOf('cosmos-validator-hero__description') > page.indexOf('cosmos-validator-hero__metrics'))
  assert.match(page, /hero__facts"><Field label="Rank"[\s\S]*Field label="Commission"/)
  assert.match(page, /hero__metrics"><Metric label="Voting Power"[\s\S]*Metric label="Minimum Self Delegation"/)
  assert.match(page, /cosmos-validator-detail__primary[\s\S]*Signing &amp; Liveness[\s\S]*Panel title="Consensus Identity"/)
  assert.match(page, /Panel title="Validator Parameters"[\s\S]*Panel title="Validator Economics"/)
  assert.match(page, /Address label="EVM Address" value=\{v\.evm_address\}/)
  assert.match(css, /\.cosmos-validator-detail__primary, \.cosmos-validator-detail__secondary\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1\.12fr\) minmax\(0, \.88fr\)/)
})

test('missed counters reuse the shared semantic threshold class', () => {
  const overview = fs.readFileSync(new URL('../src/pages/CosmosOverview.jsx', import.meta.url), 'utf8')
  assert.match(overview, /className=\{missedCountClass\(row\.missed_blocks_counter\)\}/)
  assert.match(page, /className=\{missedCountClass\(v\.liveness\.missed_blocks\)\}/)
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
