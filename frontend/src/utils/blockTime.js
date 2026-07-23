export function formatAverageBlockTime(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '—'
  if (value < 10) return `${value.toFixed(2)}s`
  if (value < 60) return `${value.toFixed(1)}s`

  const totalSeconds = Math.round(value)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`
}
