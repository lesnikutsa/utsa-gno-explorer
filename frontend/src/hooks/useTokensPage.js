import { useCallback, useEffect, useRef, useState } from 'react'
import { getAssets, getNativeToken, getNftActivity, getTokens, getTokenSupply } from '../services/api'
import { TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS } from './useTokensAutoRefresh'

export const PAGE_SIZE = 50
export const TOKEN_ACTIVITY_WINDOWS = ['24h', '7d', '30d']

export function useTokensPage() {
  const [items, setItems] = useState([])
  const [assetFilter, setAssetFilter] = useState('all')
  const currentAssetFilter = useRef('all')
  const [summary, setSummary] = useState(null)
  const [topActivity, setTopActivity] = useState(null)
  const [activityWindow, setActivityWindow] = useState('24h')
  const [availableActivityWindows, setAvailableActivityWindows] = useState([])
  const [activityLoading, setActivityLoading] = useState(true)
  const [activityError, setActivityError] = useState(false)
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
  const currentActivityWindow = useRef('24h')
  const activityController = useRef(null)
  const activityRequestId = useRef(0)
  const supplyCache = useRef(new Map())
  const [supplies, setSupplies] = useState({})
  const [nftActivity, setNftActivity] = useState({})

  const loadNftActivity = useCallback(async (assetItems, standard, signal) => {
    if (standard !== 'grc721' || !assetItems.length) return {}
    try {
      const response = await getNftActivity(assetItems.map((item) => item.path), { signal })
      return Object.fromEntries((response.items ?? []).map((item) => [item.path, item]))
    } catch (error) {
      if (error?.name === 'AbortError') throw error
      return Object.fromEntries(assetItems.map((item) => [item.path, { path: item.path, available: false }]))
    }
  }, [])

  const loadPage = useCallback(async (request) => {
    const attempted = { ...request, history: request.history ? [...request.history] : undefined }
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    foregroundActive.current = true
    setLoading(true); setError(false)
    try {
      const response = await getAssets({ limit: PAGE_SIZE, q: request.search,
        standard: request.standard ?? currentAssetFilter.current,
        beforeActivityHeight: request.cursor?.activityHeight, beforePath: request.cursor?.path,
        signal: activeController.signal })
      const pageItems = (response.items ?? []).slice(0, PAGE_SIZE)
      const nextNftActivity = await loadNftActivity(pageItems, request.standard ?? currentAssetFilter.current, activeController.signal)
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNext = pagination.next_before_activity_height !== null && pagination.next_before_activity_height !== undefined
        && pagination.next_before_path !== null && pagination.next_before_path !== undefined
      setItems(pageItems); setNftActivity(nextNftActivity); setSummary(response.summary ?? null)
      setNextCursor(hasNext ? { activityHeight: pagination.next_before_activity_height, path: pagination.next_before_path } : null)
      setPageIndex(request.targetIndex); if (request.history) setCursorHistory(request.history)
      failedRequest.current = null; setHealthState('healthy')
      hasData.current = true
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current || requestError?.name === 'AbortError') return
      failedRequest.current = attempted; setError(true); setHealthState('error')
    } finally {
      if (id === requestId.current) foregroundActive.current = false
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [loadNftActivity])

  const refreshInBackground = useCallback(async () => {
    if (foregroundActive.current || controller.current?.background || activityController.current) return
    const activeController = new AbortController()
    activeController.background = true
    controller.current = activeController
    const id = ++requestId.current
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; activeController.abort() }, TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS)
    try {
      const [response, tokenResponse, nativeResponse] = await Promise.all([
        getAssets({ limit: PAGE_SIZE, q: appliedSearch, standard: currentAssetFilter.current, signal: activeController.signal }),
        getTokens({ limit: 3, activityWindow: currentActivityWindow.current, signal: activeController.signal }),
        getNativeToken({ signal: activeController.signal }).catch(() => null),
      ])
      const pageItems = (response.items ?? []).slice(0, PAGE_SIZE)
      const nextNftActivity = await loadNftActivity(pageItems, currentAssetFilter.current, activeController.signal)
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNext = pagination.next_before_activity_height != null && pagination.next_before_path != null
      setItems(pageItems)
      setNftActivity(nextNftActivity)
      setSummary(response.summary ?? null)
      setTopActivity(Array.isArray(tokenResponse.top_activity) ? tokenResponse.top_activity.slice(0, 3) : null)
      setAvailableActivityWindows(Array.isArray(tokenResponse.source?.available_activity_windows) ? tokenResponse.source.available_activity_windows : [])
      setActivityError(false)
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
  }, [appliedSearch, loadNftActivity])

  const loadActivityWindow = useCallback(async (nextWindow) => {
    if (!TOKEN_ACTIVITY_WINDOWS.includes(nextWindow)) return
    if (controller.current?.background) controller.current.abort()
    activityController.current?.abort()
    const activeController = new AbortController()
    activityController.current = activeController
    const id = ++activityRequestId.current
    currentActivityWindow.current = nextWindow
    setActivityWindow(nextWindow)
    setTopActivity(null); setActivityLoading(true); setActivityError(false)
    try {
      const cursor = cursorHistory[pageIndex]
      const response = await getTokens({ limit: PAGE_SIZE, q: appliedSearch, activityWindow: nextWindow,
        beforeActivityHeight: cursor?.activityHeight, beforePath: cursor?.path, signal: activeController.signal })
      if (!mounted.current || id !== activityRequestId.current || currentActivityWindow.current !== nextWindow) return
      setTopActivity(Array.isArray(response.top_activity) ? response.top_activity.slice(0, 3) : null)
      setAvailableActivityWindows(Array.isArray(response.source?.available_activity_windows) ? response.source.available_activity_windows : [])
    } catch (requestError) {
      if (!mounted.current || id !== activityRequestId.current || requestError?.name === 'AbortError') return
      setActivityError(true)
    } finally {
      if (id === activityRequestId.current) {
        activityController.current = null
        if (mounted.current) setActivityLoading(false)
      }
    }
  }, [appliedSearch, cursorHistory, pageIndex])

  const selectActivityWindow = useCallback((nextWindow) => {
    if (nextWindow === currentActivityWindow.current) return
    loadActivityWindow(nextWindow)
  }, [loadActivityWindow])

  const resetAndLoad = useCallback((search, standard = currentAssetFilter.current) => {
    const history = [null]
    setCursorHistory(history); setPageIndex(0); setNextCursor(null)
    loadPage({ cursor: null, targetIndex: 0, history, search, standard, activityWindow: currentActivityWindow.current })
  }, [loadPage])
  const submitSearch = useCallback((event) => {
    event?.preventDefault(); const search = searchInput.trim()
    setSearchInput(search); setAppliedSearch(search); resetAndLoad(search)
  }, [resetAndLoad, searchInput])
  const clearSearch = useCallback(() => { setSearchInput(''); setAppliedSearch(''); resetAndLoad('') }, [resetAndLoad])
  const selectAssetFilter = useCallback((standard) => {
    if (!['all', 'grc20', 'grc721'].includes(standard) || standard === currentAssetFilter.current) return
    currentAssetFilter.current = standard; setAssetFilter(standard); resetAndLoad(appliedSearch, standard)
  }, [appliedSearch, resetAndLoad])
  const loadOlder = useCallback(() => {
    if (loading || !nextCursor) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage({ cursor: nextCursor, targetIndex: pageIndex + 1, history, search: appliedSearch, activityWindow: currentActivityWindow.current })
  }, [appliedSearch, cursorHistory, loadPage, loading, nextCursor, pageIndex])
  const loadNewer = useCallback(() => {
    if (loading || pageIndex === 0) return
    loadPage({ cursor: cursorHistory[pageIndex - 1], targetIndex: pageIndex - 1, search: appliedSearch, activityWindow: currentActivityWindow.current })
  }, [appliedSearch, cursorHistory, loadPage, loading, pageIndex])
  const retry = useCallback(() => { if (failedRequest.current) loadPage(failedRequest.current) }, [loadPage])

  useEffect(() => {
    mounted.current = true
    loadPage({ cursor: null, targetIndex: 0, history: [null], search: '' })
    loadActivityWindow('24h')
    return () => { mounted.current = false; requestId.current += 1; activityRequestId.current += 1;
      controller.current?.abort(); activityController.current?.abort() }
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
    const pending = items.filter((item) => item.standard === 'grc20' && !supplyCache.current.has(item.path))
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

  return { items, supplies, nftActivity, summary, topActivity, nativeToken, activityWindow, availableActivityWindows, assetFilter, selectAssetFilter,
    activityLoading, activityError,
    searchInput, appliedSearch, loading, error, healthState, pageIndex,
    nextCursor, cursorHistory, setSearchInput, submitSearch, clearSearch, retry, loadOlder, loadNewer,
    refreshInBackground, selectActivityWindow, retryActivity: () => loadActivityWindow(currentActivityWindow.current),
    canLoadOlder: nextCursor !== null }
}
