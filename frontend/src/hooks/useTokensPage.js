import { useCallback, useEffect, useRef, useState } from 'react'
import { getNativeToken, getTokens, getTokenSupply } from '../services/api'
import { TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS } from './useTokensAutoRefresh'

export const PAGE_SIZE = 50

export function useTokensPage() {
  const [items, setItems] = useState([])
  const [summary, setSummary] = useState(null)
  const [top24h, setTop24h] = useState(null)
  const [nativeToken, setNativeToken] = useState(null)
  const [searchInput, setSearchInput] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [pageIndex, setPageIndex] = useState(0)
  const [nextCursor, setNextCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const mounted = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const failedRequest = useRef(null)
  const foregroundActive = useRef(false)
  const hasData = useRef(false)
  const supplyCache = useRef(new Map())
  const [supplies, setSupplies] = useState({})

  const loadPage = useCallback(async (request) => {
    const attempted = { ...request, history: request.history ? [...request.history] : undefined }
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    foregroundActive.current = true
    setLoading(true); setItems([]); setSummary(null); setTop24h(null); setError(false)
    try {
      const response = await getTokens({ limit: PAGE_SIZE, q: request.search,
        beforeActivityHeight: request.cursor?.activityHeight, beforePath: request.cursor?.path,
        signal: activeController.signal })
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNext = pagination.next_before_activity_height !== null && pagination.next_before_activity_height !== undefined
        && pagination.next_before_path !== null && pagination.next_before_path !== undefined
      setItems((response.items ?? []).slice(0, PAGE_SIZE)); setSummary(response.summary ?? null)
      setTop24h(Array.isArray(response.top_24h) ? response.top_24h.slice(0, 3) : null)
      setNextCursor(hasNext ? { activityHeight: pagination.next_before_activity_height, path: pagination.next_before_path } : null)
      setPageIndex(request.targetIndex); if (request.history) setCursorHistory(request.history)
      failedRequest.current = null; setHealthState('healthy')
      hasData.current = true
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current || requestError?.name === 'AbortError') return
      failedRequest.current = attempted; setItems([]); setSummary(null); setTop24h(null); setError(true); setHealthState('error')
    } finally {
      if (id === requestId.current) foregroundActive.current = false
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

  const refreshInBackground = useCallback(async () => {
    if (foregroundActive.current || controller.current?.background) return
    const activeController = new AbortController()
    activeController.background = true
    controller.current = activeController
    const id = ++requestId.current
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; activeController.abort() }, TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS)
    try {
      const [response, nativeResponse] = await Promise.all([
        getTokens({ limit: PAGE_SIZE, q: appliedSearch, signal: activeController.signal }),
        getNativeToken({ signal: activeController.signal }).catch(() => null),
      ])
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNext = pagination.next_before_activity_height != null && pagination.next_before_path != null
      setItems((response.items ?? []).slice(0, PAGE_SIZE))
      setSummary(response.summary ?? null)
      setTop24h(Array.isArray(response.top_24h) ? response.top_24h.slice(0, 3) : null)
      if (nativeResponse !== null) setNativeToken(nativeResponse)
      setNextCursor(hasNext ? { activityHeight: pagination.next_before_activity_height, path: pagination.next_before_path } : null)
      hasData.current = true; setError(false); setHealthState('healthy')
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current) return
      if (requestError?.name === 'AbortError' && !timedOut) return
      if (hasData.current) setHealthState('degraded')
    } finally {
      window.clearTimeout(timeout)
      if (id === requestId.current) controller.current = null
    }
  }, [appliedSearch])

  const resetAndLoad = useCallback((search) => {
    const history = [null]
    setCursorHistory(history); setPageIndex(0); setNextCursor(null)
    loadPage({ cursor: null, targetIndex: 0, history, search })
  }, [loadPage])
  const submitSearch = useCallback((event) => {
    event?.preventDefault(); const search = searchInput.trim()
    setSearchInput(search); setAppliedSearch(search); resetAndLoad(search)
  }, [resetAndLoad, searchInput])
  const clearSearch = useCallback(() => { setSearchInput(''); setAppliedSearch(''); resetAndLoad('') }, [resetAndLoad])
  const loadOlder = useCallback(() => {
    if (loading || !nextCursor) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage({ cursor: nextCursor, targetIndex: pageIndex + 1, history, search: appliedSearch })
  }, [appliedSearch, cursorHistory, loadPage, loading, nextCursor, pageIndex])
  const loadNewer = useCallback(() => {
    if (loading || pageIndex === 0) return
    loadPage({ cursor: cursorHistory[pageIndex - 1], targetIndex: pageIndex - 1, search: appliedSearch })
  }, [appliedSearch, cursorHistory, loadPage, loading, pageIndex])
  const retry = useCallback(() => { if (failedRequest.current) loadPage(failedRequest.current) }, [loadPage])

  useEffect(() => {
    mounted.current = true
    loadPage({ cursor: null, targetIndex: 0, history: [null], search: '' })
    return () => { mounted.current = false; requestId.current += 1; controller.current?.abort() }
  }, [loadPage])

  useEffect(() => {
    if (!mounted.current) return undefined
    const activeController = new AbortController()
    getNativeToken({ signal: activeController.signal }).then(setNativeToken).catch((nativeError) => {
      if (nativeError?.name !== 'AbortError') setNativeToken((current) => current ?? { available: false })
    })
    return () => activeController.abort()
  }, [])

  useEffect(() => {
    if (!items.length) return undefined
    const activeController = new AbortController()
    const pending = items.filter((item) => !supplyCache.current.has(item.path))
    let cursor = 0
    const worker = async () => {
      while (cursor < pending.length && !activeController.signal.aborted) {
        const item = pending[cursor++]
        try {
          const supply = await getTokenSupply(item.path, { signal: activeController.signal })
          supplyCache.current.set(item.path, supply)
          setSupplies((current) => ({ ...current, [item.path]: supply }))
        } catch (supplyError) {
          if (supplyError?.name === 'AbortError') return
          setSupplies((current) => ({ ...current, [item.path]: { available: false } }))
        }
      }
    }
    Promise.all(Array.from({ length: Math.min(4, pending.length) }, worker))
    const cached = Object.fromEntries(items.flatMap((item) => supplyCache.current.has(item.path)
      ? [[item.path, supplyCache.current.get(item.path)]] : []))
    if (Object.keys(cached).length) setSupplies((current) => ({ ...current, ...cached }))
    return () => activeController.abort()
  }, [items])

  return { items, supplies, summary, top24h, nativeToken, searchInput, appliedSearch, loading, error, healthState, pageIndex,
    nextCursor, cursorHistory, setSearchInput, submitSearch, clearSearch, retry, loadOlder, loadNewer,
    refreshInBackground, canLoadOlder: nextCursor !== null }
}
