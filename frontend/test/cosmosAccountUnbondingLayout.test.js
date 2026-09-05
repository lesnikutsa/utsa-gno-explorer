import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')

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
