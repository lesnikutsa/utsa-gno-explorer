import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const blocks = read('../src/pages/CosmosBlocks.jsx')
const detail = read('../src/pages/CosmosBlockDetail.jsx')
const identity = read('../src/components/CosmosValidatorIdentity.jsx')
const resource = read('../src/hooks/useCosmosResource.js')
const styles = read('../src/styles/app.css')
const gnoBlocks = read('../src/pages/Blocks.jsx')
const gnoDetail = read('../src/pages/BlockDetail.jsx')

test('Cosmos Blocks has the canonical heading and no duplicate height search', () => {
  assert.match(blocks, /<h1>Blocks<\/h1>/)
  assert.doesNotMatch(blocks, /<form|Block height|cosmos-height-search|inputMode="numeric"/)
})

test('Cosmos Blocks columns are ordered and use TIME rather than AGE', () => {
  assert.match(blocks, /<th>Height<\/th><th>Time<\/th><th>Proposer<\/th><th>Txs<\/th><th>Block hash<\/th>/)
  assert.doesNotMatch(blocks, /<th>Age<\/th>/i)
})

test('Cosmos Blocks presents relative time while retaining the exact timestamp', () => {
  assert.match(blocks, /<time dateTime=\{block\.timestamp\} title=\{block\.timestamp\}>\{relativeTime\(block\.timestamp\)\}<\/time>/)
})

test('Cosmos Blocks uses monikers with an address fallback and shortened hashes', () => {
  assert.match(blocks, /moniker=\{block\.proposer_moniker\}/)
  assert.match(blocks, /block\.proposer_operator_address \|\| block\.proposer/)
  assert.match(identity, /\{moniker \|\| 'Unknown proposer'\}/)
  assert.match(identity, /shortAddress\(address\)/)
  assert.match(blocks, /value\.slice\(0, 6\).*value\.slice\(-6\)/)
  assert.match(blocks, /<code title=\{block\.hash\}>/)
})

test('stale Cosmos Blocks never claims Live and reuses Explorer row animation classes', () => {
  assert.match(blocks, /resource\.stale\s*\? <span className="cosmos-stale">Stale · last successful data<\/span>\s*: <span className="panel__meta panel__meta--live">/)
  assert.match(blocks, /'is-new-row'.*'is-settling-row'/s)
})

test('larger table typography is scoped to Cosmos Blocks only', () => {
  assert.match(blocks, /className="cosmos-blocks"/)
  assert.match(styles, /\.cosmos-blocks \.cosmos-table \{ font-size: 1\.08rem; \}/)
  assert.match(styles, /prefers-reduced-motion.*\.cosmos-blocks \.is-new-row/s)
})

test('confirmed full Block Detail uses generic no-poll resource mode', () => {
  assert.match(detail, /\/detail`, null\)/)
  assert.doesNotMatch(detail, /\/detail`, 30000\)/)
  assert.match(resource, /const timer = interval \? window\.setInterval/)
  assert.match(resource, /if \(interval\) document\.addEventListener\('visibilitychange'/)
})

test('Block Detail has navigation, title, summary, and latest behavior', () => {
  assert.match(detail, />← Back to Blocks<\/a>/)
  assert.match(detail, /<h1>Block #\{Number\(height\)\.toLocaleString\(\)\}<\/h1>/)
  for (const label of ['Height', 'Time', 'Transactions', 'Chain ID']) assert.match(detail, new RegExp(`label="${label}"`))
  assert.match(detail, /data\.height - 1/)
  assert.match(detail, /data\.height \+ 1/)
  assert.match(detail, /data\.height < lookup\.local_height/)
  assert.match(detail, /<span>Latest<\/span>/)
})

test('Block Detail exposes human and technical information through compact disclosures', () => {
  assert.match(detail, /<h2>Block Information<\/h2>/)
  assert.match(detail, /moniker=\{data\.proposer_moniker\}/)
  assert.match(detail, /\['Block hash', data\.hashes\.block\].*\['App hash', data\.hashes\.app\].*\['Validators hash', data\.hashes\.validators\]/)
  assert.match(detail, /<summary>More technical hashes<\/summary>/)
  assert.match(detail, /<h2>Commit Summary<\/h2>/)
  assert.match(detail, /<summary>Commit Signatures \(\{data\.signatures\.length\}\)<\/summary>/)
})

test('Block Detail handles transaction rows, zero state, optional evidence and collapsed JSON', () => {
  assert.match(detail, /data\.transactions\.map/)
  assert.match(detail, /No transactions in this block\./)
  assert.match(detail, /data\.evidence\.length > 0 && <section/)
  assert.doesNotMatch(detail, /<details[^>]*open/)
  assert.match(detail, /<details className="panel cosmos-normalized-json"><summary>Normalized JSON<\/summary>/)
})

test('Gno Blocks and Block Detail remain outside Cosmos-scoped implementation', () => {
  assert.doesNotMatch(gnoBlocks, /cosmos-blocks|cosmos-detail/)
  assert.doesNotMatch(gnoDetail, /cosmos-blocks|cosmos-detail/)
  assert.match(gnoBlocks, /<h1 id="blocks-page-title">Blocks<\/h1>/)
  assert.match(gnoDetail, /<h1 id="block-detail-title">Block #/ )
})
