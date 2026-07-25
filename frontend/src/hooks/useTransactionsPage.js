import { useCallback, useEffect, useRef, useState } from 'react'
import { getTransactions } from '../services/api'

export const PAGE_SIZE = 25

export function useTransactionsPage() {
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [nextCursor, setNextCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const [pageIndex, setPageIndex] = useState(0)
  const mounted = useRef(false)
  const requestId = useRef(0)
  const failedRequest = useRef(null)

  const loadPage = useCallback(async (cursor, targetIndex, history) => {
    const attemptedRequest = { cursor, targetIndex, history }
    const id = ++requestId.current
    setLoading(true)
    setTransactions([])
    setError(false)

    try {
      const response = await getTransactions({
        limit: PAGE_SIZE,
        beforeHeight: cursor?.height,
        beforeTxIndex: cursor?.txIndex,
      })
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNextCursor = pagination.next_before_height !== null
        && pagination.next_before_height !== undefined
        && pagination.next_before_tx_index !== null
        && pagination.next_before_tx_index !== undefined
      setTransactions((response.items ?? []).slice(0, PAGE_SIZE))
      setNextCursor(hasNextCursor ? {
        height: pagination.next_before_height,
        txIndex: pagination.next_before_tx_index,
      } : null)
      setPageIndex(targetIndex)
      if (history) setCursorHistory(history)
      failedRequest.current = null
      setHealthState('healthy')
    } catch {
      if (!mounted.current || id !== requestId.current) return
      failedRequest.current = attemptedRequest
      setError(true)
      setHealthState('error')
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

  const retry = useCallback(() => {
    const request = failedRequest.current
    if (!request) return
    loadPage(request.cursor, request.targetIndex, request.history)
  }, [loadPage])
  const loadOlder = useCallback(() => {
    if (loading || !nextCursor) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage(nextCursor, pageIndex + 1, history)
  }, [cursorHistory, loadPage, loading, nextCursor, pageIndex])
  const loadNewer = useCallback(() => {
    if (loading || pageIndex === 0) return
    loadPage(cursorHistory[pageIndex - 1], pageIndex - 1)
  }, [cursorHistory, loadPage, loading, pageIndex])

  useEffect(() => {
    mounted.current = true
    loadPage(null, 0)
    return () => {
      mounted.current = false
      requestId.current += 1
    }
  }, [loadPage])

  return {
    transactions,
    loading,
    error,
    healthState,
    pageIndex,
    canLoadOlder: nextCursor !== null,
    retry,
    loadOlder,
    loadNewer,
  }
}
