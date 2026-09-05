import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const css = fs.readFileSync(new URL('../src/styles/cosmos-validator-reward-usd.css', import.meta.url), 'utf8')

test('validator detail paired panels use the requested visual order', () => {
  assert.match(css, /cosmos-validator-detail__secondary > \.cosmos-validator-fields:not\(\.cosmos-validator-reward-fields\)\s*\{[^}]*order:\s*1/)
  assert.match(css, /cosmos-validator-detail__secondary > \.cosmos-validator-reward-fields\s*\{[^}]*order:\s*2/)
  assert.match(css, /cosmos-validator-detail__lower > \.cosmos-validator-activity\s*\{[^}]*order:\s*1/)
  assert.match(css, /cosmos-validator-detail__lower > \.cosmos-validator-delegators\s*\{[^}]*order:\s*2/)
})

test('validator activity and delegators headings omit helper subtitles visually', () => {
  assert.match(css, /cosmos-validator-activity \.panel__meta,[\s\S]*cosmos-validator-delegators \.panel__meta\s*\{[^}]*display:\s*none/)
})
