import { useEffect, useState } from 'react'
import { getHealth } from '../services/api'

export const CHAIN_IDENTITY_POLL_MS = 30_000

export function useChainIdentity() {
  const [chainId, setChainId] = useState(null)

  useEffect(() => {
    let mounted = true
    let refreshTimer = null

    const requestChainIdentity = async () => {
      try {
        const health = await getHealth()
        const nextChainId = typeof health?.chain_id === 'string' ? health.chain_id.trim() : ''
        if (mounted && nextChainId) setChainId(nextChainId)
      } catch {
        // Chain identity is optional UI metadata; retain the last successful value.
      } finally {
        if (mounted) refreshTimer = window.setTimeout(requestChainIdentity, CHAIN_IDENTITY_POLL_MS)
      }
    }

    requestChainIdentity()

    return () => {
      mounted = false
      if (refreshTimer !== null) window.clearTimeout(refreshTimer)
    }
  }, [])

  return chainId
}
