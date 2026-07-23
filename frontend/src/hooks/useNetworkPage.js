import { useCallback, useEffect, useRef, useState } from 'react'
import { getHealth, getNetwork } from '../services/api'

export const NETWORK_PAGE_POLL_MS = 15_000

export function useNetworkPage() {
  const [data, setData] = useState({ health: null, network: null })
  const [errors, setErrors] = useState({ health: false, network: false })
  const [loading, setLoading] = useState(true)
  const [nextRefreshAt, setNextRefreshAt] = useState(null)
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    const [health, network] = await Promise.allSettled([getHealth(), getNetwork()])

    if (mounted.current) {
      setData((current) => ({
        health: health.status === 'fulfilled' ? health.value : current.health,
        network: network.status === 'fulfilled' ? network.value : current.network,
      }))
      setErrors({ health: health.status === 'rejected', network: network.status === 'rejected' })
      setLoading(false)
      setNextRefreshAt(Date.now() + NETWORK_PAGE_POLL_MS)
      timer.current = window.setTimeout(refresh, NETWORK_PAGE_POLL_MS)
    }
    inFlight.current = false
  }, [])

  useEffect(() => {
    mounted.current = true
    refresh()
    return () => {
      mounted.current = false
      window.clearTimeout(timer.current)
    }
  }, [refresh])

  let healthState = 'loading'
  if (!loading && errors.health) healthState = 'error'
  else if (!loading && data.health?.status === 'ok') healthState = 'healthy'
  else if (!loading && data.health) healthState = 'degraded'

  return { data, errors, loading, healthState, nextRefreshAt }
}
