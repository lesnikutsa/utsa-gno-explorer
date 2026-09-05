import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const css = fs.readFileSync(new URL('../src/styles/cosmos-account-detail.css', import.meta.url), 'utf8')

test('account staking typography matches validator detail delegator values', () => {
  assert.match(css, /\.cosmos-account-validator > a \{[^}]*color: var\(--color-text-bright\)[^}]*font-family: inherit[^}]*font-size: 12px[^}]*font-weight: 600/)
  assert.match(css, /\.cosmos-account-delegations td:nth-child\(3\) > strong,[\s\S]*td:nth-child\(4\) \.cosmos-account-coin-line > span \{[^}]*color: var\(--color-text-bright\)[^}]*font-family: inherit[^}]*font-size: 12px[^}]*font-weight: 400/)
  assert.match(css, /\.cosmos-account-unbonding-row > div > span \{[^}]*font-family: inherit[^}]*font-size: 10px[^}]*font-weight: 700[^}]*letter-spacing: 0/)
  assert.match(css, /\.cosmos-account-unbonding-row > div > strong \{[^}]*color: var\(--color-text-bright\)[^}]*font-family: inherit[^}]*font-size: 12px[^}]*font-weight: 400/)
})
