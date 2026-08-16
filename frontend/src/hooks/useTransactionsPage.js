import { useCallback, useEffect, useRef, useState } from 'react'
import { getTransactions } from '../services/api'

export const TRANSACTIONS_POLL_MS = 5_000
export const PAGE_SIZE = 25

const cursorFromResponse = (response) => {
  const pagination = response.pagination ?? {}
  const hasNextCursor = pagination.next_before_height !== null
    && pagination.next_before_height !== undefined
    && pagination.next_before_tx_index !== null
    && pagination.next_before_tx_index !== undefined
  return hasNextCursor ? {
    height: pagination.next_before_height,
    txIndex: pagination.next_before_tx_index,
  } : null
}

export function useTransactionsPage() {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false)
  const [manualRefreshing, setManualRefreshing] = useState(false)
  const [error, setError] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [nextCursor, setNextCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const [pageIndex, setPageIndex] = useState(0)
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const requestId = useRef(0)
  const failedRequest = useRef(null)
  const timerId = useRef(null)
  const transactionsRef = useRef([])
  const pageIndexRef = useRef(0)

  const clearRefreshTimer = useCallback(() => {
    if (timerId.current !== null) window.clearTimeout(timerId.current)
    timerId.current = null
  }, [])

  const refreshLatestInBackground = useCallback(async ({ manual = false } = {}) => {
    if (inFlight.current || pageIndexRef.current !== 0) return false
    if (!manual && document.visibilityState === 'hidden') return false
    clearRefreshTimer()
    inFlight.current = true
    setBackgroundRefreshing(!manual)
    setManualRefreshing(manual)
    const id = ++requestId.current

    try {
      const response = await getTransactions({ limit: PAGE_SIZE })
      if (!mounted.current || id !== requestId.current || pageIndexRef.current !== 0) return false
      const rows = (response.items ?? []).slice(0, PAGE_SIZE)
      setTransactions(rows)
      transactionsRef.current = rows
      setNextCursor(cursorFromResponse(response))
      failedRequest.current = null
      setError(false)
      setHealthState('healthy')
      return true
    } catch {
      if (!mounted.current || id !== requestId.current) return false
      setError(true)
      setHealthState(transactionsRef.current.length ? 'degraded' : 'error')
      return false
    } finally {
      if (mounted.current && id === requestId.current) {
        setBackgroundRefreshing(false)
        setManualRefreshing(false)
        inFlight.current = false
        if (pageIndexRef.current === 0 && document.visibilityState !== 'hidden') {
          timerId.current = window.setTimeout(() => {
            timerId.current = null
            refreshLatestInBackground()
          }, TRANSACTIONS_POLL_MS)
        }
      }
    }
  }, [clearRefreshTimer])

  const loadPage = useCallback(async (cursor, targetIndex, history) => {
    if (inFlight.current) return false
    clearRefreshTimer()
    const attemptedRequest = { cursor, targetIndex, history }
    const id = ++requestId.current
    inFlight.current = true
    setLoading(true)
    setTransactions([])
    transactionsRef.current = []
    setError(false)

    try {
      const response = await getTransactions({
        limit: PAGE_SIZE,
        beforeHeight: cursor?.height,
        beforeTxIndex: cursor?.txIndex,
      })
      if (!mounted.current || id !== requestId.current) return false
      const rows = (response.items ?? []).slice(0, PAGE_SIZE)
      setTransactions(rows)
      transactionsRef.current = rows
      setNextCursor(cursorFromResponse(response))
      setPageIndex(targetIndex)
      pageIndexRef.current = targetIndex
      if (history) setCursorHistory(history)
      failedRequest.current = null
      setHealthState('healthy')
      return true
    } catch {
      if (!mounted.current || id !== requestId.current) return false
      failedRequest.current = attemptedRequest
      setError(true)
      setHealthState('error')
      return false
    } finally {
      if (mounted.current && id === requestId.current) {
        setLoading(false)
        inFlight.current = false
        if (pageIndexRef.current === 0 && document.visibilityState !== 'hidden') {
          timerId.current = window.setTimeout(() => {
            timerId.current = null
            refreshLatestInBackground()
          }, TRANSACTIONS_POLL_MS)
        }
      }
    }
  }, [clearRefreshTimer, refreshLatestInBackground])

  const retry = useCallback(() => {
    const request = failedRequest.current
    if (!request) return
    loadPage(request.cursor, request.targetIndex, request.history)
  }, [loadPage])
  const refresh = useCallback(() => refreshLatestInBackground({ manual: true }), [refreshLatestInBackground])
  const loadOlder = useCallback(() => {
    if (inFlight.current || !nextCursor) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage(nextCursor, pageIndex + 1, history)
  }, [cursorHistory, loadPage, nextCursor, pageIndex])
  const loadNewer = useCallback(() => {
    if (inFlight.current || pageIndex === 0) return
    loadPage(cursorHistory[pageIndex - 1], pageIndex - 1)
  }, [cursorHistory, loadPage, pageIndex])

  useEffect(() => {
    mounted.current = true
    loadPage(null, 0)
    const handleVisibilityChange = () => {
      clearRefreshTimer()
      if (document.visibilityState !== 'hidden' && pageIndexRef.current === 0 && !inFlight.current) {
        refreshLatestInBackground()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      mounted.current = false
      requestId.current += 1
      inFlight.current = false
      clearRefreshTimer()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [clearRefreshTimer, loadPage, refreshLatestInBackground])

  return {
    transactions,
    loading,
    backgroundRefreshing,
    manualRefreshing,
    error,
    healthState,
    pageIndex,
    canLoadOlder: nextCursor !== null,
    retry,
    refresh,
    loadOlder,
    loadNewer,
  }
}
