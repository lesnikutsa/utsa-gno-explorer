import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { sortRealmItems } from '../src/utils/realm.js'

const rows = () => [
  { path: 'equal-a', kind: 'realm', call_count: 50, success_rate: 0.5 },
  { path: 'package', kind: 'package', call_count: null, success_rate: null },
  { path: 'high', kind: 'realm', call_count: 100, success_rate: 1 },
  { path: 'zero', kind: 'realm', call_count: 0, success_rate: 0 },
  { path: 'missing', kind: 'realm', call_count: null, success_rate: undefined },
  { path: 'equal-b', kind: 'realm', call_count: 50, success_rate: 0.5 },
]

const paths = (items) => items.map((item) => item.path)

test('only Direct Calls and Success Rate columns use the DataTable sorting contract', async () => {
  const source = await readFile(new URL('../src/pages/Realms.jsx', import.meta.url), 'utf8')
  const sortableLabels = [...source.matchAll(/label: '([^']+)'[^\n]+sortable: true/g)].map((match) => match[1])

  assert.deepEqual(sortableLabels, ['Direct Calls', 'Success Rate'])
  for (const label of ['Path', 'Type', 'Last Activity', 'Visibility']) {
    assert.doesNotMatch(source, new RegExp(`label: '${label}'[^\\n]+sortable: true`))
  }
  assert.match(source, /useState\(\{ key: null, direction: null \}\)/)
  assert.match(source, /sortKey=\{sort\.key\} sortDirection=\{sort\.direction\} onSort=/)
  assert.equal((source.match(/defaultSortDirection: 'descending'/g) ?? []).length, 2)
})

test('no active sort preserves the existing array and its exact order', () => {
  const items = rows()
  assert.equal(sortRealmItems(items, null, null), items)
  assert.deepEqual(paths(items), ['equal-a', 'package', 'high', 'zero', 'missing', 'equal-b'])
})

test('Direct Calls sorts numerically descending then ascending with missing values last', () => {
  const items = rows()
  assert.deepEqual(paths(sortRealmItems(items, 'call_count', 'descending')), ['high', 'equal-a', 'equal-b', 'zero', 'package', 'missing'])
  assert.deepEqual(paths(sortRealmItems(items, 'call_count', 'ascending')), ['zero', 'equal-a', 'equal-b', 'high', 'package', 'missing'])
})

test('Success Rate sorts numerically descending then ascending with missing values last', () => {
  const items = rows()
  assert.deepEqual(paths(sortRealmItems(items, 'success_rate', 'descending')), ['high', 'equal-a', 'equal-b', 'zero', 'package', 'missing'])
  assert.deepEqual(paths(sortRealmItems(items, 'success_rate', 'ascending')), ['zero', 'equal-a', 'equal-b', 'high', 'package', 'missing'])
})

test('sorting is stable and does not mutate the original items array', () => {
  const items = rows()
  const original = [...items]

  const sorted = sortRealmItems(items, 'call_count', 'descending')

  assert.notEqual(sorted, items)
  assert.deepEqual(items, original)
  assert.ok(sorted.indexOf(items[0]) < sorted.indexOf(items[5]))
  assert.ok(sorted.indexOf(items[1]) < sorted.indexOf(items[4]))
})
