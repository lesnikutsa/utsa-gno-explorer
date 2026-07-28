import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposal } from '../services/api'
import { isValidGovernanceDetailResponse, parseProposalRouteId } from '../utils/governance'

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

  const load = useCallback(async () => {
    if (proposalId === null) return
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
    }
  }, [proposalId])

  useEffect(() => {
    mounted.current = true
    load()
    return () => {
      mounted.current = false
      requestId.current += 1
    }
  }, [load])

  return {
    ...state,
    proposalId,
    invalidProposalId: proposalId === null,
    retry: load,
  }
}
