import { useEffect, useState } from 'react'
import { getCosmosTransactionByHash } from '../services/api'
import { INTERNAL_NAVIGATION_EVENT } from '../utils/navigation'

export function CosmosTransactionHashRoute({ network, txHash }) {
  const [state, setState] = useState({ loading: true, error: null })

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15000)

    setState({ loading: true, error: null })
    getCosmosTransactionByHash({ networkId: network.id, txHash, signal: controller.signal })
      .then((data) => {
        if (!active) return
        const destination = `/networks/${network.id}/blocks/${data.height}/transactions/${data.index}`
        window.history.replaceState({}, '', destination)
        window.scrollTo(0, 0)
        window.dispatchEvent(new Event(INTERNAL_NAVIGATION_EVENT))
      })
      .catch((error) => {
        if (!active) return
        const message = error?.name === 'AbortError'
          ? 'Request timed out'
          : error?.detail || error?.message || 'Transaction not found or temporarily unavailable.'
        setState({ loading: false, error: message })
      })
      .finally(() => window.clearTimeout(timeout))

    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [network.id, txHash])

  if (state.loading) return <p>Loading transaction…</p>
  return <p className="cosmos-error">{state.error || 'Transaction not found or temporarily unavailable.'}</p>
}
