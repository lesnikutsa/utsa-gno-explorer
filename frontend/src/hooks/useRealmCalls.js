import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmCalls } from '../services/api'

export const REALM_CALLS_PAGE_SIZE = 25
const callKey = (item) => `${item.block_height}:${item.tx_index}:${item.message_index}`
const hasCursor = (pagination) => pagination?.next_before_height != null && pagination?.next_before_tx_index != null && pagination?.next_before_message_index != null

export function useRealmCalls(path) {
  const [items, setItems] = useState([])
  const [pagination, setPagination] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState(false)
  const [olderError, setOlderError] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const activeRef = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)

  const load = useCallback((cursor = null) => {
    if (!path || activeRef.current) return
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    const older = cursor !== null
    if (older) {
      activeRef.current = true
      setLoadingOlder(true)
      setOlderError(false)
    } else {
      activeRef.current = true
      setLoading(true)
      setItems([])
      setPagination(null)
      setError(false)
      setOlderError(false)
      setUnavailable(false)
    }
    getRealmCalls({
      path,
      limit: REALM_CALLS_PAGE_SIZE,
      beforeHeight: cursor?.height,
      beforeTxIndex: cursor?.txIndex,
      beforeMessageIndex: cursor?.messageIndex,
      signal: activeController.signal,
    }).then((response) => {
      if (id !== requestId.current || activeController.signal.aborted) return
      setPagination(response.pagination ?? null)
      const rows = (response.items ?? []).slice(0, REALM_CALLS_PAGE_SIZE)
      setItems((current) => {
        if (!older) return rows
        const seen = new Set(current.map(callKey))
        return [...current, ...rows.filter((row) => !seen.has(callKey(row)))]
      })
      setError(false)
      setOlderError(false)
      setUnavailable(false)
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      if (requestError?.status === 409) setUnavailable(true)
      else if (older) setOlderError(true)
      else setError(true)
    }).finally(() => {
      if (id !== requestId.current) return
      setLoading(false)
      setLoadingOlder(false)
      activeRef.current = false
    })
  }, [path])

  const retry = useCallback(() => load(null), [load])
  const loadOlder = useCallback(() => {
    if (activeRef.current || !hasCursor(pagination)) return
    load({ height: pagination.next_before_height, txIndex: pagination.next_before_tx_index, messageIndex: pagination.next_before_message_index })
  }, [load, pagination])

  useEffect(() => {
    controller.current?.abort()
    requestId.current += 1
    activeRef.current = false
    setItems([])
    setPagination(null)
    setError(false)
    setOlderError(false)
    setUnavailable(false)
    if (path) load(null)
    return () => {
      requestId.current += 1
      controller.current?.abort()
    }
  }, [load, path])

  return { items, pagination, loading, loadingOlder, error, olderError, unavailable, retry, loadOlder, canLoadOlder: hasCursor(pagination) }
}
