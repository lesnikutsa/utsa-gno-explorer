import { useCallback, useEffect, useRef, useState } from 'react'
import { getBlocks } from '../services/api'

export function useBlocksPage() {
  const [blocks, setBlocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const mounted = useRef(false)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return

    inFlight.current = true
    if (mounted.current) {
      setLoading(true)
      setError(false)
    }

    try {
      const response = await getBlocks({ limit: 25 })
      if (mounted.current) setBlocks(response.items ?? [])
    } catch {
      if (mounted.current) setError(true)
    } finally {
      if (mounted.current) setLoading(false)
      inFlight.current = false
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    refresh()

    return () => {
      mounted.current = false
    }
  }, [refresh])

  return { blocks, loading, error, refresh }
}
