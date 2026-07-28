import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposals } from '../services/api'

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

  const loadPage = useCallback(async (cursor, targetIndex, history) => {
    const attemptedRequest = { cursor, targetIndex, history }
    const id = ++requestId.current
    setLoading(true); setError(false); setSnapshotMissing(false); setProposals([])
    try {
      const response = await getGovernanceProposals({ limit: PAGE_SIZE, beforeProposalId: cursor })
      if (!mounted.current || id !== requestId.current) return
      const next = response.pagination?.next_before_proposal_id
      setProposals((response.items ?? []).slice(0, PAGE_SIZE)); setSource(response.source ?? {}); setStatusCounts(response.status_counts ?? {})
      setNextCursor(hasCursor(next) ? next : null); setPageIndex(targetIndex)
      if (history) setCursorHistory(history)
      failedRequest.current = null; setHealthState('healthy')
    } catch (cause) {
      if (!mounted.current || id !== requestId.current) return
      if (cause.status === 404) { setSnapshotMissing(true); setHealthState('healthy') }
      else { setError(true); setHealthState('error'); failedRequest.current = attemptedRequest }
    } finally { if (mounted.current && id === requestId.current) setLoading(false) }
  }, [])
  const retry = useCallback(() => { const r = failedRequest.current; if (r) loadPage(r.cursor, r.targetIndex, r.history) }, [loadPage])
  const loadOlder = useCallback(() => { if (loading || !hasCursor(nextCursor)) return; const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]; loadPage(nextCursor, pageIndex + 1, history) }, [cursorHistory, loadPage, loading, nextCursor, pageIndex])
  const loadNewer = useCallback(() => { if (!loading && pageIndex > 0) loadPage(cursorHistory[pageIndex - 1], pageIndex - 1) }, [cursorHistory, loadPage, loading, pageIndex])
  useEffect(() => { mounted.current = true; loadPage(null, 0); return () => { mounted.current = false; requestId.current += 1 } }, [loadPage])
  return { proposals, source, statusCounts, loading, error, snapshotMissing, healthState, nextCursor, cursorHistory, pageIndex, canLoadOlder: hasCursor(nextCursor), retry, loadOlder, loadNewer }
}
