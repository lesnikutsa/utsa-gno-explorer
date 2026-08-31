const SECOND = 1000

export function countdownParts(estimatedAt, now = Date.now()) {
  const target = Date.parse(estimatedAt)
  if (!Number.isFinite(target) || !Number.isFinite(now)) return null
  const totalSeconds = Math.max(0, Math.floor((target - now) / SECOND))
  return {
    days: Math.floor(totalSeconds / 86400),
    hours: Math.floor(totalSeconds % 86400 / 3600),
    minutes: Math.floor(totalSeconds % 3600 / 60),
    seconds: totalSeconds % 60,
    totalSeconds,
  }
}

export function formatAverageBlockTime(value) {
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `${new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: 3 }).format(value)} s`
}

export function formatEstimatedArrival(value) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hour12: false, timeZone: 'UTC',
  }).format(date).replace(',', ' ·') + ' UTC'
}
