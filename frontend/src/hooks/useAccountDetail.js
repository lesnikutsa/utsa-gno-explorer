import { useCallback, useEffect, useRef, useState } from 'react'
import { getAccount, getAccountTransactions } from '../services/api'
import { decodeAccountRouteAddress } from '../utils/account'
import { emptyAccountHistory, historyRequestIsCurrent, mergeAccountHistoryItems } from '../utils/accountHistory'

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
  const [historyRetryCount, setHistoryRetryCount] = useState(0)
  const historyGenerationRef = useRef(0)
  const historyAddressRef = useRef(requestedAddress)
  const historyControllersRef = useRef(new Set())
  const loadMoreActiveRef = useRef(false)
  const retry = useCallback(() => setRetryCount((count) => count + 1), [])
  const retryHistory = useCallback(() => setHistoryRetryCount((count) => count + 1), [])

  useEffect(() => {
    const generation = ++historyGenerationRef.current
    historyAddressRef.current = requestedAddress
    for (const pending of historyControllersRef.current) pending.abort()
    historyControllersRef.current.clear()
    loadMoreActiveRef.current = false
    if (requestedAddress === null) {
      setHistory({ ...emptyAccountHistory(), loading: false })
      return undefined
    }
    const controller = new AbortController()
    const address = requestedAddress
    historyControllersRef.current.add(controller)
    setHistory(emptyAccountHistory())
    getAccountTransactions(requestedAddress, { signal: controller.signal }).then((result) => {
      if (!historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return
      setHistory({ items: result.items || [], pagination: result.pagination || null, loading: false, loadingMore: false, initialError: false, loadMoreError: false })
    }).catch((requestError) => {
      if (requestError.name === 'AbortError' || !historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return
      setHistory({ items: [], pagination: null, loading: false, loadingMore: false, initialError: true, loadMoreError: false })
    }).finally(() => historyControllersRef.current.delete(controller))
    return () => {
      ++historyGenerationRef.current
      for (const pending of historyControllersRef.current) pending.abort()
      historyControllersRef.current.clear()
      loadMoreActiveRef.current = false
    }
  }, [requestedAddress, historyRetryCount])

  const loadMoreHistory = useCallback(() => {
    const cursor = history.pagination
    if (!requestedAddress || loadMoreActiveRef.current || !cursor?.next_before_height) return
    const controller = new AbortController()
    const generation = historyGenerationRef.current
    const address = requestedAddress
    historyControllersRef.current.add(controller)
    loadMoreActiveRef.current = true
    setHistory((current) => ({ ...current, loadingMore: true, loadMoreError: false }))
    getAccountTransactions(requestedAddress, {
      beforeHeight: cursor.next_before_height,
      beforeTxIndex: cursor.next_before_tx_index,
      signal: controller.signal,
    }).then((result) => setHistory((current) => {
      if (!historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return current
      return { ...current, items: mergeAccountHistoryItems(current.items, result.items || []), pagination: result.pagination || null, loadingMore: false, loadMoreError: false }
    })).catch((requestError) => {
      if (requestError.name === 'AbortError' || !historyRequestIsCurrent({ controller, generation, currentGeneration: historyGenerationRef.current, address, currentAddress: historyAddressRef.current })) return
      setHistory((current) => ({ ...current, loadingMore: false, loadMoreError: true }))
    }).finally(() => {
      historyControllersRef.current.delete(controller)
      if (generation === historyGenerationRef.current) loadMoreActiveRef.current = false
    })
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
