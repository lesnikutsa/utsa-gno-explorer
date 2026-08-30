import { createContext, useContext, useMemo, useState } from 'react'
import { DEFAULT_NETWORK_ID, getNetworkById } from '../config/networkRegistry'

const SelectedNetworkContext = createContext(null)

export function SelectedNetworkProvider({ children }) {
  const [selectedNetworkId, setSelectedNetworkId] = useState(DEFAULT_NETWORK_ID)
  const selectedNetwork = getNetworkById(selectedNetworkId)
  const value = useMemo(() => ({
    selectedNetwork,
    selectNetwork: (networkId) => {
      if (getNetworkById(networkId)) setSelectedNetworkId(networkId)
    },
  }), [selectedNetwork])

  return <SelectedNetworkContext.Provider value={value}>{children}</SelectedNetworkContext.Provider>
}

export function useSelectedNetwork() {
  const context = useContext(SelectedNetworkContext)
  if (!context) throw new Error('useSelectedNetwork must be used within SelectedNetworkProvider')
  return context
}
