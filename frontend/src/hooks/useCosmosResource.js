import { useCallback, useEffect, useRef, useState } from 'react'

export function useCosmosResource(load, { interval = 5_000, enabled = true, stopWhen } = {}) {
  const [state, setState] = useState({ data: null, loading: true, error: null, stale: false, updatedAt: null })
  const activeRequest = useRef(null)
  const generation = useRef(0)
  const run = useCallback(async ({ background = false } = {}) => {
    if (!enabled || activeRequest.current || document.hidden) return
    const current = generation.current
    const controller = new AbortController()
    activeRequest.current = controller
    if (!background) setState({ data: null, loading: true, error: null, stale: false, updatedAt: null })
    try {
      const data = await load(controller.signal)
      if (current === generation.current && !controller.signal.aborted) setState({ data, loading: false, error: null, stale: false, updatedAt: Date.now() })
    } catch (error) {
      if (error.name !== 'AbortError' && current === generation.current) setState((old) => ({ ...old, loading: false, error, stale: Boolean(old.data) }))
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null
    }
  }, [enabled, load])
  useEffect(() => {
    generation.current += 1
    setState({ data: null, loading: true, error: null, stale: false, updatedAt: null })
    run()
    const tick = () => { if (!stopWhen?.()) run({ background: true }) }
    const timer = enabled ? window.setInterval(tick, interval) : null
    const visible = () => { if (!document.hidden) run({ background: true }) }
    document.addEventListener('visibilitychange', visible)
    return () => {
      generation.current += 1
      activeRequest.current?.abort()
      activeRequest.current = null
      if (timer) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [enabled, interval, run, stopWhen])
  return { ...state, refresh: () => run({ background: Boolean(state.data) }) }
}
