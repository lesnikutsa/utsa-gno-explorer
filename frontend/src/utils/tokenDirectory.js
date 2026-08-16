const canonicalPath = (item) => typeof item?.path === 'string' ? item.path : ''

const exactSupply = (item, supplies) => {
  const supply = supplies?.[canonicalPath(item)]
  if (supply?.available !== true || !/^\d+$/.test(supply.raw_total_supply ?? '')
      || typeof item?.decimals !== 'number' || item.decimals < 0 || item.decimals % 1 !== 0) return null
  return { raw: BigInt(supply.raw_total_supply), decimals: BigInt(item.decimals) }
}

export function sortTokenDirectoryItems(items, sortKey, sortDirection, supplies = {}) {
  if (!Array.isArray(items) || !sortKey) return items
  const direction = sortDirection === 'ascending' ? 1 : -1
  const value = (item) => {
    if (sortKey === 'direct_call_count') return Number.isFinite(item?.direct_call_count) ? item.direct_call_count : null
    if (sortKey === 'last_activity_at') {
      const timestamp = Date.parse(item?.last_activity_at)
      return Number.isFinite(timestamp) ? timestamp : null
    }
    if (sortKey === 'total_supply') return exactSupply(item, supplies)
    return null
  }
  return [...items].sort((left, right) => {
    const leftValue = value(left)
    const rightValue = value(right)
    if (leftValue === null && rightValue !== null) return 1
    if (leftValue !== null && rightValue === null) return -1
    if (sortKey === 'total_supply' && leftValue !== null && rightValue !== null) {
      const leftScaled = leftValue.raw * (10n ** rightValue.decimals)
      const rightScaled = rightValue.raw * (10n ** leftValue.decimals)
      if (leftScaled !== rightScaled) return (leftScaled < rightScaled ? -1 : 1) * direction
    } else if (leftValue !== rightValue) return (leftValue - rightValue) * direction
    const leftPath = canonicalPath(left)
    const rightPath = canonicalPath(right)
    return leftPath < rightPath ? -1 : leftPath > rightPath ? 1 : 0
  })
}
