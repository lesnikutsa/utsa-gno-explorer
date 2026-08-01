import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const summary = readFileSync(new URL('../src/components/TransactionSummary.jsx', import.meta.url), 'utf8')
const detail = readFileSync(new URL('../src/pages/TransactionDetail.jsx', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')

test('message rows use independent native disclosures with only the first open initially', () => {
  assert.match(summary, /<details className="transaction-summary__message" open=\{index === 0\}/)
  assert.match(summary, /<summary id=/)
  assert.doesNotMatch(summary, /setOpen|accordion/i)
  assert.match(styles, /transaction-summary__message > summary:focus-visible/)
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

test('Developer Data keeps raw Base64 behind a nested disclosure', () => {
  assert.match(detail, /<summary>Developer Data<\/summary>/)
  assert.match(detail, /<summary>Show raw transaction<\/summary>/)
  assert.match(detail, /label="raw transaction"/)
  assert.doesNotMatch(detail, /Technical Data|Encoded length|Low-level encoded transaction data/)
  assert.match(detail, /Execution Details/)
})
