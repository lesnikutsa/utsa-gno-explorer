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

test('total supply compares exact human units across decimals and unsafe integers', () => {
  const tokens = [
    { path: 'gno.land/r/one', decimals: 6 },
    { path: 'gno.land/r/two', decimals: 0 },
    { path: 'gno.land/r/huge', decimals: 18 },
  ]
  const supplies = {
    'gno.land/r/one': { available: true, raw_total_supply: '1000000' },
    'gno.land/r/two': { available: true, raw_total_supply: '200' },
    'gno.land/r/huge': { available: true, raw_total_supply: '900719925474099312345678901234567890' },
  }
  const tokensBefore = structuredClone(tokens)
  const suppliesBefore = structuredClone(supplies)
  assert.deepEqual(sortTokenDirectoryItems(tokens, 'total_supply', 'descending', supplies).map((item) => item.path),
    ['gno.land/r/huge', 'gno.land/r/two', 'gno.land/r/one'])
  assert.deepEqual(sortTokenDirectoryItems(tokens, 'total_supply', 'ascending', supplies).map((item) => item.path),
    ['gno.land/r/one', 'gno.land/r/two', 'gno.land/r/huge'])
  assert.deepEqual(tokens, tokensBefore)
  assert.deepEqual(supplies, suppliesBefore)
})

test('equal and unavailable supplies use canonical paths with unavailable last both ways', () => {
  const tokens = [
    { path: 'gno.land/r/missing-b', decimals: 6 },
    { path: 'gno.land/r/equal-b', decimals: 0 },
    { path: 'gno.land/r/equal-a', decimals: 6 },
    { path: 'gno.land/r/missing-a', decimals: 6 },
  ]
  const supplies = {
    'gno.land/r/missing-b': { available: false },
    'gno.land/r/equal-b': { available: true, raw_total_supply: '1' },
    'gno.land/r/equal-a': { available: true, raw_total_supply: '1000000' },
    'gno.land/r/missing-a': { available: false },
  }
  const expected = ['gno.land/r/equal-a', 'gno.land/r/equal-b', 'gno.land/r/missing-a', 'gno.land/r/missing-b']
  assert.deepEqual(sortTokenDirectoryItems(tokens, 'total_supply', 'descending', supplies).map((item) => item.path), expected)
  assert.deepEqual(sortTokenDirectoryItems(tokens, 'total_supply', 'ascending', supplies).map((item) => item.path), expected)
})
