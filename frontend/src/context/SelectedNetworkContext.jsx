import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { DEFAULT_NETWORK_ID, getNetworkById as getStaticNetworkById,
  supportedNetworks as staticNetworks } from '../config/networkRegistry'
import { normalizePublicCosmosNetwork } from '../utils/publicNetworkRegistry'
import { networkIdForPath } from '../utils/networkSelection'
import { INTERNAL_NAVIGATION_EVENT } from '../utils/navigation'

const SelectedNetworkContext = createContext(null)

export function SelectedNetworkProvider({ children }) {
  const [cosmosNetworks, setCosmosNetworks] = useState([])
  const [networksLoading, setNetworksLoading] = useState(true)
  const [networksError, setNetworksError] = useState(null)
  const supportedNetworks = useMemo(() => [...staticNetworks, ...cosmosNetworks], [cosmosNetworks])
  const getNetworkById = useCallback((networkId) => (
    getStaticNetworkById(networkId) || cosmosNetworks.find(({ id }) => id === networkId) || null
  ), [cosmosNetworks])
  const networkForCurrentUrl = () => networkIdForPath(window.location.pathname, getNetworkById, DEFAULT_NETWORK_ID)
  const [selectedNetworkId, setSelectedNetworkId] = useState(networkForCurrentUrl)
  const selectedNetwork = getNetworkById(selectedNetworkId)
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/networks', { signal: controller.signal, headers: { Accept: 'application/json' } })
      .then((response) => {
        if (!response.ok) throw new Error('Network registry is unavailable')
        return response.json()
      })
      .then((payload) => {
        const networks = Array.isArray(payload?.networks)
          ? payload.networks.map(normalizePublicCosmosNetwork).filter(Boolean) : []
        if (networks.length !== payload?.networks?.length) throw new Error('Network registry is invalid')
        setCosmosNetworks(networks)
        const lookup = (id) => getStaticNetworkById(id) || networks.find((network) => network.id === id) || null
        setSelectedNetworkId(networkIdForPath(window.location.pathname, lookup, DEFAULT_NETWORK_ID))
        setNetworksLoading(false)
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setNetworksError(error.message)
          setNetworksLoading(false)
        }
      })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    const synchronizeWithUrl = () => setSelectedNetworkId(networkForCurrentUrl())
    window.addEventListener('popstate', synchronizeWithUrl)
    window.addEventListener(INTERNAL_NAVIGATION_EVENT, synchronizeWithUrl)
    synchronizeWithUrl()
    return () => {
      window.removeEventListener('popstate', synchronizeWithUrl)
      window.removeEventListener(INTERNAL_NAVIGATION_EVENT, synchronizeWithUrl)
    }
  }, [getNetworkById])
  const selectNetwork = useCallback((networkId) => {
    if (getNetworkById(networkId)) setSelectedNetworkId(networkId)
  }, [getNetworkById])
  const value = useMemo(() => ({
    selectedNetwork,
    selectNetwork,
    supportedNetworks,
    getNetworkById,
    networksLoading,
    networksError,
  }), [selectedNetwork, selectNetwork, supportedNetworks, getNetworkById, networksLoading, networksError])

  return <SelectedNetworkContext.Provider value={value}>{children}</SelectedNetworkContext.Provider>
}

export function useSelectedNetwork() {
  const context = useContext(SelectedNetworkContext)
  if (!context) throw new Error('useSelectedNetwork must be used within SelectedNetworkProvider')
  return context
}
