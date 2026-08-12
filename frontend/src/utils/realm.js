export function formatSuccessRate(value) {
  if (value === null || value === undefined || typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const percentage = Math.round(value * 1000) / 10
  return `${Number.isInteger(percentage) ? percentage.toFixed(0) : percentage.toFixed(1)}%`
}

export function sortRealmItems(items, sortKey, sortDirection) {
  if (!sortKey) return items

  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftValue = left.item.kind === 'realm' && Number.isFinite(left.item[sortKey]) ? left.item[sortKey] : null
      const rightValue = right.item.kind === 'realm' && Number.isFinite(right.item[sortKey]) ? right.item[sortKey] : null

      if (leftValue === null && rightValue === null) return left.index - right.index
      if (leftValue === null) return 1
      if (rightValue === null) return -1
      if (leftValue === rightValue) return left.index - right.index
      return sortDirection === 'ascending' ? leftValue - rightValue : rightValue - leftValue
    })
    .map(({ item }) => item)
}

export function realmDetailHref(path) {
  const params = new URLSearchParams()
  params.set('path', path)
  return `/realm?${params.toString()}`
}

export function isCanonicalRealmPath(path) {
  if (typeof path !== 'string') return false
  if (path.length < 1 || path.length > 256) return false
  if (path !== path.trim()) return false
  if (/\s/.test(path) || path.includes('?') || path.includes('#')) return false
  return /^gno\.land\/[rp]\/[!-.0-~]+(?:\/[!-.0-~]+)*$/.test(path)
}

export function decodeRealmDetailPath(search = window.location.search) {
  const params = new URLSearchParams(search)
  const path = params.get('path')
  return isCanonicalRealmPath(path) ? path : null
}
