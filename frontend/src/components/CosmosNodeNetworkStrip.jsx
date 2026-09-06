import { useEffect, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { getCosmosEndpointProvider, subscribeCosmosEndpointProvider } from '../utils/cosmosEndpointProvider'
import '../styles/cosmos-tx-tooltip.css'

const Detail = ({ label, value, raw }) => <div><dt>{label}</dt><dd>{raw === undefined || raw === null ? value : <span className="cosmos-data-tooltip" data-tooltip={String(raw)}>{value}</span>}</dd></div>

const formatRetainedBlocks = (count) => {
  if (!Number.isInteger(count) || count <= 0) return 'unknown'
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(2).replace(/\.00$/, '')}M blocks`
  if (count >= 1_000) return `${(count / 1_000).toFixed(count >= 100_000 ? 1 : 2).replace(/\.0+$/, '')}K blocks`
  return `${count.toLocaleString()} blocks`
}

const formatCompactHeight = (height) => {
  if (!Number.isInteger(height) || height <= 0) return 'unknown'
  if (height >= 1_000_000) return `${(height / 1_000_000).toFixed(2)}M`
  if (height >= 1_000) return `${(height / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return height.toLocaleString()
}

export function CosmosNodeNetworkStrip({ network, overview }) {
  const diagnostics = useCosmosResource(`/api/networks/${network.id}/endpoint-status`, 30000)
  const [providerMode, setProviderMode] = useState(() => getCosmosEndpointProvider(network.id))

  useEffect(() => {
    setProviderMode(getCosmosEndpointProvider(network.id))
    return subscribeCosmosEndpointProvider((changedNetworkId) => {
      if (changedNetworkId === network.id) setProviderMode(getCosmosEndpointProvider(network.id))
    })
  }, [network.id])

  const data = overview?.data
  if (!data?.network) return null

  const providers = diagnostics.data?.network_id === network.id ? (diagnostics.data.providers || []) : []
  const rpcProvider = providerMode === 'auto'
    ? providers.find((provider) => provider.rpc?.host === data.network.rpc_status_source)
      || providers.find((provider) => provider.id === diagnostics.data?.preferred_rpc_provider_id)
    : providers.find((provider) => provider.id === providerMode)

  const selectedTxIndex = rpcProvider?.rpc?.tx_index || data.network.tx_index || 'unknown'
  const historyFloor = rpcProvider?.rpc?.lowest_available_height
  const historyHead = rpcProvider?.rpc?.height
  const retainedBlocks = Number.isInteger(historyFloor) && Number.isInteger(historyHead) && historyHead >= historyFloor
    ? historyHead - historyFloor + 1 : null
  const blockHistory = retainedBlocks
    ? `From #${formatCompactHeight(historyFloor)} · ${formatRetainedBlocks(retainedBlocks)}`
    : data.network.block_history_state
  const blockHistoryRaw = retainedBlocks
    ? `#${historyFloor.toLocaleString()} – #${historyHead.toLocaleString()} · ${retainedBlocks.toLocaleString()} blocks`
    : null

  return <section className="panel cosmos-node-strip"><dl><Detail label="Tx index" value={selectedTxIndex} /><Detail label="Application" value={[data.network.application_name, data.network.application_version].filter(Boolean).join(' ') || '—'} /><Detail label="SDK" value={data.network.sdk_version || '—'} /><Detail label="CometBFT" value={data.network.cometbft_version || '—'} /><Detail label="Node version" value={data.network.node_version || '—'} /><Detail label="Block history" value={blockHistory} raw={blockHistoryRaw} /><Detail label="RPC provider" value={rpcProvider?.label || 'unknown'} /></dl></section>
}
