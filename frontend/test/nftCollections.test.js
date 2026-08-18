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

test('calculates family aggregates and application state', () => {
  const family = groupNftCollections([
    item('r/z/2', 'Same', 'S', { direct_call_count: 4, last_activity_at: '2026-02-01T00:00:00Z', rpc_visible: false }),
    item('r/a/1', 'Same', 'S', { direct_call_count: 3, last_activity_at: '2026-03-01T00:00:00Z', namespace_key: 'a' }),
  ], {}, {
    'r/z/2': { available: true, last_action: 'transfer', last_action_height: 20, last_action_tx_index: 0, last_action_message_index: 1 },
    'r/a/1': { available: true, last_action: 'mint', last_action_height: 30, last_action_tx_index: 0, last_action_message_index: 0 },
  })[0]
  assert.equal(family.direct_call_count, 7)
  assert.equal(family.last_activity_at, '2026-03-01T00:00:00Z')
  assert.equal(family.visibility, 'Mixed')
  assert.equal(family.applicationMode, 'multiple')
  assert.equal(family.namespaceCount, 2)
  assert.equal(family.nft_activity.last_action, 'mint')
  assert.equal(family.nft_activity.last_action_height, 30)
  assert.equal(family.members.find(({ path }) => path === 'r/z/2').nft_activity.last_action, 'transfer')
  assert.deepEqual(family.members.map(({ path }) => path), ['r/a/1', 'r/z/2'])
  assert.equal(groupNftCollections([item('a'), item('b')])[0].visibility, 'Visible')
  assert.equal(groupNftCollections([item('a'), item('b')])[0].applicationMode, 'single')
  assert.equal(groupNftCollections([item('a', 'H', 'H', { rpc_visible: false }), item('b', 'H', 'H', { rpc_visible: false })])[0].visibility, 'Historical')
})

test('orders family children by activity, calls, then canonical path', () => {
  const family = groupNftCollections([
    item('r/family/g1', 'Same', 'S', { direct_call_count: 999, last_activity_at: null }),
    item('r/family/g10', 'Same', 'S', { direct_call_count: 3, last_activity_at: '2026-03-01T00:00:00Z' }),
    item('r/family/g2', 'Same', 'S', { direct_call_count: 8, last_activity_at: '2026-03-01T00:00:00Z' }),
    item('r/family/a', 'Same', 'S', { direct_call_count: 8, last_activity_at: '2026-03-01T00:00:00Z' }),
    item('r/family/newest', 'Same', 'S', { direct_call_count: null, last_activity_at: '2026-04-01T00:00:00Z' }),
    item('r/family/missing-calls', 'Same', 'S', { direct_call_count: null, last_activity_at: '2026-03-01T00:00:00Z' }),
    item('r/family/invalid', 'Same', 'S', { direct_call_count: 1000, last_activity_at: 'not-a-date' }),
  ])[0]
  assert.deepEqual(family.members.map(({ path }) => path), [
    'r/family/newest',
    'r/family/a',
    'r/family/g2',
    'r/family/g10',
    'r/family/missing-calls',
    'r/family/invalid',
    'r/family/g1',
  ])
})

test('sorts top-level collections, NFT actions, and activity in either direction', () => {
  const groups = groupNftCollections([
    item('r/b', 'Beta', 'B', { direct_call_count: 2, last_activity_at: '2026-02-01T00:00:00Z' }),
    item('r/a', 'Alpha', 'A', { direct_call_count: 8, last_activity_at: '2026-01-01T00:00:00Z' }),
  ], {}, {
    'r/b': { available: true, last_action: 'transfer', last_action_height: 2, last_action_tx_index: 0, last_action_message_index: 0 },
    'r/a': { available: true, last_action: 'mint', last_action_height: 8, last_action_tx_index: 0, last_action_message_index: 0 },
  })
  assert.deepEqual(sortNftCollectionGroups(groups, 'collection', 'ascending').map(({ name }) => name), ['Alpha', 'Beta'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'collection', 'descending').map(({ name }) => name), ['Beta', 'Alpha'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'nft_activity', 'descending').map(({ name }) => name), ['Alpha', 'Beta'])
  assert.deepEqual(sortNftCollectionGroups(groups, 'last_activity_at', 'descending').map(({ name }) => name), ['Beta', 'Alpha'])
})

test('qualifies family count wording when another NFT page is proven', () => {
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 0, canLoadOlder: false }), '17 Realm collections')
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 0, canLoadOlder: true }), '17 Realm collections on this page')
  assert.equal(nftCollectionCountLabel(17, { pageIndex: 1, canLoadOlder: false }), '17 Realm collections on this page')
})
