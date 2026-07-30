import { useCallback, useEffect, useRef, useState } from 'react'
import { getAccount } from '../services/api'
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
  const retry = useCallback(() => setRetryCount((count) => count + 1), [])

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

  return { ...state, requestedAddress, retry }
}
