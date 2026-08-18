import { applicationPresentation } from './namespaceDisplay.js'

const lexicalCompare = (left, right) => left < right ? -1 : left > right ? 1 : 0
const canonicalPath = (item) => typeof item?.path === 'string' ? item.path : ''

export function nftCollectionGroupKey(item) {
  return JSON.stringify([item?.name ?? '', item?.symbol ?? ''])
}

const applicationKey = (item) => {
  const presentation = applicationPresentation(item)
  return JSON.stringify([presentation.label, presentation.title ?? '', item?.application?.category ?? 'Namespace'])
}

export function nftCollectionCountLabel(count, paginationState = {}) {
  const suffix = paginationState.pageIndex > 0 || paginationState.canLoadOlder === true ? ' on this page' : ''
  return `${count} Realm collections${suffix}`
}

export function groupNftCollections(items, paginationState = {}) {
  const buckets = new Map()
  for (const item of Array.isArray(items) ? items : []) {
    const key = nftCollectionGroupKey(item)
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(item)
  }

  return [...buckets.entries()].map(([groupKey, bucket]) => {
    const members = [...bucket].sort((left, right) => lexicalCompare(canonicalPath(left), canonicalPath(right)))
    if (members.length === 1) return { ...members[0], rowType: 'single', groupKey, members }

    const validActivity = members.map((item) => ({ value: item.last_activity_at, timestamp: Date.parse(item.last_activity_at) }))
      .filter((activity) => Number.isFinite(activity.timestamp))
      .sort((left, right) => right.timestamp - left.timestamp)[0]
    const applicationKeys = new Set(members.map(applicationKey))
    const namespaces = new Set(members.map((item) => item?.namespace_key ?? ''))
    const allVisible = members.every((item) => item.rpc_visible === true)
    const allHistorical = members.every((item) => item.rpc_visible === false)
    return {
      rowType: 'family', groupKey, name: members[0].name, symbol: members[0].symbol, members,
      path: canonicalPath(members[0]),
      direct_call_count: members.reduce((sum, item) => sum + (Number.isFinite(item.direct_call_count) ? item.direct_call_count : 0), 0),
      last_activity_at: validActivity?.value ?? null,
      visibility: allVisible ? 'Visible' : allHistorical ? 'Historical' : 'Mixed',
      applicationMode: applicationKeys.size === 1 ? 'single' : 'multiple',
      applicationItem: members[0], namespaceCount: namespaces.size,
      collectionCountLabel: nftCollectionCountLabel(members.length, paginationState),
    }
  })
}

export function sortNftCollectionGroups(groups, sortKey, sortDirection) {
  const direction = sortDirection === 'ascending' ? 1 : -1
  return [...groups].sort((left, right) => {
    let comparison = 0
    if (sortKey === 'collection') {
      comparison = lexicalCompare(left.name ?? '', right.name ?? '')
      if (comparison === 0) comparison = lexicalCompare(left.symbol ?? '', right.symbol ?? '')
      if (comparison === 0) comparison = lexicalCompare(left.rowType === 'family' ? left.groupKey : canonicalPath(left), right.rowType === 'family' ? right.groupKey : canonicalPath(right))
    } else if (sortKey === 'direct_call_count') {
      const leftCalls = Number.isFinite(left.direct_call_count) ? left.direct_call_count : null
      const rightCalls = Number.isFinite(right.direct_call_count) ? right.direct_call_count : null
      if (leftCalls === null && rightCalls !== null) return 1
      if (leftCalls !== null && rightCalls === null) return -1
      comparison = leftCalls - rightCalls
    } else if (sortKey === 'last_activity_at') {
      const leftTime = Date.parse(left.last_activity_at)
      const rightTime = Date.parse(right.last_activity_at)
      if (!Number.isFinite(leftTime) && Number.isFinite(rightTime)) return 1
      if (Number.isFinite(leftTime) && !Number.isFinite(rightTime)) return -1
      comparison = Number.isFinite(leftTime) ? leftTime - rightTime : 0
    }
    if (comparison !== 0) return comparison < 0 ? -direction : direction
    return lexicalCompare(left.rowType === 'family' ? left.groupKey : canonicalPath(left), right.rowType === 'family' ? right.groupKey : canonicalPath(right))
  })
}

export function flattenNftCollectionGroups(groups, expandedGroupKeys) {
  return groups.flatMap((group) => group.rowType === 'family' && expandedGroupKeys.has(group.groupKey)
    ? [group, ...group.members.map((member) => ({ ...member, rowType: 'family-child', parentGroupKey: group.groupKey }))]
    : [group])
}
