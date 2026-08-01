import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { request } from '../src/services/api.js'
import { emptyAccountHistory, historyRequestIsCurrent } from '../src/utils/accountHistory.js'

const originalFetch = globalThis.fetch

test.afterEach(() => { globalThis.fetch = originalFetch })

test('request preserves AbortError unchanged', async () => {
  const abortError = new Error('aborted')
  abortError.name = 'AbortError'
  globalThis.fetch = async () => { throw abortError }
  await assert.rejects(request('/history', { signal: new AbortController().signal }), (error) => error === abortError && error.name === 'AbortError')
})

test('request bounds a real network failure', async () => {
  globalThis.fetch = async () => { throw new TypeError('internal fetch detail') }
  await assert.rejects(request('/history'), (error) => error.message === 'Unable to reach the Explorer API' && error.status === 0 && error.detail === 'Network request failed')
})

test('request generations reject aborted, navigated, and stale work', () => {
  const controller = new AbortController()
  const current = { controller, generation: 4, currentGeneration: 4, address: 'g1a', currentAddress: 'g1a' }
  assert.equal(historyRequestIsCurrent(current), true)
  assert.equal(historyRequestIsCurrent({ ...current, currentAddress: 'g1b' }), false)
  assert.equal(historyRequestIsCurrent({ ...current, currentGeneration: 5 }), false)
  controller.abort()
  assert.equal(historyRequestIsCurrent(current), false)
})

test('history state starts on the latest page', () => {
  assert.deepEqual(emptyAccountHistory(), { items: [], pagination: null, loading: true, initialError: false, pageError: false, pageIndex: 0, canLoadOlder: false })
})


test('account history pagination replaces pages and stores cursors', () => {
  const hook = readFileSync(new URL('../src/hooks/useAccountDetail.js', import.meta.url), 'utf8')
  assert.ok(hook.includes('export const ACCOUNT_HISTORY_PAGE_SIZE = 20'))
  assert.ok(hook.includes('limit: ACCOUNT_HISTORY_PAGE_SIZE'))
  assert.ok(hook.includes('const [cursorHistory, setCursorHistory] = useState([null])'))
  assert.ok(hook.includes('items: (result.items || []).slice(0, ACCOUNT_HISTORY_PAGE_SIZE)'))
  assert.ok(hook.includes('loadHistoryPage(cursorHistory[history.pageIndex - 1], history.pageIndex - 1)'))
  assert.ok(hook.includes('setCursorHistory([null])'))
  assert.ok(hook.includes('loadHistoryPage(null, 0, [null])'))
  assert.equal(hook.includes('mergeAccountHistoryItems'), false)
  assert.equal(hook.includes('items: [...'), false)
})
