import test from 'node:test'
import assert from 'node:assert/strict'
import { groupNftCollections, nftCollectionCountLabel, sortNftCollectionGroups } from '../src/utils/nftCollections.js'

const item = (path, name = 'Collection', symbol = 'COL', overrides = {}) => ({
  path, name, symbol, direct_call_count: 1, last_activity_at: '2026-01-01T00:00:00Z', rpc_visible: true,
  namespace_key: path.split('/').at(-2), application: { category: 'Namespace' }, ...overrides,
})

test('groups only exact name and symbol identities and leaves singles alone', () => {
  const groups = groupNftCollections([
    item('r/a/1'), item('r/a/2'), item('r/a/3', 'Collection', 'OTHER'),
    item('r/a/4', 'Other', 'COL'), item('r/a/5', 'collection', 'COL'),
  ])
  assert.equal(groups.filter((group) => group.rowType === 'family').length, 1)
  assert.deepEqual(groups.find((group) => group.rowType === 'family').members.map(({ path }) => path), ['r/a/1', 'r/a/2'])
  assert.equal(groups.filter((group) => group.rowType === 'single').length, 3)
  assert.equal(groupNftCollections([item('r/only')])[0].rowType, 'single')
})

test('calculates family aggregates, application state, and deterministic child order', () => {
  const family = groupNftCollections([
    item('r/z/2', 'Same', 'S', { direct_call_count: 4, last_activity_at: '2026-02-01T00:00:00Z', rpc_visible: false }),
    item('r/a/1', 'Same', 'S', { direct_call_count: 3, last_activity_at: '2026-03-01T00:00:00Z', namespace_key: 'a' }),
  ])[0]
  assert.equal(family.direct_call_count, 7)
  assert.equal(family.last_activity_at, '2026-03-01T00:00:00Z')
  assert.equal(family.visibility, 'Mixed')
  assert.equal(family.applicationMode, 'multiple')
  assert.equal(family.namespaceCount, 2)
  assert.deepEqual(family.members.map(({ path }) => path), ['r/a/1', 'r/z/2'])
  assert.equal(groupNftCollections([item('a'), item('b')])[0].visibility, 'Visible')
  assert.equal(groupNftCollections([item('a'), item('b')])[0].applicationMode, 'single')
  assert.equal(groupNftCollections([item('a', 'H', 'H', { rpc_visible: false }), item('b', 'H', 'H', { rpc_visible: false })])[0].visibility, 'Historical')
})

test('sorts top-level collections, calls, and activity in either direction', () => {
  const groups = groupNftCollections([
    item('r/b', 'Beta', 'B', { direct_call_count: 2, last_activity_at: '2026-02-01T00:00:00Z' }),
    item('r/a', 'Alpha', 'A', { direct_call_count: 8, last_activity_at: '2026-01-01T00:00:00Z' }),
  ])
  assert.deepEqual(sortNftCollectionGroups(groups, 'collection', 'ascending').map(({ name }) => name), ['Alpha', 'Beta'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'collection', 'descending').map(({ name }) => name), ['Beta', 'Alpha'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'direct_call_count', 'descending').map(({ name }) => name), ['Alpha', 'Beta'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'last_activity_at', 'descending').map(({ name }) => name), ['Beta', 'Alpha'])
})

test('qualifies family count wording when another NFT page is proven', () => {
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 0, canLoadOlder: false }), '17 Realm collections')
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 0, canLoadOlder: true }), '17 Realm collections on this page')
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 1, canLoadOlder: false }), '17 Realm collections on this page')
})
