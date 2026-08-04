import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmDetail } from '../services/api'

const idleState = { data: null, loading: false, error: false, temporaryError: false, notFound: false, healthState: 'healthy' }
const loadingState = { data: null, loading: true, error: false, temporaryError: false, notFound: false, healthState: 'loading' }

export function useRealmDetail(path) {
  const requestId = useRef(0)
  const controller = useRef(null)
  const [retryCount, setRetryCount] = useState(0)
  const [state, setState] = useState(() => path ? loadingState : idleState)
  const retry = useCallback(() => setRetryCount((count) => count + 1), [])

  useEffect(() => {
    controller.current?.abort()
    const id = ++requestId.current
    if (!path) {
      setState(idleState)
      return undefined
    }
    const activeController = new AbortController()
    controller.current = activeController
    setState(loadingState)
    getRealmDetail({ path, signal: activeController.signal }).then((data) => {
      if (id !== requestId.current || activeController.signal.aborted) return
      setState({ data, loading: false, error: false, temporaryError: false, notFound: false, healthState: 'healthy' })
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      setState({
        data: null,
        loading: false,
        notFound: requestError?.status === 404,
        temporaryError: requestError?.status === 503,
        error: requestError?.status !== 404 && requestError?.status !== 503,
        healthState: requestError?.status === 404 ? 'healthy' : 'error',
      })
    })
    return () => {
      requestId.current += 1
      activeController.abort()
    }
  }, [path, retryCount])

  return { ...state, retry }
}
