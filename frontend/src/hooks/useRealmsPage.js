import { useCallback, useEffect, useRef, useState } from 'react'
import { getRealms } from '../services/api'

export const PAGE_SIZE = 25

export function useRealmsPage() {
  const [items, setItems] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [snapshotMissing, setSnapshotMissing] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [kind, setKindState] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [pageIndex, setPageIndex] = useState(0)
  const [nextCursor, setNextCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const mounted = useRef(false)
  const requestId = useRef(0)
  const controller = useRef(null)
  const failedRequest = useRef(null)

  const loadPage = useCallback(async (request) => {
    const attemptedRequest = { ...request, history: request.history ? [...request.history] : undefined }
    controller.current?.abort()
    const activeController = new AbortController()
    controller.current = activeController
    const id = ++requestId.current
    setLoading(true)
    setItems([])
    setError(false)
    setSnapshotMissing(false)
    try {
      const response = await getRealms({
        limit: PAGE_SIZE,
        kind: request.kind,
        q: request.search,
        beforeActivityHeight: request.cursor?.activityHeight,
        beforePath: request.cursor?.path,
        signal: activeController.signal,
      })
      if (!mounted.current || id !== requestId.current) return
      const pagination = response.pagination ?? {}
      const hasNextCursor = pagination.next_before_activity_height !== null
        && pagination.next_before_activity_height !== undefined
        && pagination.next_before_path !== null
        && pagination.next_before_path !== undefined
      setItems((response.items ?? []).slice(0, PAGE_SIZE))
      setSummary(response.summary ?? null)
      setNextCursor(hasNextCursor ? { activityHeight: pagination.next_before_activity_height, path: pagination.next_before_path } : null)
      setPageIndex(request.targetIndex)
      if (request.history) setCursorHistory(request.history)
      failedRequest.current = null
      setHealthState('healthy')
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current || requestError?.name === 'AbortError') return
      failedRequest.current = attemptedRequest
      if (requestError?.status === 404) {
        setSnapshotMissing(true)
        setHealthState('healthy')
      } else {
        setError(true)
        setHealthState('error')
      }
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

  const resetAndLoad = useCallback((nextKind, nextSearch) => {
    const history = [null]
    setCursorHistory(history)
    setPageIndex(0)
    setNextCursor(null)
    loadPage({ cursor: null, targetIndex: 0, history, kind: nextKind, search: nextSearch })
  }, [loadPage])

  const selectKind = useCallback((nextKind) => {
    if (nextKind === kind) return
    setKindState(nextKind)
    resetAndLoad(nextKind, appliedSearch)
  }, [appliedSearch, kind, resetAndLoad])
  const submitSearch = useCallback((event) => {
    event?.preventDefault()
    const nextSearch = searchInput.trim()
    setSearchInput(nextSearch)
    setAppliedSearch(nextSearch)
    resetAndLoad(kind, nextSearch)
  }, [kind, resetAndLoad, searchInput])
  const clearSearch = useCallback(() => {
    setSearchInput('')
    setAppliedSearch('')
    resetAndLoad(kind, '')
  }, [kind, resetAndLoad])
  const retry = useCallback(() => {
    if (failedRequest.current) loadPage(failedRequest.current)
  }, [loadPage])
  const loadOlder = useCallback(() => {
    if (loading || !nextCursor) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage({ cursor: nextCursor, targetIndex: pageIndex + 1, history, kind, search: appliedSearch })
  }, [appliedSearch, cursorHistory, kind, loadPage, loading, nextCursor, pageIndex])
  const loadNewer = useCallback(() => {
    if (loading || pageIndex === 0) return
    loadPage({ cursor: cursorHistory[pageIndex - 1], targetIndex: pageIndex - 1, kind, search: appliedSearch })
  }, [appliedSearch, cursorHistory, kind, loadPage, loading, pageIndex])

  useEffect(() => {
    mounted.current = true
    loadPage({ cursor: null, targetIndex: 0, history: [null], kind: 'all', search: '' })
    return () => {
      mounted.current = false
      requestId.current += 1
      controller.current?.abort()
    }
  }, [loadPage])

  return { items, summary, loading, error, snapshotMissing, healthState, kind, searchInput, appliedSearch, pageIndex, nextCursor, cursorHistory, setSearchInput, selectKind, submitSearch, clearSearch, retry, loadOlder, loadNewer, canLoadOlder: nextCursor !== null }
}
