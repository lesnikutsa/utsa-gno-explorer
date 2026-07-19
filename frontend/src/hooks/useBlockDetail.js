import { useCallback, useEffect, useRef, useState } from 'react'
import { getBlock } from '../services/api'

const isValidHeight = (height) => /^[1-9]\d*$/.test(height)

export function useBlockDetail(height) {
  const requestIdRef = useRef(0)
  const [retryCount, setRetryCount] = useState(0)
  const [state, setState] = useState({
    block: null,
    loading: true,
    notFound: false,
    invalidHeight: false,
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

    if (!isValidHeight(height)) {
      update({ block: null, loading: false, notFound: false, invalidHeight: true, error: false, healthState: 'healthy' })
      return () => { mounted = false }
    }

    update({ block: null, loading: true, notFound: false, invalidHeight: false, error: false, healthState: 'loading' })
    getBlock(height)
      .then((block) => update({ block, loading: false, notFound: false, invalidHeight: false, error: false, healthState: 'healthy' }))
      .catch((error) => {
        if (error.status === 404) {
          update({ block: null, loading: false, notFound: true, invalidHeight: false, error: false, healthState: 'healthy' })
        } else if (error.status === 422) {
          update({ block: null, loading: false, notFound: false, invalidHeight: true, error: false, healthState: 'healthy' })
        } else {
          update({ block: null, loading: false, notFound: false, invalidHeight: false, error: true, healthState: 'error' })
        }
      })

    return () => { mounted = false }
  }, [height, retryCount])

  return { ...state, retry }
}
