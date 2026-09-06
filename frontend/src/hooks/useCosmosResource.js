import { useCallback, useEffect, useRef, useState } from 'react'
import { CosmosRequestScope } from '../utils/cosmosRequestScope'
import { cosmosApiNetworkId, rewriteCosmosApiUrl, subscribeCosmosEndpointProvider } from '../utils/cosmosEndpointProvider'

export function useCosmosResource(url, interval = 5000) {
  const networkId = cosmosApiNetworkId(url)
  const [, setProviderVersion] = useState(0)
  const requestUrl = rewriteCosmosApiUrl(url)
  const [state, setState] = useState({ url: requestUrl, data: null, loading: true, error: null, stale: false })
  const scope = useRef(new CosmosRequestScope())

  useEffect(() => subscribeCosmosEndpointProvider((changedNetworkId) => {
    if (changedNetworkId === networkId) setProviderVersion((value) => value + 1)
  }), [networkId])

  const load = useCallback(async (background = false) => {
    if (scope.current.current || (background && document.hidden)) return
    const controller = new AbortController()
    const request = scope.current.begin(requestUrl, controller)
    if (!request) return
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    try {
      const response = await fetch(requestUrl, { signal: controller.signal, headers: { Accept: 'application/json' } })
      if (!response.ok) throw new Error(`Request failed (${response.status})`)
      const data = await response.json()
      if (scope.current.isCurrent(request, requestUrl)) setState((current) => {
        if (background && Array.isArray(data.blocks) && Array.isArray(current.data?.blocks)) {
          const newest = data.blocks[0]?.height
          const previous = current.data.blocks[0]?.height
          if (Number.isInteger(newest) && Number.isInteger(previous) && newest >= previous && newest - previous <= 10) {
            const merged = [...data.blocks, ...current.data.blocks]
            data.blocks = [...new Map(merged.map((block) => [block.height, block])).values()]
              .sort((left, right) => right.height - left.height).slice(0, 20)
          }
        }
        return { url: requestUrl, data, loading: false, error: null, stale: false,
          ...(interval ? { nextRefreshAt: Date.now() + interval } : {}) }
      })
    } catch (error) {
      if (scope.current.isCurrent(request, requestUrl)) setState((current) => ({ ...current, url: requestUrl, loading: false, error: error.name === 'AbortError' ? 'Request timed out' : error.message, stale: Boolean(current.data) }))
    } finally {
      window.clearTimeout(timeout)
      scope.current.finish(request)
    }
  }, [requestUrl, interval])
  useEffect(() => {
    let active = true
    setState({ url: requestUrl, data: null, loading: true, error: null, stale: false })
    load(false)
    const timer = interval ? window.setInterval(() => { if (active) load(true) }, interval) : null
    const visible = () => { if (!document.hidden) load(true) }
    if (interval) document.addEventListener('visibilitychange', visible)
    return () => { active = false; scope.current.reset(); if (timer) window.clearInterval(timer); if (interval) document.removeEventListener('visibilitychange', visible) }
  }, [load, interval, requestUrl])
  return state.url === requestUrl
    ? { ...state, refresh: () => load(false) }
    : { url: requestUrl, data: null, loading: true, error: null, stale: false, refresh: () => load(false) }
}
