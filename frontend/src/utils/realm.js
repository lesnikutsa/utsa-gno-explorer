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
  if (path.length < 1 || path.length > 256) return null
  if (path !== path.trim()) return null
  if (/\s/.test(path) || path.includes('?') || path.includes('#')) return null
  if (!/^gno\.land\/[rp]\/[!-.0-~]+(?:\/[!-.0-~]+)*$/.test(path)) return null
  return path
}
