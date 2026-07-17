export function relativeTime(value, now = Date.now()) {
  if (!value) return '—'

  const timestamp = value instanceof Date ? value.getTime() : new Date(value).getTime()
  if (Number.isNaN(timestamp)) return '—'

  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000))
  if (seconds < 60) return `${seconds}s ago`

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}
