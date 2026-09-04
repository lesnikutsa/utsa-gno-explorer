import { useEffect, useState } from 'react'
import { getCosmosTransactionByHash } from '../services/api'

export function CosmosTransactionHashRoute({ network, txHash }) {
  const [state, setState] = useState({ loading: true, error: null })

  useEffect(() => {
    let active = true
    const controller = new AbortController()

    setState({ loading: true, error: null })
    getCosmosTransactionByHash({ networkId: network.id, txHash, signal: controller.signal })
      .then((data) => {
        if (!active) return
        const destination = `/networks/${network.id}/blocks/${data.height}/transactions/${data.index}`
        window.location.replace(destination)
      })
      .catch((error) => {
        if (!active) return
        const message = error?.detail || error?.message || 'Transaction not found or temporarily unavailable.'
        setState({ loading: false, error: message })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [network.id, txHash])

  if (state.loading) return <p>Loading transaction…</p>
  return <p className="cosmos-error">{state.error || 'Transaction not found or temporarily unavailable.'}</p>
}
