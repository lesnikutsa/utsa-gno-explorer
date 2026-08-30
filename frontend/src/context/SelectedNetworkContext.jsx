import { createContext, useContext, useMemo } from 'react'
import { getNetworkFromPath, networkOverviewPath } from '../config/networkRegistry'
import { navigateInternal, usePathname } from '../utils/navigation'

const SelectedNetworkContext = createContext(null)

export function SelectedNetworkProvider({ children }) {
  const pathname = usePathname()
  const selectedNetwork = getNetworkFromPath(pathname)
  const value = useMemo(() => ({
    selectedNetwork,
    selectNetwork: (networkId) => {
      const network = getNetworkFromPath(`/networks/${networkId}`)
      if (network?.id === networkId) navigateInternal(networkOverviewPath(network))
    },
  }), [selectedNetwork])

  return <SelectedNetworkContext.Provider value={value}>{children}</SelectedNetworkContext.Provider>
}

export function useSelectedNetwork() {
  const context = useContext(SelectedNetworkContext)
  if (!context) throw new Error('useSelectedNetwork must be used within SelectedNetworkProvider')
  return context
}
