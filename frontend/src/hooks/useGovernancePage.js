import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposals } from '../services/api'
import { isValidGovernanceListResponse } from '../utils/governance'

export const PAGE_SIZE = 25
export const GOVERNANCE_LIST_POLL_MS = 30_000
const hasCursor = (value) => value !== null && value !== undefined

export function useGovernancePage() {
  const [proposals, setProposals] = useState([])
  const [source, setSource] = useState({})
  const [statusCounts, setStatusCounts] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [snapshotMissing, setSnapshotMissing] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const [nextCursor, setNextCursor] = useState(null)
  const [cursorHistory, setCursorHistory] = useState([null])
  const [pageIndex, setPageIndex] = useState(0)
  const mounted = useRef(false)
  const requestId = useRef(0)
  const failedRequest = useRef(null)
  const pollTimeout = useRef(null)
  const inFlight = useRef(false)
  const pageIndexRef = useRef(0)
  const hasLoadedData = useRef(false)
  const backgroundRefreshRef = useRef(null)

  const clearPollTimeout = useCallback(() => {
    if (pollTimeout.current !== null) {
      window.clearTimeout(pollTimeout.current)
      pollTimeout.current = null
    }
  }, [])

  const schedulePoll = useCallback(() => {
    clearPollTimeout()
    if (!mounted.current || pageIndexRef.current !== 0 || !hasLoadedData.current
      || document.visibilityState !== 'visible' || inFlight.current) return
    pollTimeout.current = window.setTimeout(() => {
      pollTimeout.current = null
      backgroundRefreshRef.current?.()
    }, GOVERNANCE_LIST_POLL_MS)
  }, [clearPollTimeout])

  const clearPublicData = () => {
    setProposals([])
    setSource({})
    setStatusCounts({})
    setNextCursor(null)
  }

  const loadPage = useCallback(async (cursor, targetIndex, history) => {
    if (inFlight.current) return
    clearPollTimeout()
    inFlight.current = true
    const attemptedRequest = { cursor, targetIndex, history }
    const id = ++requestId.current
    setLoading(true)
    setError(false)
    setSnapshotMissing(false)
    setHealthState('loading')
    clearPublicData()

    try {
      const response = await getGovernanceProposals({
        limit: PAGE_SIZE,
        beforeProposalId: cursor,
      })
      if (!mounted.current || id !== requestId.current) return
      if (!isValidGovernanceListResponse(response)) throw new Error('Invalid Governance response')

      setProposals(response.items.slice(0, PAGE_SIZE))
      setSource(response.source)
      setStatusCounts(response.status_counts)
      setNextCursor(response.pagination.next_before_proposal_id)
      setPageIndex(targetIndex)
      pageIndexRef.current = targetIndex
      hasLoadedData.current = true
      if (history) setCursorHistory(history)
      failedRequest.current = null
      setHealthState('healthy')
    } catch (cause) {
      if (!mounted.current || id !== requestId.current) return
      clearPublicData()
      hasLoadedData.current = false
      if (cause.status === 404) {
        setPageIndex(0)
        setCursorHistory([null])
        setSnapshotMissing(true)
        setError(false)
        failedRequest.current = null
        setHealthState('healthy')
      } else {
        setError(true)
        setSnapshotMissing(false)
        failedRequest.current = attemptedRequest
        setHealthState('error')
      }
    } finally {
      if (id === requestId.current) inFlight.current = false
      if (mounted.current && id === requestId.current) {
        setLoading(false)
        schedulePoll()
      }
    }
  }, [clearPollTimeout, schedulePoll])

  const refreshInBackground = useCallback(async () => {
    if (!mounted.current || inFlight.current || pageIndexRef.current !== 0
      || !hasLoadedData.current || document.visibilityState !== 'visible') return
    clearPollTimeout()
    inFlight.current = true
    const id = ++requestId.current
    try {
      const response = await getGovernanceProposals({ limit: PAGE_SIZE, beforeProposalId: null })
      if (!mounted.current || id !== requestId.current) return
      if (!isValidGovernanceListResponse(response)) throw new Error('Invalid Governance response')
      setProposals(response.items.slice(0, PAGE_SIZE))
      setSource(response.source)
      setStatusCounts(response.status_counts)
      setNextCursor(response.pagination.next_before_proposal_id)
      setHealthState('healthy')
    } catch {
      if (mounted.current && id === requestId.current) setHealthState('degraded')
    } finally {
      if (id === requestId.current) inFlight.current = false
      if (mounted.current && id === requestId.current) schedulePoll()
    }
  }, [clearPollTimeout, schedulePoll])

  backgroundRefreshRef.current = refreshInBackground

  const retry = useCallback(() => {
    const request = failedRequest.current
    if (request) loadPage(request.cursor, request.targetIndex, request.history)
  }, [loadPage])

  const loadOlder = useCallback(() => {
    if (loading || error || snapshotMissing || !hasCursor(nextCursor)) return
    const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]
    loadPage(nextCursor, pageIndex + 1, history)
  }, [cursorHistory, error, loadPage, loading, nextCursor, pageIndex, snapshotMissing])

  const loadNewer = useCallback(() => {
    if (loading || error || snapshotMissing || pageIndex === 0) return
    loadPage(cursorHistory[pageIndex - 1], pageIndex - 1)
  }, [cursorHistory, error, loadPage, loading, pageIndex, snapshotMissing])

  useEffect(() => {
    mounted.current = true
    loadPage(null, 0)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') clearPollTimeout()
      else refreshInBackground()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      mounted.current = false
      requestId.current += 1
      inFlight.current = false
      clearPollTimeout()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [clearPollTimeout, loadPage, refreshInBackground])

  return {
    proposals,
    source,
    statusCounts,
    loading,
    error,
    snapshotMissing,
    healthState,
    nextCursor,
    cursorHistory,
    pageIndex,
    canLoadOlder: !error && !snapshotMissing && hasCursor(nextCursor),
    retry,
    loadOlder,
    loadNewer,
  }
}
