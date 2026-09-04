import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosValidatorDetail.jsx', import.meta.url), 'utf8')
const styles = fs.readFileSync(new URL('../src/styles/cosmos-validator-reward-usd.css', import.meta.url), 'utf8')

test('validator detail makes category-local rank explicit', () => {
  assert.match(page, /active: 'Active Rank'/)
  assert.match(page, /inactive: 'Inactive Rank'/)
  assert.match(page, /jailed: 'Jailed Rank'/)
  assert.match(page, /Field label="Rank" displayLabel=\{rankLabel\(v\.category\)\}/)
})

test('validator hero tiles reuse the shared light hover surface', () => {
  assert.match(styles, /cosmos-validator-hero__facts > div:hover/)
  assert.match(styles, /cosmos-validator-hero__metrics > article:hover/)
  assert.match(styles, /background:\s*var\(--color-overlay-hover\)/)
})
