import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposal } from '../services/api'
import { isMutableGovernanceStatus, isValidGovernanceDetailResponse, parseProposalRouteId } from '../utils/governance'

export const GOVERNANCE_DETAIL_POLL_MS = 15_000

export function useGovernanceDetail(routeProposalId) {
  const proposalId = parseProposalRouteId(routeProposalId)
  const [state, setState] = useState({
    proposal: null,
    source: {},
    loading: proposalId !== null,
    error: false,
    notFound: false,
    snapshotMissing: false,
    healthState: proposalId === null ? 'healthy' : 'loading',
  })
  const mounted = useRef(false)
  const requestId = useRef(0)
  const pollTimeout = useRef(null)
  const inFlight = useRef(false)
  const storedProposal = useRef(null)
  const backgroundRefreshRef = useRef(null)

  const clearPollTimeout = useCallback(() => {
    if (pollTimeout.current !== null) {
      window.clearTimeout(pollTimeout.current)
      pollTimeout.current = null
    }
  }, [])

  const schedulePoll = useCallback(() => {
    clearPollTimeout()
    if (!mounted.current || proposalId === null || !storedProposal.current
      || !isMutableGovernanceStatus(storedProposal.current.status)
      || document.visibilityState !== 'visible' || inFlight.current) return
    pollTimeout.current = window.setTimeout(() => {
      pollTimeout.current = null
      backgroundRefreshRef.current?.()
    }, GOVERNANCE_DETAIL_POLL_MS)
  }, [clearPollTimeout, proposalId])

  const load = useCallback(async () => {
    if (proposalId === null) return
    if (inFlight.current) return
    clearPollTimeout()
    inFlight.current = true
    const id = ++requestId.current
    setState({
      proposal: null,
      source: {},
      loading: true,
      error: false,
      notFound: false,
      snapshotMissing: false,
      healthState: 'loading',
    })

    try {
      const response = await getGovernanceProposal(proposalId)
      if (!mounted.current || id !== requestId.current) return
      if (!isValidGovernanceDetailResponse(response, proposalId)) {
        throw new Error('Invalid Governance proposal response')
      }
      setState({
        proposal: response.proposal,
        source: response.source,
        loading: false,
        error: false,
        notFound: false,
        snapshotMissing: false,
        healthState: 'healthy',
      })
      storedProposal.current = response.proposal
    } catch (cause) {
      if (!mounted.current || id !== requestId.current) return
      const snapshotMissing = cause.status === 404
        && cause.detail === 'Governance snapshot not found'
      const notFound = cause.status === 404
        && cause.detail === 'Governance proposal not found'
      const error = !snapshotMissing && !notFound
      setState({
        proposal: null,
        source: {},
        loading: false,
        error,
        notFound,
        snapshotMissing,
        healthState: error ? 'error' : 'healthy',
      })
      storedProposal.current = null
    } finally {
      if (id === requestId.current) inFlight.current = false
      if (mounted.current && id === requestId.current) schedulePoll()
    }
  }, [clearPollTimeout, proposalId, schedulePoll])

  const refreshInBackground = useCallback(async () => {
    if (!mounted.current || proposalId === null || inFlight.current || !storedProposal.current
      || !isMutableGovernanceStatus(storedProposal.current.status)
      || document.visibilityState !== 'visible') return
    clearPollTimeout()
    inFlight.current = true
    const id = ++requestId.current
    try {
      const response = await getGovernanceProposal(proposalId)
      if (!mounted.current || id !== requestId.current) return
      if (!isValidGovernanceDetailResponse(response, proposalId)) {
        throw new Error('Invalid Governance proposal response')
      }
      storedProposal.current = response.proposal
      setState({
        proposal: response.proposal,
        source: response.source,
        loading: false,
        error: false,
        notFound: false,
        snapshotMissing: false,
        healthState: 'healthy',
      })
    } catch {
      if (mounted.current && id === requestId.current) {
        setState((current) => ({ ...current, healthState: 'degraded' }))
      }
    } finally {
      if (id === requestId.current) inFlight.current = false
      if (mounted.current && id === requestId.current) schedulePoll()
    }
  }, [clearPollTimeout, proposalId, schedulePoll])

  backgroundRefreshRef.current = refreshInBackground

  useEffect(() => {
    mounted.current = true
    load()
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
  }, [clearPollTimeout, load, refreshInBackground])

  return {
    ...state,
    proposalId,
    invalidProposalId: proposalId === null,
    retry: load,
  }
}
