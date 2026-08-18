import test from 'node:test'
import assert from 'node:assert/strict'
import { applicationPresentation, compactNamespace } from '../src/utils/namespaceDisplay.js'

test('namespace display preserves short values and middle-truncates long values', () => {
  assert.equal(compactNamespace('gnoland'), 'gnoland')
  assert.equal(compactNamespace('g17cjym5e9hhws46lt6329pv2gtx2ay0503hgems'), 'g17cjym5…03hgems')
  assert.equal(compactNamespace(null), '')
})

test('fallback retains the full namespace title while curated names stay unchanged', () => {
  const namespace = 'g17cjym5e9hhws46lt6329pv2gtx2ay0503hgems'
  assert.deepEqual(applicationPresentation({ namespace_key: namespace }),
    { label: 'g17cjym5…03hgems', title: namespace })
  assert.deepEqual(applicationPresentation({ namespace_key: namespace,
    application: { display_name: 'A Very Long Curated Application Name' } }),
  { label: 'A Very Long Curated Application Name', title: undefined })
})
