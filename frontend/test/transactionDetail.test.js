import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { isValidArgumentValue } from '../src/utils/transactionArguments.js'

const summary = readFileSync(new URL('../src/components/TransactionSummary.jsx', import.meta.url), 'utf8')
const detail = readFileSync(new URL('../src/pages/TransactionDetail.jsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('message rows use independent native disclosures with only the first open initially', () => {
  assert.match(summary, /const \[open, setOpen\] = useState\(index === 0\)/)
  assert.match(summary, /open=\{open\}/)
  assert.match(summary, /onToggle=\{\(event\) => setOpen\(event\.currentTarget\.open\)\}/)
  assert.match(summary, /function MessageDisclosure/)
  assert.match(summary, /<summary id=/)
  assert.doesNotMatch(summary, /accordion/i)
  assert.match(styles, /transaction-summary__message > summary:focus-visible/)
})

test('each message disclosure owns state that survives parent rerenders independently', () => {
  assert.match(summary, /<MessageDisclosure[\s\S]*key=\{index\}/)
  assert.doesNotMatch(summary, /open=\{index === 0\}/)
  assert.doesNotMatch(summary, /setOpenMessage|activeMessage|openIndex/)
})

test('bounded arguments render as escaped message-local text with fallback and truncation notice', () => {
  assert.match(summary, /argumentDetails\.get\(index\)/)
  assert.match(summary, /detail\.values\.map/)
  assert.match(summary, /value === '' \? '—' : value/)
  assert.match(summary, /showArgumentFallback=\{!argumentDetail\}/)
  assert.match(summary, /Some argument values were shortened or are not shown\./)
  assert.doesNotMatch(summary, /dangerouslySetInnerHTML/)
  assert.match(styles, /overflow-wrap: anywhere/)
})

test('argument limits count Unicode code points and reject controls', () => {
  assert.equal(isValidArgumentValue('a'.repeat(256)), true)
  assert.equal(isValidArgumentValue('🙂'.repeat(256)), true)
  assert.equal(isValidArgumentValue('🙂'.repeat(257)), false)
  assert.equal(isValidArgumentValue('control\nvalue'), false)
  assert.equal(isValidArgumentValue(''), true)
})

test('Developer Data keeps raw Base64 behind a nested disclosure', () => {
  assert.match(detail, /<summary>Developer Data<\/summary>/)
  assert.match(detail, /<summary>Show raw transaction<\/summary>/)
  assert.doesNotMatch(detail, /transaction-detail__developer-actions/)
  assert.doesNotMatch(styles, /transaction-detail__developer-actions/)
  const rawDisclosure = detail.slice(detail.indexOf('<summary>Show raw transaction</summary>'))
  const rawContent = rawDisclosure.slice(rawDisclosure.indexOf('transaction-detail__raw-content'))
  assert.match(rawContent, /<div className="panel__heading"><h2>Raw Transaction Base64<\/h2><CopyButton value=\{transaction\.raw_base64\} label="raw transaction" \/><\/div>/)
  assert.match(rawContent, /<pre className="transaction-detail__raw-value mono">\{transaction\.raw_base64\}<\/pre>/)
  assert.ok(rawContent.indexOf('label="raw transaction"') < rawContent.indexOf('transaction-detail__raw-value'))
  assert.doesNotMatch(detail, /Technical Data|Encoded length|Low-level encoded transaction data/)
  assert.match(detail, /Execution Details/)
})

test('transaction hash copy control stays beside the wrapping heading hash', () => {
  assert.match(detail, /<div className="transaction-detail__copy-row transaction-detail__copy-row--heading">\s*<h1 className="transaction-detail__heading-hash mono"[^>]*>\{transaction\.tx_hash\}<\/h1>\s*<CopyButton value=\{transaction\.tx_hash\} label="transaction hash" \/>/)
  assert.match(styles, /\.transaction-detail__heading-hash \{ flex: 0 1 auto;/)
  assert.match(styles, /\.transaction-detail__copy-row--heading \{ width: fit-content; max-width: 100%; \}/)
  assert.match(styles, /\.transaction-detail__copy-row--heading \.copy-button \{ flex: 0 0 auto; \}/)
  assert.match(styles, /\.transaction-detail__copy-row \{ display: flex; align-items: flex-start; gap: 8px; min-width: 0; \}/)
  assert.match(styles, /\.transaction-detail__hash \{ flex: 1 1 auto;/)
})
