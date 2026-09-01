const SECOND = 1000

const INTEGER_HEIGHT = /^[1-9]\d*$/

export function futureHeightValues(height, currentHeight) {
  if (typeof height !== 'string' || !INTEGER_HEIGHT.test(height)
      || !Number.isSafeInteger(currentHeight) || currentHeight < 1) {
    return { height: '—', remaining: '—' }
  }
  try {
    const requested = BigInt(height)
    const current = BigInt(currentHeight)
    if (requested <= current) return { height: requested.toLocaleString('en-US'), remaining: '—' }
    return {
      height: requested.toLocaleString('en-US'),
      remaining: (requested - current).toLocaleString('en-US'),
    }
  } catch {
    return { height: '—', remaining: '—' }
  }
}

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
