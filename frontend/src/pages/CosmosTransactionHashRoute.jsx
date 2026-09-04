import { useEffect } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { INTERNAL_NAVIGATION_EVENT } from '../utils/navigation'

export function CosmosTransactionHashRoute({ network, txHash }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/transactions/${encodeURIComponent(txHash)}`, null)

  useEffect(() => {
    if (!resource.data) return
    const destination = `/networks/${network.id}/blocks/${resource.data.height}/transactions/${resource.data.index}`
    window.history.replaceState({}, '', destination)
    window.scrollTo(0, 0)
    window.dispatchEvent(new Event(INTERNAL_NAVIGATION_EVENT))
  }, [network.id, resource.data])

  if (resource.loading || resource.data) return <p>Loading transaction…</p>
  return <p className="cosmos-error">{resource.error || 'Transaction not found or temporarily unavailable.'}</p>
}
