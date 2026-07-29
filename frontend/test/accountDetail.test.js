import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { decodeAccountRouteAddress, findNativeBalance, findOtherBalances } from '../src/utils/account.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const app = read('../src/App.jsx')
const api = read('../src/services/api.js')
const hook = read('../src/hooks/useAccountDetail.js')
const page = read('../src/pages/AccountDetail.jsx')
const validator = read('../src/pages/ValidatorDetail.jsx')
const profile = read('../src/config/networkProfile.js')

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
test('network profile defines the native denom with an ugnot fallback', () => {
  assert.ok(profile.includes('import.meta.env.VITE_NATIVE_DENOM'))
  assert.match(profile, /nativeDenom:\s*publicValue\([\s\S]*?'ugnot'/)
})
test('primary balance selection uses denom rather than a display symbol', () => {
  const synthetic = { denom: 'GNOT', symbol: 'GNOT' }
  const native = { denom: 'ugnot', symbol: 'GNOT' }
  assert.equal(findNativeBalance([synthetic, native], 'ugnot'), native)
  assert.ok(page.includes('findNativeBalance(balances, networkProfile.nativeDenom)'))
  assert.equal(page.includes("balance.symbol === 'GNOT'"), false)
})
test('missing account refresh reuses retry, preserves content, and reports errors safely', () => {
  assert.ok(page.includes('function MissingAccount({ account, retry, loading, refreshError })'))
  assert.ok(page.includes('onClick={retry} disabled={loading}'))
  assert.ok(page.includes("loading ? 'Refreshing…' : 'Refresh'"))
  assert.ok(page.includes('refreshError && <p className="account-detail__refresh-error"'))
  assert.ok(page.includes('<MissingAccount account={account} retry={retry} loading={loading}'))
  assert.ok(page.includes('This address has no account state on the current network.'))
  assert.ok(page.includes('<FetchedAt height={account.observed_height} />'))
})
test('page uses a compact balance and account summary overview', () => {
  assert.ok(page.includes('account-detail__overview'))
  assert.ok(page.includes('Account Summary'))
  assert.ok(page.includes('Fetched at block'))
  assert.ok(page.includes('account-detail__main-balance'))
  assert.equal(page.includes('label="Observed Height"'), false)
  const balanceCard = page.slice(page.indexOf('aria-labelledby="account-balance-title"'), page.indexOf('aria-labelledby="account-summary-title"'))
  assert.ok(balanceCard.includes('primary.display_amount'))
  assert.ok(balanceCard.includes('primary.symbol'))
  for (const label of ['Denom', 'Raw amount', 'Decimals', 'account-detail__compact-list']) assert.equal(balanceCard.includes(label), false)
})
test('page keeps technical and validator information compact', () => {
  assert.ok(page.includes('<details className="panel account-detail__details">'))
  assert.ok(page.includes('<summary>Technical details</summary>'))
  assert.ok(page.includes('Operator account'))
  assert.ok(page.includes('Signing validator'))
  const technicalDetails = page.slice(page.indexOf('<details className="panel account-detail__details">'), page.indexOf('</details>'))
  for (const label of ['Native balance', 'Denom', 'Raw amount', 'Decimals', 'Network', 'RPC endpoint', 'Observed RPC height', 'Public key']) assert.ok(technicalDetails.includes(label))
})
test('other balances exclude native denom and render only when non-native balances exist', () => {
  const native = { denom: 'ugnot' }
  const other = { denom: 'uatom' }
  assert.deepEqual(findOtherBalances([native, other], 'ugnot'), [other])
  assert.deepEqual(findOtherBalances([native], 'ugnot'), [])
  assert.ok(page.includes('otherBalances.length > 0'))
  assert.ok(page.includes('otherBalances.map'))
  assert.equal(page.includes('balances.map'), false)
  assert.ok(page.includes('Other balances'))
})
test('page contains account content and all safe result states', () => {
  for (const text of ['Loading account…', 'Invalid account address', 'Account data is temporarily unavailable', 'Account details are currently unavailable', 'Account not found']) assert.ok(page.includes(text))
  for (const text of ['Balance', 'Raw amount', 'Account number', 'Sequence', 'Technical details', 'Validator', 'No native bank balance', 'Public key not available']) assert.ok(page.includes(text))
  assert.ok(page.includes("primary.display_amount"))
  assert.ok(page.includes("balance.amount"))
  assert.ok(page.includes("new URL(source?.rpc_url).hostname"))
})
test('validator operator address links to an encoded account route only when present', () => {
  assert.ok(validator.includes('href={validator.operator_address ? `/accounts/${encodeURIComponent(validator.operator_address)}` : undefined}'))
})
