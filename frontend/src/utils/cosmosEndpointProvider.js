const STORAGE_PREFIX = 'utsa.cosmos.endpoint-provider.'
const CHANGE_EVENT = 'utsa:cosmos-endpoint-provider-change'
const SAFE_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const NETWORK_PATH = /\/api\/networks\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\/|\?|$)/
const memorySelections = new Map()

const storage = () => {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

export const cosmosProviderAlias = (networkId, providerId) => {
  if (!SAFE_ID.test(networkId || '') || !SAFE_ID.test(providerId || '')) return null
  return `${networkId}-provider-${providerId}`
}

export const cosmosApiNetworkId = (url) => {
  if (typeof url !== 'string') return null
  return url.match(NETWORK_PATH)?.[1] || null
}

export const getCosmosEndpointProvider = (networkId) => {
  if (!SAFE_ID.test(networkId || '')) return 'auto'
  let value = memorySelections.get(networkId) ?? null
  try {
    const stored = storage()?.getItem(`${STORAGE_PREFIX}${networkId}`) ?? null
    if (stored !== null) value = stored
  } catch {
    // Keep the current tab's in-memory choice when persistent storage is disabled.
  }
  return value && SAFE_ID.test(value) ? value : 'auto'
}

export const setCosmosEndpointProvider = (networkId, providerId) => {
  if (!SAFE_ID.test(networkId || '')) return
  const selected = providerId === 'auto' ? 'auto' : (SAFE_ID.test(providerId || '') ? providerId : 'auto')
  if (selected === 'auto') memorySelections.delete(networkId)
  else memorySelections.set(networkId, selected)
  const target = storage()
  try {
    if (target) {
      if (selected === 'auto') target.removeItem(`${STORAGE_PREFIX}${networkId}`)
      else target.setItem(`${STORAGE_PREFIX}${networkId}`, selected)
    }
  } catch {
    // Browser storage can be disabled; the in-memory selection remains active in this tab.
  }
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    const EventCtor = typeof CustomEvent === 'function' ? CustomEvent : null
    if (EventCtor) window.dispatchEvent(new EventCtor(CHANGE_EVENT, { detail: { networkId, providerId: selected } }))
  }
}

export const rewriteCosmosApiUrl = (url) => {
  const networkId = cosmosApiNetworkId(url)
  if (!networkId || typeof url !== 'string') return url
  const prefix = `/api/networks/${networkId}`
  if (url.includes(`${prefix}/endpoint-status`) || url.includes(`${prefix}/market`)) return url
  const providerId = getCosmosEndpointProvider(networkId)
  if (providerId === 'auto') return url
  const alias = cosmosProviderAlias(networkId, providerId)
  if (!alias) return url
  return url.replace(prefix, `/api/networks/${alias}`)
}

export const subscribeCosmosEndpointProvider = (listener) => {
  if (typeof window === 'undefined' || typeof listener !== 'function') return () => {}
  const changed = (event) => listener(event?.detail?.networkId || null)
  const stored = (event) => {
    if (typeof event?.key !== 'string' || !event.key.startsWith(STORAGE_PREFIX)) return
    const networkId = event.key.slice(STORAGE_PREFIX.length) || null
    if (networkId && SAFE_ID.test(networkId)) {
      if (typeof event.newValue === 'string' && SAFE_ID.test(event.newValue)) memorySelections.set(networkId, event.newValue)
      else memorySelections.delete(networkId)
    }
    listener(networkId)
  }
  window.addEventListener(CHANGE_EVENT, changed)
  window.addEventListener('storage', stored)
  return () => {
    window.removeEventListener(CHANGE_EVENT, changed)
    window.removeEventListener('storage', stored)
  }
}
