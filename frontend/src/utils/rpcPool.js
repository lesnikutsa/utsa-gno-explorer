export const endpointHostname = (url) => {
  if (typeof url !== 'string' || !url) return 'Unknown endpoint'
  try { return new URL(url).hostname || url } catch { return url }
}

export const normalizeRpcPool = (pool) => {
  if (!pool || !Number.isInteger(pool.total) || !Number.isInteger(pool.available) || !Array.isArray(pool.endpoints)) return null
  if (pool.total < 0 || pool.total > 32 || pool.available < 0 || pool.available > pool.total || pool.endpoints.length !== pool.total) return null
  const states = new Set(['healthy', 'catching_up', 'stale', 'wrong_chain', 'unavailable', 'unknown'])
  const validEndpoint = (endpoint) => endpoint
    && typeof endpoint.url === 'string' && endpoint.url.length > 0
    && typeof endpoint.selected === 'boolean'
    && states.has(endpoint.state)
    && (endpoint.latency_ms === null || (Number.isInteger(endpoint.latency_ms) && endpoint.latency_ms >= 0 && endpoint.latency_ms <= 30000))
    && (endpoint.lag === null || (Number.isInteger(endpoint.lag) && endpoint.lag >= 0))
    && (endpoint.last_checked_at === null || typeof endpoint.last_checked_at === 'string')
  if (pool.endpoints.some((endpoint) => !validEndpoint(endpoint)) || pool.endpoints.filter((endpoint) => endpoint.selected).length > 1) return null
  return pool
}

export const hoverPopoverState = (open, pointerType) => pointerType === 'touch' ? open : true
export const togglePopoverState = (open) => !open

export const poolSummary = (pool) => {
  if (!pool || pool.total === 0) return { tone: 'neutral', label: 'RPC unavailable' }
  if (pool.available === pool.total) return { tone: 'success', label: `${pool.available}/${pool.total} available` }
  if (pool.available >= 2) return { tone: 'warning', label: 'Reduced redundancy' }
  if (pool.available === 1) return { tone: 'danger', label: 'At risk' }
  return { tone: 'danger', label: 'Unavailable' }
}

export const endpointStatus = (endpoint) => {
  if (endpoint.state === 'stale' && Number.isInteger(endpoint.lag) && endpoint.lag > 1) return `${endpoint.lag} blocks behind`
  return { healthy: 'Healthy', catching_up: 'Catching up', stale: 'Stale', wrong_chain: 'Wrong network', unavailable: 'Unavailable', unknown: 'Not checked' }[endpoint.state] || 'Not checked'
}
