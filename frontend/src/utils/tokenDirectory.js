const canonicalPath = (item) => typeof item?.path === 'string' ? item.path : ''

export function sortTokenDirectoryItems(items, sortKey, sortDirection) {
  if (!Array.isArray(items) || !sortKey) return items
  const direction = sortDirection === 'ascending' ? 1 : -1
  const value = (item) => {
    if (sortKey === 'direct_call_count') return Number.isFinite(item?.direct_call_count) ? item.direct_call_count : null
    if (sortKey === 'last_activity_at') {
      const timestamp = Date.parse(item?.last_activity_at)
      return Number.isFinite(timestamp) ? timestamp : null
    }
    return null
  }
  return [...items].sort((left, right) => {
    const leftValue = value(left)
    const rightValue = value(right)
    if (leftValue === null && rightValue !== null) return 1
    if (leftValue !== null && rightValue === null) return -1
    if (leftValue !== rightValue) return (leftValue - rightValue) * direction
    const leftPath = canonicalPath(left)
    const rightPath = canonicalPath(right)
    return leftPath < rightPath ? -1 : leftPath > rightPath ? 1 : 0
  })
}
