import { useCallback, useEffect, useRef, useState } from 'react'
import { getBlocks, getHealth, getNetwork, getValidators } from '../services/api'

const POLL_INTERVAL_MS = 15_000
const endpointRequests = { health: getHealth, network: getNetwork, blocks: getBlocks, validators: getValidators }

export function useExplorerData() {
  const [data, setData] = useState({ health: null, network: null, blocks: [], validators: [] })
  const [errors, setErrors] = useState({ health: false, network: false, blocks: false, validators: false })
  const [loading, setLoading] = useState(true)
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null)
  const inFlight = useRef(false)
  const mounted = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true

    const entries = Object.entries(endpointRequests)
    const results = await Promise.allSettled(entries.map(([, request]) => request()))

    if (mounted.current) {
      setData((current) => {
        const next = { ...current }
        results.forEach((result, index) => {
          if (result.status !== 'fulfilled') return
          const endpoint = entries[index][0]
          next[endpoint] = endpoint === 'blocks' || endpoint === 'validators'
            ? result.value.items ?? []
            : result.value
        })
        return next
      })
      setErrors(Object.fromEntries(entries.map(([endpoint], index) => [endpoint, results[index].status === 'rejected'])))
      if (results.some((result) => result.status === 'fulfilled')) setLastUpdatedAt(new Date())
      setLoading(false)
    }

    inFlight.current = false
  }, [])

  useEffect(() => {
    mounted.current = true
    refresh()
    const intervalId = window.setInterval(refresh, POLL_INTERVAL_MS)

    return () => {
      mounted.current = false
      window.clearInterval(intervalId)
    }
  }, [refresh])

  let healthState = 'loading'
  if (!loading && errors.health) healthState = 'error'
  else if (!loading && data.health?.status === 'ok') healthState = 'healthy'
  else if (!loading && data.health) healthState = 'degraded'

  return { data, errors, loading, healthState, lastUpdatedAt, refresh }
}
