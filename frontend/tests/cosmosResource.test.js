import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CosmosResourceTimeoutError,
  cosmosResourceFailureState,
  cosmosResourceResponseIsCurrent,
  loadCosmosResourceWithTimeout,
} from '../src/hooks/useCosmosResource.js'

globalThis.window ??= globalThis

test('a hung request times out and a later retry can succeed', async () => {
  const hung = new AbortController()
  await assert.rejects(
    loadCosmosResourceWithTimeout(() => new Promise(() => {}), hung, 5),
    CosmosResourceTimeoutError,
  )
  assert.equal(hung.signal.aborted, true)
  const retry = new AbortController()
  assert.deepEqual(await loadCosmosResourceWithTimeout(async () => ({ height: 42 }), retry, 50), { height: 42 })
})

test('a refresh failure preserves previous data and marks it stale', () => {
  const data = { height: 41 }
  const error = new CosmosResourceTimeoutError(5)
  assert.deepEqual(cosmosResourceFailureState({ data, loading: false, error: null, stale: false, updatedAt: 1 }, error), {
    data, loading: false, error, stale: true, updatedAt: 1,
  })
})

test('late responses from an aborted or replaced resource are ignored', () => {
  const oldController = new AbortController()
  assert.equal(cosmosResourceResponseIsCurrent({ generation: 1, currentGeneration: 2, controller: oldController }), false)
  oldController.abort()
  assert.equal(cosmosResourceResponseIsCurrent({ generation: 2, currentGeneration: 2, controller: oldController }), false)
  assert.equal(cosmosResourceResponseIsCurrent({ generation: 2, currentGeneration: 2, controller: new AbortController() }), true)
})
