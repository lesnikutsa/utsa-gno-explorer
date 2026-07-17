import { useCallback, useEffect, useRef, useState } from 'react'
import { getBlocks, getHealth, getNetwork, getValidators } from '../services/api'

const FAST_POLL_MS = 5_000
const SLOW_POLL_MS = 15_000

export function useExplorerData() {
  const [data, setData] = useState({ health: null, network: null, blocks: [], validators: [] })
  const [errors, setErrors] = useState({ health: false, network: false, blocks: false, validators: false })
  const [loading, setLoading] = useState(true)
  const [nextFastRefreshAt, setNextFastRefreshAt] = useState(null)
  const mounted = useRef(false)
  const fastInFlight = useRef(false)
  const slowInFlight = useRef(false)
  const fastTimer = useRef(null)
  const slowTimer = useRef(null)
  const initialGroupsCompleted = useRef(new Set())

  const finishInitialGroup = useCallback((group) => {
    initialGroupsCompleted.current.add(group)
    if (initialGroupsCompleted.current.size === 2) setLoading(false)
  }, [])

  const refreshFast = useCallback(async () => {
    if (fastInFlight.current) return
    fastInFlight.current = true
    if (mounted.current) setNextFastRefreshAt(Date.now())
    const [network, blocks] = await Promise.allSettled([getNetwork(), getBlocks()])

    if (mounted.current) {
      setData((current) => ({
        ...current,
        network: network.status === 'fulfilled' ? network.value : current.network,
        blocks: blocks.status === 'fulfilled' ? blocks.value.items ?? [] : current.blocks,
      }))
      setErrors((current) => ({ ...current, network: network.status === 'rejected', blocks: blocks.status === 'rejected' }))
      setNextFastRefreshAt(Date.now() + FAST_POLL_MS)
      finishInitialGroup('fast')
      fastTimer.current = window.setTimeout(refreshFast, FAST_POLL_MS)
    }
    fastInFlight.current = false
  }, [finishInitialGroup])

  const refreshSlow = useCallback(async () => {
    if (slowInFlight.current) return
    slowInFlight.current = true
    const [health, validators] = await Promise.allSettled([getHealth(), getValidators()])

    if (mounted.current) {
      setData((current) => ({
        ...current,
        health: health.status === 'fulfilled' ? health.value : current.health,
        validators: validators.status === 'fulfilled' ? validators.value.items ?? [] : current.validators,
      }))
      setErrors((current) => ({ ...current, health: health.status === 'rejected', validators: validators.status === 'rejected' }))
      finishInitialGroup('slow')
      slowTimer.current = window.setTimeout(refreshSlow, SLOW_POLL_MS)
    }
    slowInFlight.current = false
  }, [finishInitialGroup])

  useEffect(() => {
    mounted.current = true
    refreshFast()
    refreshSlow()

    return () => {
      mounted.current = false
      window.clearTimeout(fastTimer.current)
      window.clearTimeout(slowTimer.current)
    }
  }, [refreshFast, refreshSlow])

  let healthState = 'loading'
  if (!loading && errors.health) healthState = 'error'
  else if (!loading && data.health?.status === 'ok') healthState = 'healthy'
  else if (!loading && data.health) healthState = 'degraded'

  return { data, errors, loading, healthState, nextFastRefreshAt }
}
