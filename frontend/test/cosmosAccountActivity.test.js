import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosAccountDetail.jsx', import.meta.url), 'utf8')
const activity = fs.readFileSync(new URL('../src/components/CosmosAccountActivity.jsx', import.meta.url), 'utf8')
const css = fs.readFileSync(new URL('../src/styles/cosmos-account-activity.css', import.meta.url), 'utf8')

test('account page places recent activity after unbonding and before technical details', () => {
  assert.match(page, /cosmos-account-unbonding[\s\S]*<CosmosAccountActivity[\s\S]*cosmos-account-technical/)
  assert.match(page, /market=\{market\.data\}/)
})

test('account activity is bounded, paginated and network scoped', () => {
  assert.match(activity, /accounts\/\$\{encodeURIComponent\(address\)\}\/activity/)
  assert.match(activity, /limit: '10'/)
  assert.match(activity, /page < 5/)
  assert.match(activity, /Show 10 more ↓/)
})

test('account activity keeps graceful indexing states and hash navigation', () => {
  assert.match(activity, /Recent activity is unavailable from the current transaction index\./)
  assert.match(activity, /Recent activity is temporarily unavailable\./)
  assert.match(activity, /No recent account activity found\./)
  assert.match(activity, /\/transactions\/\$\{item\.tx_hash\}/)
  assert.match(activity, /\/blocks\/\$\{item\.height\}/)
})

test('account activity exposes the expected human actions and validator activity tones', () => {
  for (const label of ['Received', 'Sent', 'Delegate', 'Undelegate', 'Redelegate', 'Withdraw reward', 'Vote', 'IBC transfer', 'Authz execution']) {
    assert.match(activity, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
  assert.match(activity, /function actionTone\(item\)/)
  assert.match(activity, /item\.action === 'withdraw_reward'[\s\S]*return 'neutral'/)
  assert.match(activity, /return item\.direction/)
  assert.match(css, /is-positive[^{]*\{[^}]*var\(--color-success\)/)
  assert.match(css, /is-negative[^,]*,[^{]*is-failed[^{]*\{[^}]*var\(--color-error\)/)
  assert.match(css, /is-neutral[^{]*\{[^}]*var\(--color-text\)/)
})

test('activity columns align with the account unbonding table', () => {
  assert.match(activity, /<th>Activity<\/th><th>Amount \/ Detail<\/th><th>Height \/ Time<\/th><th>TX<\/th>/)
  assert.match(css, /nth-child\(1\)[^{]*\{ width: 34%; \}/)
  assert.match(css, /nth-child\(2\)[^{]*\{ width: 18%; \}/)
  assert.match(css, /nth-child\(3\)[^{]*\{ width: 24%; \}/)
  assert.match(css, /nth-child\(4\)[^{]*\{ width: 24%; \}/)
})

test('activity rows keep native table cells and continuous delegation-style separators', () => {
  assert.match(css, /\.cosmos-account-activity td \{[^}]*padding: 13px 16px[^}]*border-top: 1px solid var\(--color-border\)/)
  assert.doesNotMatch(css, /\.cosmos-account-activity td:first-child,[^{]*\{[^}]*display:\s*grid/)
  assert.match(css, /td:first-child > strong,[\s\S]*td:nth-child\(3\) > small \{ display: block;/)
})
