import { useEffect, useRef, useState } from 'react'
import { getTokenSupply } from '../services/api'

const idleState = { status: 'idle', data: null }

export function useTokenSupply(path) {
  const requestId = useRef(0)
  const [state, setState] = useState(idleState)

  useEffect(() => {
    const id = ++requestId.current
    if (!path?.startsWith('gno.land/r/')) {
      setState(idleState)
      return undefined
    }
    const activeController = new AbortController()
    setState({ status: 'loading', data: null })
    getTokenSupply(path, { signal: activeController.signal }).then((data) => {
      if (id !== requestId.current || activeController.signal.aborted) return
      setState({ status: data.available ? 'success' : 'unavailable', data })
    }).catch((requestError) => {
      if (id !== requestId.current || requestError?.name === 'AbortError') return
      setState({ status: requestError?.status === 404 ? 'notToken' : 'unavailable', data: null })
    })
    return () => {
      requestId.current += 1
      activeController.abort()
    }
  }, [path])

  return state
}
