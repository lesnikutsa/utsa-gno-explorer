import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposals } from '../services/api'
import { isValidGovernanceListResponse } from '../utils/governance'

export const PAGE_SIZE = 25
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

  const clearPublicData = () => {
    setProposals([])
    setSource({})
    setStatusCounts({})
    setNextCursor(null)
  }

  const loadPage = useCallback(async (cursor, targetIndex, history) => {
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
      if (history) setCursorHistory(history)
      failedRequest.current = null
      setHealthState('healthy')
    } catch (cause) {
      if (!mounted.current || id !== requestId.current) return
      clearPublicData()
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
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

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
    return () => {
      mounted.current = false
      requestId.current += 1
    }
  }, [loadPage])

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
