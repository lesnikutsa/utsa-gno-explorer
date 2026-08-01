import { useCallback, useEffect, useRef, useState } from 'react'
import { getAccount, getAccountTransactions } from '../services/api'
import { decodeAccountRouteAddress } from '../utils/account'
import { emptyAccountHistory, historyRequestIsCurrent } from '../utils/accountHistory'

export const ACCOUNT_HISTORY_PAGE_SIZE = 20

const initialState = {
  account: null,
  loading: true,
  invalidAddress: false,
  unavailable: false,
  error: false,
  healthState: 'loading',
}

export function useAccountDetail(routeAddress) {
  const requestedAddress = decodeAccountRouteAddress(routeAddress)
  const requestIdRef = useRef(0)
  const [retryCount, setRetryCount] = useState(0)
  const [state, setState] = useState(initialState)
  const [history, setHistory] = useState(emptyAccountHistory)
  const [cursorHistory, setCursorHistory] = useState([null])
  const historyGenerationRef = useRef(0)
  const historyAddressRef = useRef(requestedAddress)
  const historyControllersRef = useRef(new Set())
  const failedHistoryRequestRef = useRef(null)
  const retry = useCallback(() => setRetryCount((count) => count + 1), [])

  const loadHistoryPage = useCallback((cursor, targetIndex, nextHistory) => {
    if (requestedAddress === null) return
    for (const pending of historyControllersRef.current) pending.abort()
    historyControllersRef.current.clear()
    const controller = new AbortController()
    const generation = ++historyGenerationRef.current
    const address = requestedAddress
    historyControllersRef.current.add(controller)
    setHistory((current) => ({ ...current, items: [], pagination: null, loading: true, initialError: false, pageError: false }))
    getAccountTransactions(address, {
      limit: ACCOUNT_HISTORY_PAGE_SIZE,
      beforeHeight: cursor?.height,
      beforeTxIndex: cursor?.txIndex,
      signal: controller.signal,
    }).then((result) => {
      if (!historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return
      const pagination = result.pagination || null
      const hasNextCursor = pagination?.next_before_height !== null
        && pagination?.next_before_height !== undefined
        && pagination?.next_before_tx_index !== null
        && pagination?.next_before_tx_index !== undefined
      setHistory({
        items: (result.items || []).slice(0, ACCOUNT_HISTORY_PAGE_SIZE),
        pagination,
        loading: false,
        initialError: false,
        pageError: false,
        pageIndex: targetIndex,
        canLoadOlder: hasNextCursor,
      })
      if (nextHistory) setCursorHistory(nextHistory)
      failedHistoryRequestRef.current = null
    }).catch((requestError) => {
      if (requestError.name === 'AbortError' || !historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return
      setHistory({
        items: [], pagination: null, loading: false,
        initialError: targetIndex === 0, pageError: targetIndex !== 0,
        pageIndex: targetIndex, canLoadOlder: false,
      })
      failedHistoryRequestRef.current = { cursor, targetIndex, history: nextHistory }
    }).finally(() => historyControllersRef.current.delete(controller))
  }, [requestedAddress])

  const retryHistory = useCallback(() => {
    const failed = failedHistoryRequestRef.current
    if (!failed || failed.targetIndex === 0) {
      setCursorHistory([null])
      loadHistoryPage(null, 0, [null])
      return
    }
    loadHistoryPage(failed.cursor, failed.targetIndex, failed.history)
  }, [loadHistoryPage])

  const loadOlderHistory = useCallback(() => {
    const pagination = history.pagination
    if (history.loading || !history.canLoadOlder || pagination?.next_before_height == null || pagination?.next_before_tx_index == null) return
    const cursor = { height: pagination.next_before_height, txIndex: pagination.next_before_tx_index }
    const nextHistory = [...cursorHistory.slice(0, history.pageIndex + 1), cursor]
    loadHistoryPage(cursor, history.pageIndex + 1, nextHistory)
  }, [cursorHistory, history, loadHistoryPage])

  const loadNewerHistory = useCallback(() => {
    if (history.loading || history.pageIndex === 0) return
    loadHistoryPage(cursorHistory[history.pageIndex - 1], history.pageIndex - 1)
  }, [cursorHistory, history.loading, history.pageIndex, loadHistoryPage])

  useEffect(() => {
    historyAddressRef.current = requestedAddress
    failedHistoryRequestRef.current = null
    setCursorHistory([null])
    if (requestedAddress === null) {
      ++historyGenerationRef.current
      for (const pending of historyControllersRef.current) pending.abort()
      historyControllersRef.current.clear()
      setHistory({ ...emptyAccountHistory(), loading: false })
      return undefined
    }
    loadHistoryPage(null, 0, [null])
    return () => {
      ++historyGenerationRef.current
      for (const pending of historyControllersRef.current) pending.abort()
      historyControllersRef.current.clear()
    }
  }, [loadHistoryPage, requestedAddress])

  useEffect(() => {
    const requestId = ++requestIdRef.current
    let mounted = true
    const update = (nextState) => {
      if (mounted && requestId === requestIdRef.current) setState(nextState)
    }
    const address = requestedAddress

    if (address === null) {
      update({ ...initialState, loading: false, invalidAddress: true, healthState: 'healthy' })
      return () => { mounted = false }
    }

    setState((current) => ({
      ...current,
      account: current.account?.address === address ? current.account : null,
      loading: true,
      invalidAddress: false,
      unavailable: false,
      error: false,
      healthState: current.account?.address === address ? 'healthy' : 'loading',
    }))

    getAccount(address).then((account) => {
      update({ ...initialState, account, loading: false, healthState: 'healthy' })
    }).catch((requestError) => {
      const errorState = {
        invalidAddress: requestError.status === 422,
        unavailable: requestError.status === 503,
        error: requestError.status !== 422 && requestError.status !== 503,
      }
      setState((current) => {
        if (!mounted || requestId !== requestIdRef.current) return current
        return {
          ...current,
          ...errorState,
          loading: false,
          healthState: errorState.invalidAddress ? 'healthy' : 'error',
        }
      })
    })

    return () => { mounted = false }
  }, [requestedAddress, retryCount])

  return { ...state, requestedAddress, retry, history, retryHistory, loadOlderHistory, loadNewerHistory }
}
