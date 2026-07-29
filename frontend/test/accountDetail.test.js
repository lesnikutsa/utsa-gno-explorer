import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { decodeAccountRouteAddress } from '../src/utils/account.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const api = read('../src/services/api.js')
const hook = read('../src/hooks/useAccountDetail.js')
const page = read('../src/pages/AccountDetail.jsx')
const validator = read('../src/pages/ValidatorDetail.jsx')

const address = 'g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75'

test('account route decoder accepts plain and encoded addresses', () => {
  assert.equal(decodeAccountRouteAddress(address), address)
  assert.equal(decodeAccountRouteAddress(encodeURIComponent(address)), address)
})
test('account route decoder rejects empty, slashes, excessive length, and malformed encoding', () => {
  assert.equal(decodeAccountRouteAddress(''), null)
  assert.equal(decodeAccountRouteAddress('%2F'), null)
  assert.equal(decodeAccountRouteAddress('a'.repeat(129)), null)
  assert.equal(decodeAccountRouteAddress('%E0%A4%A'), null)
})
test('App recognizes account routes with an optional trailing slash', () => {
  assert.match(app, /path\.match\(\/\^\\\/accounts/)
  assert.ok(app.includes('<AccountDetailPage address={accountDetailMatch[1]} />'))
})
test('API client uses the shared request wrapper and encodes the address', () => {
  assert.ok(api.includes('getAccount = (address) => request(`/accounts/${encodeURIComponent(address)}`)'))
  assert.ok(api.includes("error.status = 0"))
})
test('hook maps safe states, supports retry and has no polling timer', () => {
  for (const text of ['requestError.status === 422', 'requestError.status === 503', 'const retry = useCallback', 'requestId === requestIdRef.current']) assert.ok(hook.includes(text))
  assert.equal(hook.includes('setTimeout'), false)
  assert.equal(hook.includes('setInterval'), false)
})
test('page contains account content and all safe result states', () => {
  for (const text of ['Loading account…', 'Invalid account address', 'Account data is temporarily unavailable', 'Account details are currently unavailable', 'Account not found']) assert.ok(page.includes(text))
  for (const text of ['Balance', 'Raw amount', 'Account Number', 'Sequence', 'Public Key', 'Validator Relation', 'No native bank balances', 'Public key not available']) assert.ok(page.includes(text))
  assert.ok(page.includes("primary.display_amount"))
  assert.ok(page.includes("balance.amount"))
  assert.ok(page.includes("new URL(source?.rpc_url).hostname"))
})
test('validator operator address links to an encoded account route only when present', () => {
  assert.ok(validator.includes('href={validator.operator_address ? `/accounts/${encodeURIComponent(validator.operator_address)}` : undefined}'))
})
