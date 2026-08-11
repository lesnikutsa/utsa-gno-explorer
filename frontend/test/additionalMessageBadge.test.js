import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const badge = read('../src/components/AdditionalMessageBadge.jsx')
const page = read('../src/pages/Transactions.jsx')
const styles = read('../src/styles/app.css')

test('transactions render one primary type and a bounded additional-message count', () => {
  assert.match(page, /<TransactionTypeBadge[^>]*>\{transaction\.operation\}<\/TransactionTypeBadge>/)
  assert.match(page, /<AdditionalMessageBadge messageCount=\{transaction\.message_count\} \/>/)
  assert.match(badge, /Number\.isInteger\(messageCount\) \|\| messageCount <= 1/)
  assert.match(badge, /\+\{messageCount - 1\}/)
  assert.match(badge, /title=\{`\$\{messageCount\} messages total`\}/)
})

test('counter examples follow the additional-message rule', () => {
  const displayedCount = (messageCount) => Number.isInteger(messageCount) && messageCount > 1
    ? `+${messageCount - 1}`
    : null

  assert.equal(displayedCount(7), '+6')
  assert.equal(displayedCount(2), '+1')
  for (const value of [1, null, undefined]) assert.equal(displayedCount(value), null)
})

test('additional-message badge has a separate neutral theme class', () => {
  const rule = styles.match(/\.additional-message-badge \{[^}]+\}/)?.[0] ?? ''
  assert.match(rule, /border: 1px solid var\(--color-border\)/)
  assert.match(rule, /background: var\(--color-card\)/)
  assert.match(rule, /color: var\(--color-text-secondary\)/)
  assert.doesNotMatch(rule, /color-type-|success|warning|error/)
  assert.doesNotMatch(badge, /transaction-type-badge--|status-badge/)
})
