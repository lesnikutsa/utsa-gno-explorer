import assert from 'node:assert/strict'
import test from 'node:test'
import { CosmosRequestScope } from '../src/utils/cosmosRequestScope.js'

const controller = () => ({ aborted: false, abort() { this.aborted = true } })

test('URL change cancels and invalidates the previous resource response', () => {
  const scope = new CosmosRequestScope()
  const oldController = controller()
  const oldRequest = scope.begin('/api/networks/a/blocks/10', oldController)
  scope.reset()
  const currentRequest = scope.begin('/api/networks/a/blocks/11', controller())
  assert.equal(oldController.aborted, true)
  assert.equal(scope.isCurrent(oldRequest, oldRequest.url), false)
  assert.equal(scope.isCurrent(currentRequest, currentRequest.url), true)
})

test('late completion cannot clear a newer in-flight request', () => {
  const scope = new CosmosRequestScope()
  const oldRequest = scope.begin('/old', controller())
  scope.reset()
  const currentRequest = scope.begin('/new', controller())
  scope.finish(oldRequest)
  assert.equal(scope.current, currentRequest)
})

test('StrictMode setup-cleanup-setup leaves exactly the second request active', () => {
  const scope = new CosmosRequestScope()
  const first = scope.begin('/resource', controller())
  scope.reset()
  const second = scope.begin('/resource', controller())
  assert.notEqual(first.generation, second.generation)
  assert.equal(scope.isCurrent(first, '/resource'), false)
  assert.equal(scope.isCurrent(second, '/resource'), true)
})
