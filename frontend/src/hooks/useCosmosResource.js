import { useCallback, useEffect, useRef, useState } from 'react'

export class CosmosResourceTimeoutError extends Error {
  constructor(timeoutMs) {
    super(`Explorer API request timed out after ${timeoutMs} ms`)
    this.name = 'CosmosResourceTimeoutError'
  }
}

export const cosmosResourceFailureState = (previous, error) => ({
  ...previous, loading: false, error, stale: Boolean(previous.data),
})

export const cosmosResourceResponseIsCurrent = ({ generation, currentGeneration, controller }) => (
  generation === currentGeneration && !controller.signal.aborted
)

export function loadCosmosResourceWithTimeout(load, controller, timeoutMs) {
  let timedOut = false
  let timeoutId
  let abortHandler
  const aborted = new Promise((resolve, reject) => {
    abortHandler = () => reject(timedOut
      ? new CosmosResourceTimeoutError(timeoutMs)
      : Object.assign(new Error('Request aborted'), { name: 'AbortError' }))
    controller.signal.addEventListener('abort', abortHandler, { once: true })
  })
  const timeout = new Promise(() => {
    timeoutId = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
  })
  return Promise.race([Promise.resolve().then(() => load(controller.signal)), aborted, timeout])
    .finally(() => {
      window.clearTimeout(timeoutId)
      controller.signal.removeEventListener('abort', abortHandler)
    })
}

export function useCosmosResource(load, { interval = 5_000, requestTimeout = 15_000, enabled = true, stopWhen } = {}) {
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
      const data = await loadCosmosResourceWithTimeout(load, controller, requestTimeout)
      if (cosmosResourceResponseIsCurrent({ generation: current, currentGeneration: generation.current, controller })) setState({ data, loading: false, error: null, stale: false, updatedAt: Date.now() })
    } catch (error) {
      if (error.name !== 'AbortError' && current === generation.current) setState((old) => cosmosResourceFailureState(old, error))
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null
    }
  }, [enabled, load, requestTimeout])
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
