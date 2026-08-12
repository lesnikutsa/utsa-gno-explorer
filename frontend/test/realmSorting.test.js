import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { sortRealmItems } from '../src/utils/realm.js'

const rows = () => [
  { path: 'equal-a', kind: 'realm', call_count: 50, success_rate: 0.5, last_activity_at: '2026-08-12T10:00:00Z' },
  { path: 'package', kind: 'package', call_count: null, success_rate: null, last_activity_at: '2099-01-01T00:00:00Z' },
  { path: 'high', kind: 'realm', call_count: 100, success_rate: 1, last_activity_at: '2026-08-12T20:00:00Z' },
  { path: 'zero', kind: 'realm', call_count: 0, success_rate: 0, last_activity_at: '2026-08-12T12:00:00+03:00' },
  { path: 'missing', kind: 'realm', call_count: null, success_rate: undefined, last_activity_at: null },
  { path: 'equal-b', kind: 'realm', call_count: 50, success_rate: 0.5, last_activity_at: '2026-08-12T10:00:00Z' },
]

const paths = (items) => items.map((item) => item.path)

test('only Direct Calls, Success Rate, and Last Activity use the DataTable sorting contract', async () => {
  const source = await readFile(new URL('../src/pages/Realms.jsx', import.meta.url), 'utf8')
  assert.match(source, /label: 'Direct Calls'[^\n]+sortable: true/)
  assert.match(source, /label: 'Success Rate'[^\n]+sortable: true/)
  assert.match(source, /label: 'Last Activity',\n\s+sortable: true/)
  assert.equal((source.match(/sortable: true/g) ?? []).length, 3)
  for (const label of ['Path', 'Type', 'Visibility']) {
    assert.doesNotMatch(source, new RegExp(`label: '${label}'[^\\n]+sortable: true`))
  }
  assert.match(source, /useState\(\{ key: 'last_activity_at', direction: 'descending' \}\)/)
  assert.match(source, /sortKey=\{sort\.key\} sortDirection=\{sort\.direction\} onSort=/)
  assert.equal((source.match(/defaultSortDirection: 'descending'/g) ?? []).length, 3)
})

test('initial Last Activity sort is chronological descending with missing values last', () => {
  assert.deepEqual(paths(sortRealmItems(rows(), 'last_activity_at', 'descending')), ['high', 'equal-a', 'equal-b', 'zero', 'package', 'missing'])
})

test('Last Activity toggles to chronological ascending and back to descending', () => {
  const items = rows()
  assert.deepEqual(paths(sortRealmItems(items, 'last_activity_at', 'ascending')), ['zero', 'equal-a', 'equal-b', 'high', 'package', 'missing'])
  assert.deepEqual(paths(sortRealmItems(items, 'last_activity_at', 'descending')), ['high', 'equal-a', 'equal-b', 'zero', 'package', 'missing'])
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

test('sorting keeps equal timestamps stable and does not mutate the original items array', () => {
  const items = rows()
  const original = [...items]

  const sorted = sortRealmItems(items, 'last_activity_at', 'descending')

  assert.notEqual(sorted, items)
  assert.deepEqual(items, original)
  assert.ok(sorted.indexOf(items[0]) < sorted.indexOf(items[5]))
  assert.ok(sorted.indexOf(items[1]) < sorted.indexOf(items[4]))
})
