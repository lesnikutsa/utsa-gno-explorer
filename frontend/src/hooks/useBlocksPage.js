import { useCallback, useEffect, useRef, useState } from 'react'
import { getBlock, getBlocks } from '../services/api'

export const BLOCKS_POLL_MS = 5_000
const PAGE_SIZE = 25
const HEX_HASH_PATTERN = /^(?:0x)?[0-9a-fA-F]{64}$/
const HEIGHT_PATTERN = /^[0-9]+$/

export function useBlocksPage() {
  const [blocks, setBlocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false)
  const [manualRefreshing, setManualRefreshing] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [error, setError] = useState(false)
  const [nextBeforeHeight, setNextBeforeHeight] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const [pageIndex, setPageIndex] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchNotFound, setSearchNotFound] = useState(false)
  const [nextRefreshAt, setNextRefreshAt] = useState(null)
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const requestId = useRef(0)
  const timerId = useRef(null)
  const blocksRef = useRef([])
  const pageIndexRef = useRef(0)
  const searchQueryRef = useRef('')

  const clearRefreshTimer = useCallback(() => {
    if (timerId.current !== null) window.clearTimeout(timerId.current)
    timerId.current = null
    if (mounted.current) setNextRefreshAt(null)
  }, [])

  const scheduleRefresh = useCallback(() => {
    if (!mounted.current || pageIndexRef.current !== 0 || searchQueryRef.current) return
    setNextRefreshAt(Date.now() + BLOCKS_POLL_MS)
  }, [])

  const loadPage = useCallback(async (cursor, { background = false, manual = false, targetIndex = 0, history } = {}) => {
    if (inFlight.current) return false
    clearRefreshTimer()
    inFlight.current = true
    const id = ++requestId.current

    if ((background || manual) && blocksRef.current.length) {
      if (background) setBackgroundRefreshing(true)
      if (manual) setManualRefreshing(true)
    } else {
      setLoading(true)
      setBlocks([])
      blocksRef.current = []
    }
    setError(false)

    try {
      const response = await getBlocks({ limit: PAGE_SIZE, beforeHeight: cursor })
      if (!mounted.current || id !== requestId.current) return false
      const rows = response.items ?? []
      setBlocks(rows)
      blocksRef.current = rows
      setNextBeforeHeight(response.pagination?.next_before_height ?? null)
      setPageIndex(targetIndex)
      pageIndexRef.current = targetIndex
      if (history) setCursorHistory(history)
      setHealthState('healthy')
      return true
    } catch {
      if (!mounted.current || id !== requestId.current) return false
      setError(true)
      setHealthState(blocksRef.current.length ? 'degraded' : 'error')
      return false
    } finally {
      if (mounted.current && id === requestId.current) {
        setLoading(false)
        setBackgroundRefreshing(false)
        setManualRefreshing(false)
        inFlight.current = false
        if (pageIndexRef.current === 0 && !searchQueryRef.current) scheduleRefresh()
      }
    }
  }, [clearRefreshTimer, scheduleRefresh])

  const refresh = useCallback(() => loadPage(null, { manual: blocksRef.current.length > 0 }), [loadPage])

  const loadOlder = useCallback(async () => {
    if (inFlight.current || nextBeforeHeight === null) return
    const nextHistory = [...cursorHistory.slice(0, pageIndex + 1), nextBeforeHeight]
    await loadPage(nextBeforeHeight, { targetIndex: pageIndex + 1, history: nextHistory })
  }, [cursorHistory, loadPage, nextBeforeHeight, pageIndex])

  const loadNewer = useCallback(async () => {
    if (inFlight.current || pageIndex === 0) return
    const targetIndex = pageIndex - 1
    await loadPage(cursorHistory[targetIndex], { targetIndex })
  }, [cursorHistory, loadPage, pageIndex])

  const submitSearch = useCallback(async (event) => {
    event?.preventDefault()
    const query = searchInput.trim()
    if (!query || inFlight.current) return

    clearRefreshTimer()
    searchQueryRef.current = query
    setSearchQuery(query)
    setSearchNotFound(false)
    setError(false)
    setLoading(true)
    setBlocks([])
    blocksRef.current = []
    inFlight.current = true
    const id = ++requestId.current

    try {
      let rows
      if (!HEX_HASH_PATTERN.test(query) && HEIGHT_PATTERN.test(query) && Number(query) > 0) {
        rows = [await getBlock(query)]
      } else {
        const response = await getBlocks({ limit: PAGE_SIZE, hash: query })
        rows = (response.items ?? []).slice(0, 1)
      }
      if (!mounted.current || id !== requestId.current) return
      setBlocks(rows)
      blocksRef.current = rows
      setSearchNotFound(rows.length === 0)
      setHealthState('healthy')
    } catch (requestError) {
      if (!mounted.current || id !== requestId.current) return
      if (requestError.status === 404) {
        setSearchNotFound(true)
        setHealthState('healthy')
      } else {
        setError(true)
        setHealthState('error')
      }
    } finally {
      if (mounted.current && id === requestId.current) {
        setLoading(false)
        inFlight.current = false
      }
    }
  }, [clearRefreshTimer, searchInput])

  const resetSearch = useCallback(() => {
    if (inFlight.current) return
    searchQueryRef.current = ''
    setSearchInput('')
    setSearchQuery('')
    setSearchNotFound(false)
    setCursorHistory([null])
    loadPage(null, { targetIndex: 0, history: [null] })
  }, [loadPage])

  useEffect(() => {
    mounted.current = true
    loadPage(null)
    return () => {
      mounted.current = false
      requestId.current += 1
      inFlight.current = false
      if (timerId.current !== null) window.clearTimeout(timerId.current)
    }
  }, [loadPage])

  useEffect(() => {
    if (!nextRefreshAt || pageIndex !== 0 || searchQuery) return undefined
    timerId.current = window.setTimeout(() => {
      timerId.current = null
      loadPage(null, { background: true })
    }, Math.max(0, nextRefreshAt - Date.now()))
    return () => {
      if (timerId.current !== null) window.clearTimeout(timerId.current)
      timerId.current = null
    }
  }, [loadPage, nextRefreshAt, pageIndex, searchQuery])

  const searchMode = Boolean(searchQuery)
  return {
    blocks,
    loading,
    backgroundRefreshing,
    manualRefreshing,
    healthState,
    error,
    nextBeforeHeight,
    pageIndex,
    currentCursor: cursorHistory[pageIndex] ?? null,
    searchInput,
    setSearchInput,
    searchQuery,
    searchMode,
    searchNotFound,
    nextRefreshAt,
    loadOlder,
    loadNewer,
    refresh,
    submitSearch,
    resetSearch,
  }
}
