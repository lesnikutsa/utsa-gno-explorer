import { useCallback, useEffect, useRef, useState } from 'react'
import { getTransaction } from '../services/api'

const isValidHeight = (height) => /^[1-9]\d*$/.test(height)
const isValidIndex = (index) => /^(0|[1-9]\d*)$/.test(index)

const initialState = {
  transaction: null,
  loading: true,
  notFound: false,
  invalidRoute: false,
  error: false,
  healthState: 'loading',
}

export function useTransactionDetail(height, index) {
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

    if (!isValidHeight(height) || !isValidIndex(index)) {
      update({ transaction: null, loading: false, notFound: false, invalidRoute: true, error: false, healthState: 'healthy' })
      return () => { mounted = false }
    }

    update(initialState)
    getTransaction(height, index)
      .then((transaction) => update({ transaction, loading: false, notFound: false, invalidRoute: false, error: false, healthState: 'healthy' }))
      .catch((requestError) => {
        if (requestError.status === 404) {
          update({ transaction: null, loading: false, notFound: true, invalidRoute: false, error: false, healthState: 'healthy' })
        } else if (requestError.status === 422) {
          update({ transaction: null, loading: false, notFound: false, invalidRoute: true, error: false, healthState: 'healthy' })
        } else {
          update({ transaction: null, loading: false, notFound: false, invalidRoute: false, error: true, healthState: 'error' })
        }
      })

    return () => { mounted = false }
  }, [height, index, retryCount])

  return { ...state, retry }
}
