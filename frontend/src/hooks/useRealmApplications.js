import { useCallback, useEffect, useRef, useState } from 'react'
import { getTopRealmNamespaces } from '../services/api'

export const APPLICATIONS_LIMIT = 5

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

  const load = useCallback(async () => {
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
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
      setItems(response.items.filter(isValidItem).slice(0, APPLICATIONS_LIMIT))
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
      if (mounted.current && id === requestId.current) setLoading(false)
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

  return { items, source, loading, error, snapshotMissing, retry: load }
}
