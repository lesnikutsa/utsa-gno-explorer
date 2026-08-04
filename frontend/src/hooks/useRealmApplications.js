import { useCallback, useEffect, useRef, useState } from 'react'
import { getTopRealmNamespaces } from '../services/api'
import { REALMS_BACKGROUND_REQUEST_TIMEOUT_MS } from './useRealmsAutoRefresh'

export const APPLICATIONS_LIMIT = 3

const isValidItem = (item) => item !== null
  && typeof item === 'object'
  && item.application !== null
  && typeof item.application === 'object'
  && typeof item.application.display_name === 'string'
  && item.application.display_name.trim() !== ''
  && typeof item.namespace_key === 'string'
  && item.namespace_key.trim() !== ''

export function useRealmApplications() {
  const [items, setItems] = useState([])
  const [source, setSource] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [snapshotMissing, setSnapshotMissing] = useState(false)
  const mounted = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const foregroundActive = useRef(false)
  const hasItems = useRef(false)

  const load = useCallback(async () => {
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    foregroundActive.current = true
    setLoading(true)
    setError(false)
    setSnapshotMissing(false)

    try {
      const response = await getTopRealmNamespaces({
        limit: APPLICATIONS_LIMIT,
        scope: 'curated',
        signal: activeController.signal,
      })
      if (!mounted.current || id !== requestId.current) return
      if (response === null || typeof response !== 'object' || !Array.isArray(response.items)) {
        setError(true)
        return
      }
      const nextItems = response.items.filter(isValidItem).slice(0, APPLICATIONS_LIMIT)
      setItems(nextItems)
      hasItems.current = nextItems.length > 0
      setSource(response.source !== null && typeof response.source === 'object' ? response.source : null)
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current || requestError?.name === 'AbortError') return
      if (requestError?.status === 404) {
        setItems([])
        setSource(null)
        setSnapshotMissing(true)
      } else {
        setError(true)
      }
    } finally {
      if (id === requestId.current) foregroundActive.current = false
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

  const refreshInBackground = useCallback(async () => {
    if (foregroundActive.current || controller.current?.background) return
    const activeController = new AbortController()
    activeController.background = true
    controller.current = activeController
    const id = ++requestId.current
    let timedOut = false
    const requestTimeout = window.setTimeout(() => {
      timedOut = true
      activeController.abort()
    }, REALMS_BACKGROUND_REQUEST_TIMEOUT_MS)
    try {
      const response = await getTopRealmNamespaces({
        limit: APPLICATIONS_LIMIT,
        scope: 'curated',
        signal: activeController.signal,
      })
      if (!mounted.current || id !== requestId.current) return
      if (response === null || typeof response !== 'object' || !Array.isArray(response.items)) return
      const nextItems = response.items.filter(isValidItem).slice(0, APPLICATIONS_LIMIT)
      setItems(nextItems)
      hasItems.current = nextItems.length > 0
      setSource(response.source !== null && typeof response.source === 'object' ? response.source : null)
      setError(false)
      setSnapshotMissing(false)
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current) return
      if (requestError?.name === 'AbortError' && !timedOut) return
      if (!hasItems.current) return
    } finally {
      window.clearTimeout(requestTimeout)
      if (id === requestId.current) controller.current = null
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    load()
    return () => {
      mounted.current = false
      requestId.current += 1
      controller.current?.abort()
    }
  }, [load])

  return { items, source, loading, error, snapshotMissing, retry: load, refreshInBackground }
}
