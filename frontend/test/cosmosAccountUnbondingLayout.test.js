import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/cosmos-account-detail.css', import.meta.url), 'utf8')

test('unbonding uses one shared column header row instead of repeating labels per entry', () => {
  const sectionStart = page.indexOf('cosmos-account-unbonding')
  const sectionEnd = page.indexOf('cosmos-account-technical', sectionStart)
  const section = page.slice(sectionStart, sectionEnd)

  assert.match(section, /<span>Validator<\/span>/)
  assert.match(section, /<span>Amount<\/span>/)
  assert.match(section, /<span>Completion<\/span>/)
  assert.match(section, /<span>Remaining<\/span>/)
  assert.match(section, /group\.entries\.map/)
  assert.match(section, /<div><strong>\{group\.denom \? formatCoin/)
  assert.match(section, /<div><strong>\{utc\(entry\.completion_time\)\}<\/strong><\/div>/)
  assert.match(section, /<div><strong>\{formatDuration\(entry\.remaining_seconds\)\}<\/strong><\/div>/)
  assert.doesNotMatch(section, /<div><span>Amount<\/span><strong>/)
  assert.doesNotMatch(section, /<div><span>Completion<\/span><strong>/)
  assert.doesNotMatch(section, /<div><span>Remaining<\/span><strong>/)
})

test('unbonding desktop columns align with the delegations table', () => {
  assert.match(css, /\.cosmos-account-delegations th:nth-child\(1\)[^}]*width: 34%/)
  assert.match(css, /\.cosmos-account-delegations th:nth-child\(2\)[^}]*width: 18%/)
  assert.match(css, /\.cosmos-account-delegations th:nth-child\(3\)[^}]*width: 24%/)
  assert.match(css, /\.cosmos-account-delegations th:nth-child\(4\)[^}]*width: 24%/)
  assert.match(css, /\.cosmos-account-unbonding-row \{[^}]*grid-template-columns: 34% 18% 24% 24%[^}]*gap: 0[^}]*padding: 0/)
  assert.match(css, /\.cosmos-account-unbonding-row > \.cosmos-account-validator,[\s\S]*?\.cosmos-account-unbonding-row > div \{[^}]*padding: 13px 16px/)
  assert.match(css, /\.cosmos-account-unbonding-row:first-child > div \{[^}]*padding-top: 9px[^}]*padding-bottom: 9px/)
})
