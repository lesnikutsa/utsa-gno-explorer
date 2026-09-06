import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const blocks = read('../src/pages/CosmosBlocks.jsx')
const detail = read('../src/pages/CosmosBlockDetail.jsx')
const transactionDetail = read('../src/pages/CosmosTransactionDetail.jsx')
const executionBadge = read('../src/components/TransactionExecutionBadge.jsx')
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
  assert.match(blocks, /imageSrc=\{block\.proposer_avatar_url\}/)
  assert.match(blocks, /imageSrc=\{block\.proposer_avatar_url\} showTitles=\{false\}/)
  assert.match(identity, /\{moniker \|\| 'Unknown proposer'\}/)
  assert.match(identity, /shortAddress\(address\)/)
  assert.match(blocks, /value\.slice\(0, 6\).*value\.slice\(-6\)/)
  assert.match(blocks, /<code className="muted" title=\{block\.hash\}>/)
})

test('stale Cosmos Blocks never claims Live and reuses Explorer row animation classes', () => {
  assert.match(blocks, /resource\.stale\s*\? <span className="cosmos-stale">Stale · last successful data<\/span>\s*: <span className="panel__meta panel__meta--live">/)
  assert.match(blocks, /'is-new-row'.*'is-settling-row'/s)
})

test('shared compact table typography is scoped to Cosmos Blocks only', () => {
  assert.match(blocks, /className="cosmos-blocks"/)
  assert.match(styles, /\.cosmos-blocks \.cosmos-table table \{[^}]*font-size: 11px;/)
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
  assert.match(detail, /<h1>Block #\{formattedHeight\}<\/h1>/)
  assert.match(detail, /futureHeightValues\(String\(height\), data\.local_height\)/)
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
  assert.match(detail, /<span className="cosmos-copy-value"><CosmosValidatorIdentity/)
  assert.match(styles, /\.cosmos-copy-value \{[^}]*width: 100%;[^}]*justify-content: space-between;/)
  assert.match(styles, /\.cosmos-detail-summary > div \{[^}]*border: 1px solid var\(--color-border-soft\);[^}]*background: var\(--color-surface-subtle\);/)
  assert.match(detail, /className=\{compact \? undefined : 'cosmos-hash-value'\}/)
  assert.match(detail, /blocks\/\$\{data\.height\}\/transactions\/\$\{tx\.index\}/)
  assert.match(detail, /className="transaction-hash mono cosmos-hash-value cosmos-tx-full-hash-link"[^>]*>\{tx\.hash\}<\/a><CopyButton value=\{tx\.hash\}/)
  assert.doesNotMatch(detail, /cosmos-tx-full-hash-link[^>]*title=\{tx\.hash\}/)
  assert.doesNotMatch(detail, /label="transaction hash" compact/)
  assert.doesNotMatch(detail, /shortHash/)
  assert.match(styles, /\.cosmos-detail-card details > summary, \.cosmos-normalized-json > summary, \.cosmos-detail-toggle \{[^}]*display: inline-flex;[^}]*width: fit-content;[^}]*max-width: calc\(100% - 24px\);[^}]*border: 1px solid var\(--color-accent\);[^}]*background: var\(--color-accent-soft\)/)
  assert.match(styles, /details > summary::after, \.cosmos-normalized-json > summary::after \{[^}]*content: '↓'/)
  assert.match(styles, /details\[open\] > summary::after, \.cosmos-normalized-json\[open\] > summary::after \{ content: '↑'; \}/)
  assert.doesNotMatch(styles, /details > summary::after[^}]*position: absolute/)
  assert.match(styles, /details\[open\] > summary, \.cosmos-normalized-json\[open\] > summary \{[^}]*background: rgba\(200,75,49,\.18\)/)
  assert.match(styles, /\.cosmos-copy-value code \{[^}]*overflow-wrap: anywhere;[^}]*word-break: break-all;/)
  assert.match(styles, /\.cosmos-copy-value \.cosmos-hash-value \{ font-size: 12px; \}/)
  assert.match(styles, /\.cosmos-detail-summary > div > span, \.cosmos-commit-summary > div > span/)
  assert.doesNotMatch(styles, /\.cosmos-detail-summary span, \.cosmos-commit-summary span/)
})

