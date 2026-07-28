import { useCallback, useEffect, useRef, useState } from 'react'
import { getGovernanceProposal } from '../services/api'
import { parseProposalRouteId } from '../utils/governance'

export function useGovernanceDetail(routeProposalId) {
  const proposalId = parseProposalRouteId(routeProposalId)
  const [state, setState] = useState({ proposal: null, source: {}, loading: proposalId !== null, error: false, notFound: false, healthState: proposalId === null ? 'healthy' : 'loading' })
  const mounted = useRef(false); const requestId = useRef(0)
  const load = useCallback(async () => {
    if (proposalId === null) return
    const id = ++requestId.current; setState((old) => ({ ...old, loading: true, error: false, notFound: false }))
    try { const response = await getGovernanceProposal(proposalId); if (mounted.current && id === requestId.current) setState({ proposal: response.proposal ?? null, source: response.source ?? {}, loading: false, error: false, notFound: false, healthState: 'healthy' }) }
    catch (cause) { if (mounted.current && id === requestId.current) setState({ proposal: null, source: {}, loading: false, error: cause.status !== 404, notFound: cause.status === 404, healthState: cause.status === 404 ? 'healthy' : 'error' }) }
  }, [proposalId])
  useEffect(() => { mounted.current = true; load(); return () => { mounted.current = false; requestId.current += 1 } }, [load])
  return { ...state, proposalId, invalidProposalId: proposalId === null, retry: load }
}
