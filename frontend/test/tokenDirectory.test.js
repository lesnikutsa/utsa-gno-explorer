import test from 'node:test'
import assert from 'node:assert/strict'
import { sortTokenDirectoryItems } from '../src/utils/tokenDirectory.js'

const items = [
  { path: 'gno.land/r/z', direct_call_count: 2, last_activity_at: null },
  { path: 'gno.land/r/b', direct_call_count: 9, last_activity_at: '2026-01-02T00:00:00Z' },
  { path: 'gno.land/r/a', direct_call_count: 9, last_activity_at: '2026-01-02T00:00:00Z' },
  { path: 'gno.land/r/c', direct_call_count: 1, last_activity_at: '2026-01-01T00:00:00Z' },
]

test('direct calls sort numerically with canonical path ties without mutation', () => {
  const original = [...items]
  assert.deepEqual(sortTokenDirectoryItems(items, 'direct_call_count', 'descending').map((item) => item.path),
    ['gno.land/r/a', 'gno.land/r/b', 'gno.land/r/z', 'gno.land/r/c'])
  assert.deepEqual(sortTokenDirectoryItems(items, 'direct_call_count', 'ascending').map((item) => item.path),
    ['gno.land/r/c', 'gno.land/r/z', 'gno.land/r/a', 'gno.land/r/b'])
  assert.deepEqual(items, original)
})

test('last activity sorts chronologically with null last and canonical path ties', () => {
  assert.deepEqual(sortTokenDirectoryItems(items, 'last_activity_at', 'descending').map((item) => item.path),
    ['gno.land/r/a', 'gno.land/r/b', 'gno.land/r/c', 'gno.land/r/z'])
  assert.deepEqual(sortTokenDirectoryItems(items, 'last_activity_at', 'ascending').map((item) => item.path),
    ['gno.land/r/c', 'gno.land/r/a', 'gno.land/r/b', 'gno.land/r/z'])
})
