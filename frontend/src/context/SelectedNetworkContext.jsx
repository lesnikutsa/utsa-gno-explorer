import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { DEFAULT_NETWORK_ID, getNetworkById } from '../config/networkRegistry'
import { networkIdForPath } from '../utils/networkSelection'
import { INTERNAL_NAVIGATION_EVENT } from '../utils/navigation'

const SelectedNetworkContext = createContext(null)

export function SelectedNetworkProvider({ children }) {
  const networkForCurrentUrl = () => networkIdForPath(window.location.pathname, getNetworkById, DEFAULT_NETWORK_ID)
  const [selectedNetworkId, setSelectedNetworkId] = useState(networkForCurrentUrl)
  const selectedNetwork = getNetworkById(selectedNetworkId)
  useEffect(() => {
    const synchronizeWithUrl = () => setSelectedNetworkId(networkForCurrentUrl())
    window.addEventListener('popstate', synchronizeWithUrl)
    window.addEventListener(INTERNAL_NAVIGATION_EVENT, synchronizeWithUrl)
    synchronizeWithUrl()
    return () => {
      window.removeEventListener('popstate', synchronizeWithUrl)
      window.removeEventListener(INTERNAL_NAVIGATION_EVENT, synchronizeWithUrl)
    }
  }, [])
  const selectNetwork = useCallback((networkId) => {
    if (getNetworkById(networkId)) setSelectedNetworkId(networkId)
  }, [])
  const value = useMemo(() => ({
    selectedNetwork,
    selectNetwork,
  }), [selectedNetwork, selectNetwork])

  return <SelectedNetworkContext.Provider value={value}>{children}</SelectedNetworkContext.Provider>
}

export function useSelectedNetwork() {
  const context = useContext(SelectedNetworkContext)
  if (!context) throw new Error('useSelectedNetwork must be used within SelectedNetworkProvider')
  return context
}
