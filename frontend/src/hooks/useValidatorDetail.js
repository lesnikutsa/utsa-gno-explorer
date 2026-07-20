import { useCallback, useEffect, useRef, useState } from 'react'
import { getValidator } from '../services/api'

const CONSENSUS_ADDRESS_PATTERN = /^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$/

const decodeAddress = (routeAddress) => {
  if (typeof routeAddress !== 'string' || routeAddress.length === 0 || routeAddress.length > 128) return null

  try {
    const address = decodeURIComponent(routeAddress)
    if (address.length === 0 || address.length > 128 || address.includes('/')) return null
    return CONSENSUS_ADDRESS_PATTERN.test(address) ? address : null
  } catch {
    return null
  }
}

export function useValidatorDetail(routeAddress) {
  const requestIdRef = useRef(0)
  const [retryCount, setRetryCount] = useState(0)
  const [state, setState] = useState({
    validator: null,
    loading: true,
    notFound: false,
    invalidAddress: false,
    error: false,
    healthState: 'loading',
  })

  const retry = useCallback(() => setRetryCount((count) => count + 1), [])

  useEffect(() => {
    const requestId = ++requestIdRef.current
    let mounted = true
    const update = (nextState) => {
      if (mounted && requestId === requestIdRef.current) setState(nextState)
    }
    const address = decodeAddress(routeAddress)

    if (address === null) {
      update({ validator: null, loading: false, notFound: false, invalidAddress: true, error: false, healthState: 'healthy' })
      return () => { mounted = false }
    }

    update({ validator: null, loading: true, notFound: false, invalidAddress: false, error: false, healthState: 'loading' })
    getValidator(address)
      .then((validator) => update({ validator, loading: false, notFound: false, invalidAddress: false, error: false, healthState: 'healthy' }))
      .catch((requestError) => {
        if (requestError.status === 404) {
          update({ validator: null, loading: false, notFound: true, invalidAddress: false, error: false, healthState: 'healthy' })
        } else {
          update({ validator: null, loading: false, notFound: false, invalidAddress: false, error: true, healthState: 'error' })
        }
      })

    return () => { mounted = false }
  }, [routeAddress, retryCount])

  return { ...state, retry }
}
