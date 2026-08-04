import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealmDetail } from '../services/api'
import { idleRealmDetailState, loadingRealmDetailState, selectRealmDetailStateForPath } from '../utils/realmDetail'

export function useRealmDetail(path) {
  const requestId = useRef(0)
  const controller = useRef(null)
  const [retryCount, setRetryCount] = useState(0)
  const [state, setState] = useState(() => path ? loadingRealmDetailState(path) : idleRealmDetailState(null))
  const retry = useCallback(() => {
    if (path) setState(loadingRealmDetailState(path))
    setRetryCount((count) => count + 1)
  }, [path])

  useEffect(() => {
    controller.current?.abort()
    const id = ++requestId.current
    if (!path) {
      setState(idleRealmDetailState(null))
      return undefined
    }
    const requestedPath = path
    const activeController = new AbortController()
    controller.current = activeController
    setState(loadingRealmDetailState(requestedPath))
    getRealmDetail({ path: requestedPath, signal: activeController.signal }).then((data) => {
      if (id !== requestId.current || activeController.signal.aborted) return
      setState({ path: requestedPath, data, loading: false, error: false, temporaryError: false, notFound: false, healthState: 'healthy' })
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      setState({
        path: requestedPath,
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

  return { ...selectRealmDetailStateForPath(state, path), retry }
}
