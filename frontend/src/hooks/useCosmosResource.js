import { useCallback, useEffect, useRef, useState } from 'react'

export function useCosmosResource(url, interval = 5000) {
  const [state, setState] = useState({ data: null, loading: true, error: null, stale: false })
  const running = useRef(false)
  const activeController = useRef(null)
  const generation = useRef(0)
  const load = useCallback(async (background = false) => {
    if (running.current || document.hidden) return
    running.current = true
    const requestGeneration = generation.current
    const controller = new AbortController()
    activeController.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } })
      if (!response.ok) throw new Error(`Request failed (${response.status})`)
      const data = await response.json()
      if (requestGeneration === generation.current) setState((current) => {
        if (background && Array.isArray(data.blocks) && Array.isArray(current.data?.blocks)) {
          const newest = data.blocks[0]?.height
          const previous = current.data.blocks[0]?.height
          if (Number.isInteger(newest) && Number.isInteger(previous) && newest >= previous && newest - previous <= 10) {
            const merged = [...data.blocks, ...current.data.blocks]
            data.blocks = [...new Map(merged.map((block) => [block.height, block])).values()]
              .sort((left, right) => right.height - left.height).slice(0, 20)
          }
        }
        return { data, loading: false, error: null, stale: false }
      })
    } catch (error) {
      if (requestGeneration === generation.current) setState((current) => ({ ...current, loading: false, error: error.name === 'AbortError' ? 'Request timed out' : error.message, stale: Boolean(current.data) }))
    } finally {
      window.clearTimeout(timeout)
      running.current = false
      if (activeController.current === controller) activeController.current = null
    }
  }, [url])
  useEffect(() => {
    let active = true
    load(false)
    const timer = window.setInterval(() => { if (active) load(true) }, interval)
    const visible = () => { if (!document.hidden) load(true) }
    document.addEventListener('visibilitychange', visible)
    return () => { active = false; generation.current += 1; activeController.current?.abort(); running.current = false; window.clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [load, interval])
  return { ...state, refresh: () => load(false) }
}
