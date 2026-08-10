import { useCallback, useEffect, useRef, useState } from 'react'
import { getTopRealmApplications } from '../services/api'
import { REALMS_BACKGROUND_REQUEST_TIMEOUT_MS } from './useRealmsAutoRefresh'

export const APPLICATIONS_LIMIT = 3
export const APPLICATION_WINDOWS = ['24h', '7d', '30d']
export const DEFAULT_APPLICATION_WINDOW = '24h'

const isValidItem = (item) => item !== null
  && typeof item === 'object'
  && typeof item.namespace_key === 'string'
  && item.namespace_key.trim() !== ''
  && (item.application === null || typeof item.application === 'object')

export function useRealmApplications() {
  const [items, setItems] = useState([])
  const [source, setSource] = useState(null)
  const [window, setWindow] = useState(DEFAULT_APPLICATION_WINDOW)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [windowUnavailable, setWindowUnavailable] = useState(false)
  const [snapshotMissing, setSnapshotMissing] = useState(false)
  const mounted = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const foregroundActive = useRef(false)
  const hasItems = useRef(false)
  const currentWindow = useRef(DEFAULT_APPLICATION_WINDOW)

  const applyResponse = useCallback((response) => {
    if (response === null || typeof response !== 'object' || !Array.isArray(response.items)) return false
    const nextItems = response.items.filter(isValidItem).slice(0, APPLICATIONS_LIMIT)
    setItems(nextItems)
    hasItems.current = nextItems.length > 0
    setSource(response.source !== null && typeof response.source === 'object' ? response.source : null)
    return true
  }, [])

  const load = useCallback(async (selectedWindow = currentWindow.current) => {
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    foregroundActive.current = true
    setLoading(true)
    setError(false)
    setWindowUnavailable(false)
    setSnapshotMissing(false)
    setItems([])
    try {
      const response = await getTopRealmApplications({ limit: APPLICATIONS_LIMIT, window: selectedWindow, signal: activeController.signal })
      if (!mounted.current || id !== requestId.current) return
      if (!applyResponse(response)) setError(true)
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current || requestError?.name === 'AbortError') return
      if (requestError?.status === 404) setSnapshotMissing(true)
      else if (requestError?.status === 409) setWindowUnavailable(true)
      else setError(true)
    } finally {
      if (id === requestId.current) foregroundActive.current = false
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [applyResponse])

  const selectWindow = useCallback((nextWindow) => {
    if (!APPLICATION_WINDOWS.includes(nextWindow) || nextWindow === currentWindow.current) return
    currentWindow.current = nextWindow
    setWindow(nextWindow)
    load(nextWindow)
  }, [load])

  const refreshInBackground = useCallback(async () => {
    if (foregroundActive.current || controller.current?.background) return
    const activeController = new AbortController()
    activeController.background = true
    controller.current = activeController
    const id = ++requestId.current
    let timedOut = false
    const requestTimeout = globalThis.window.setTimeout(() => { timedOut = true; activeController.abort() }, REALMS_BACKGROUND_REQUEST_TIMEOUT_MS)
    try {
      const response = await getTopRealmApplications({ limit: APPLICATIONS_LIMIT, window: currentWindow.current, signal: activeController.signal })
      if (!mounted.current || id !== requestId.current) return
      if (!applyResponse(response)) return
      setError(false)
      setWindowUnavailable(false)
      setSnapshotMissing(false)
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current) return
      if (requestError?.name === 'AbortError' && !timedOut) return
      if (!hasItems.current) return
    } finally {
      globalThis.window.clearTimeout(requestTimeout)
      if (id === requestId.current) controller.current = null
    }
  }, [applyResponse])

  useEffect(() => {
    mounted.current = true
    load(DEFAULT_APPLICATION_WINDOW)
    return () => { mounted.current = false; requestId.current += 1; controller.current?.abort() }
  }, [load])

  return { items, source, window, loading, error, windowUnavailable, snapshotMissing,
    selectWindow, retry: () => load(currentWindow.current), refreshInBackground }
}
