import test from 'node:test'
import assert from 'node:assert/strict'

import { request } from '../src/services/api.js'
import { emptyAccountHistory, historyRequestIsCurrent, mergeAccountHistoryItems } from '../src/utils/accountHistory.js'

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

test('history state separates initial and load-more errors', () => {
  assert.deepEqual(emptyAccountHistory(), { items: [], pagination: null, loading: true, loadingMore: false, initialError: false, loadMoreError: false })
})

test('load-more merge preserves order and removes overlapping positions', () => {
  const existing = [{ block_height: 10, index: 2 }, { block_height: 10, index: 1 }]
  const incoming = [{ block_height: 10, index: 1, changed: true }, { block_height: 9, index: 0 }]
  assert.deepEqual(mergeAccountHistoryItems(existing, incoming), [...existing, incoming[1]])
})
