export function formatDistributionCount(value) {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value >= 0
    ? value.toLocaleString()
    : '—'
}

export function formatDistributionPercent(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) return '—'
  return `${Number(value.toFixed(2))}%`
}

export function formatDistributionAsn(value) {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value > 0
    ? `AS${value}`
    : ''
}

export function validDistributionTimestamp(value) {
  return typeof value === 'string' && value.length > 0 && Number.isFinite(Date.parse(value)) ? value : ''
}
