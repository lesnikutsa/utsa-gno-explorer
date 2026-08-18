import assert from 'node:assert/strict'
import test from 'node:test'

import { INTERNAL_NAVIGATION_EVENT, isInterceptableNavigation, navigateInternal } from '../src/utils/navigation.js'

const installWindow = (href = 'https://explorer.test/tokens') => {
  const location = new URL(href)
  const pushes = []
  const events = []
  const scrolls = []
  globalThis.window = {
    location,
    history: {
      pushState: (state, title, destination) => {
        pushes.push([state, title, destination])
        const next = new URL(destination, location.href)
        for (const key of ['href', 'pathname', 'search', 'hash']) location[key] = next[key]
      },
    },
    dispatchEvent: (event) => events.push(event.type),
    scrollTo: (...args) => scrolls.push(args),
  }
  return { events, location, pushes, scrolls }
}

const click = (overrides = {}) => ({
  defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
  ...overrides,
})

test('internal navigation pushes state, notifies routing, and scrolls to the top', () => {
  const browser = installWindow()
  assert.equal(navigateInternal('/blocks?limit=20#latest'), true)
  assert.deepEqual(browser.pushes, [[{}, '', '/blocks?limit=20#latest']])
  assert.deepEqual(browser.events, [INTERNAL_NAVIGATION_EVENT])
  assert.deepEqual(browser.scrolls, [[0, 0]])
})

test('current destination does not add a duplicate history entry', () => {
  const browser = installWindow('https://explorer.test/tokens?view=all#top')
  assert.equal(navigateInternal('/tokens?view=all#top'), false)
  assert.equal(browser.pushes.length, 0)
})

test('only an unmodified primary same-origin click is interceptable', () => {
  installWindow()
  assert.equal(isInterceptableNavigation(click(), '/blocks'), true)
  for (const modifier of ['metaKey', 'ctrlKey', 'shiftKey', 'altKey']) {
    assert.equal(isInterceptableNavigation(click({ [modifier]: true }), '/blocks'), false)
  }
  assert.equal(isInterceptableNavigation(click({ button: 1 }), '/blocks'), false)
  assert.equal(isInterceptableNavigation(click({ defaultPrevented: true }), '/blocks'), false)
  assert.equal(isInterceptableNavigation(click(), 'https://external.test/blocks'), false)
  assert.equal(isInterceptableNavigation(click(), '/blocks', '_blank'), false)
})
