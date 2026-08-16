import { useEffect, useRef } from 'react'

export const TOKENS_POLL_MS = 30_000
export const TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS = 15_000

export function useTokensAutoRefresh({ enabled, refreshTokens }) {
  const timeout = useRef(null)
  const cycleRunning = useRef(false)
  const enabledRef = useRef(enabled)

  useEffect(() => { enabledRef.current = enabled }, [enabled])
  useEffect(() => {
    let disposed = false
    const clearScheduled = () => {
      if (timeout.current !== null) { clearTimeout(timeout.current); timeout.current = null }
    }
    const schedule = () => {
      clearScheduled()
      if (disposed || !enabledRef.current || document.visibilityState === 'hidden') return
      timeout.current = setTimeout(runCycle, TOKENS_POLL_MS)
    }
    const runCycle = async () => {
      clearScheduled()
      if (!enabledRef.current || document.visibilityState === 'hidden' || cycleRunning.current) return
      cycleRunning.current = true
      try { await refreshTokens() } finally { cycleRunning.current = false; schedule() }
    }
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') clearScheduled()
      else if (enabledRef.current && !cycleRunning.current) runCycle()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    if (enabled) schedule()
    return () => { disposed = true; clearScheduled(); document.removeEventListener('visibilitychange', handleVisibilityChange) }
  }, [enabled, refreshTokens])
}
