import { useCallback, useEffect, useRef, useState } from 'react'
import { getAccount, getAccountTransactions } from '../services/api'
import { decodeAccountRouteAddress } from '../utils/account'

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
  const [history, setHistory] = useState({ items: [], pagination: null, loading: true, loadingMore: false, error: false })
  const [historyRetryCount, setHistoryRetryCount] = useState(0)
  const retry = useCallback(() => setRetryCount((count) => count + 1), [])
  const retryHistory = useCallback(() => setHistoryRetryCount((count) => count + 1), [])

  useEffect(() => {
    if (requestedAddress === null) {
      setHistory({ items: [], pagination: null, loading: false, loadingMore: false, error: false })
      return undefined
    }
    const controller = new AbortController()
    setHistory({ items: [], pagination: null, loading: true, loadingMore: false, error: false })
    getAccountTransactions(requestedAddress, { signal: controller.signal }).then((result) => {
      setHistory({ items: result.items || [], pagination: result.pagination || null, loading: false, loadingMore: false, error: false })
    }).catch((requestError) => {
      if (requestError.name !== 'AbortError') setHistory({ items: [], pagination: null, loading: false, loadingMore: false, error: true })
    })
    return () => controller.abort()
  }, [requestedAddress, historyRetryCount])

  const loadMoreHistory = useCallback(() => {
    const cursor = history.pagination
    if (!requestedAddress || history.loadingMore || !cursor?.next_before_height) return
    setHistory((current) => ({ ...current, loadingMore: true, error: false }))
    getAccountTransactions(requestedAddress, {
      beforeHeight: cursor.next_before_height,
      beforeTxIndex: cursor.next_before_tx_index,
    }).then((result) => setHistory((current) => {
      const merged = new Map(current.items.map((item) => [`${item.block_height}:${item.index}`, item]))
      for (const item of result.items || []) merged.set(`${item.block_height}:${item.index}`, item)
      return { items: [...merged.values()], pagination: result.pagination || null, loading: false, loadingMore: false, error: false }
    })).catch(() => setHistory((current) => ({ ...current, loadingMore: false, error: true })))
  }, [history.pagination, history.loadingMore, requestedAddress])

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

  return { ...state, requestedAddress, retry, history, retryHistory, loadMoreHistory }
}