test('Cosmos Transaction Detail keeps block-context navigation and readable normalized data', () => {
  assert.match(app, /cosmosTxMatch/)
  assert.match(app, /<CosmosTransactionDetail network=\{network\} height=\{txHeight\} index=\{txIndex\}/)
  assert.match(transactionDetail, /blocks\/\$\{height\}\/transactions\/\$\{index\}/)
  assert.match(transactionDetail, /className="cosmos-hash-value" title=\{tx\.tx_hash\}>\{tx\.tx_hash\}/)
  assert.match(transactionDetail, /CopyButton value=\{tx\.tx_hash\}/)
  assert.match(transactionDetail, /blocks\/\$\{tx\.height\}/)
  assert.match(transactionDetail, /dateTime=\{tx\.timestamp\}/)
  for (const label of ['Gas used', 'Gas wanted', 'Fee', 'Memo']) assert.match(transactionDetail, new RegExp(`<dt>${label}`))
  assert.match(transactionDetail, /message\.action/)
  assert.match(transactionDetail, /message\.type_url/)
  assert.match(transactionDetail, /No safely decoded fields are available/)
  assert.match(transactionDetail, /<summary>More transaction details<\/summary>/)
  assert.match(transactionDetail, /<summary>Normalized JSON<\/summary>/)
  assert.match(transactionDetail, /<TransactionExecutionBadge status=\{tx\.success \? 'success' : 'failed'\} \/>/)
  assert.match(executionBadge, /status === 'success'.*label: 'Success'.*tone: 'success'/)
  assert.match(executionBadge, /status === 'failed'.*label: 'Failed'.*tone: 'error'/)
})

test('Block Detail handles transaction rows, zero state, optional evidence and collapsed JSON', () => {
  assert.match(detail, /data\.transactions\.map/)
  assert.match(detail, /<TransactionExecutionBadge status=\{tx\.status\} \/>/)
  assert.match(detail, /import \{ TransactionExecutionBadge \}/)
  assert.doesNotMatch(detail, /cosmos-tx-status/)
  assert.match(detail, /No transactions in this block\./)
  assert.match(detail, /data\.evidence\.length > 0 && <section/)
  assert.doesNotMatch(detail, /<details[^>]*open/)
  assert.match(detail, /<details className="panel cosmos-normalized-json"><summary>Normalized JSON<\/summary>/)
})

test('future and unavailable blocks use human-friendly state presentation', () => {
  const futureCard = read('../src/components/FutureBlockCard.jsx')
  assert.match(detail, /<FutureBlockCard/)
  assert.match(futureCard, /has not been produced yet/)
  for (const label of ['Current height', 'Blocks remaining', 'Average block time', 'Estimated arrival']) {
    assert.match(futureCard, new RegExp(`label="${label}"`))
  }
  assert.match(futureCard, /Estimated time until block/)
  for (const unit of ['Days', 'Hours', 'Minutes', 'Seconds']) assert.match(futureCard, new RegExp(`'${unit}'`))
  assert.match(futureCard, /formatAverageBlockTime\(eta\.average_block_seconds\)/)
  assert.match(futureCard, /formatEstimatedArrival\(eta\.estimated_at\)/)
  assert.match(futureCard, /Estimate based on recent network block production/)
  assert.match(futureCard, /Estimated arrival is temporarily unavailable/)
  assert.match(detail, /data\.eta_unavailable_reason \? null : data\.eta/)
  assert.match(detail, /RPC is still syncing/)
  assert.match(detail, /pruned this historical block/)
  assert.doesNotMatch(detail, /replaceAll\('_'/)
  assert.doesNotMatch(detail, /\$\{remainingSeconds\}s remaining/)
  assert.match(styles, /\.cosmos-future-countdown__grid \{[^}]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/)
  assert.match(styles, /max-width: 800px[^}]*\.cosmos-future-countdown__grid \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.cosmos-future-countdown__grid > div \{[^}]*min-width: 0;/)
})

test('Gno Blocks preserve normal detail while sharing only the future card', () => {
  assert.doesNotMatch(gnoBlocks, /cosmos-blocks|cosmos-detail/)
  assert.match(gnoDetail, /FutureBlockCard/)
  assert.match(gnoBlocks, /<h1 id="blocks-page-title">Blocks<\/h1>/)
  assert.match(gnoDetail, /<h1 id="block-detail-title">Block #/ )
})
