export function formatSuccessRate(value) {
  if (value === null || value === undefined || typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const percentage = Math.round(value * 1000) / 10
  return `${Number.isInteger(percentage) ? percentage.toFixed(0) : percentage.toFixed(1)}%`
}

export function realmDetailHref(path) {
  const params = new URLSearchParams()
  params.set('path', path)
  return `/realm?${params.toString()}`
}

export function decodeRealmDetailPath(search = window.location.search) {
  const params = new URLSearchParams(search)
  const path = params.get('path')
  if (typeof path !== 'string') return null
  const trimmed = path.trim()
  if (!/^gno\.land\/(r|p)\/[A-Za-z0-9._~/-]+$/.test(trimmed)) return null
  return trimmed
}
