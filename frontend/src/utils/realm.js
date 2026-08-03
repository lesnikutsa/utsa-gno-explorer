export function formatSuccessRate(value) {
  if (value === null || value === undefined || typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const percentage = Math.round(value * 1000) / 10
  return `${Number.isInteger(percentage) ? percentage.toFixed(0) : percentage.toFixed(1)}%`
}
