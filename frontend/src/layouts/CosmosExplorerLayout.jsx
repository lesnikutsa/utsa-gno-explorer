import { ExplorerLayout } from './ExplorerLayout'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { deriveBlockTimeMetrics } from '../utils/cosmosBlockTime'

const healthFor = (resource) => {
  if (!resource.data) return resource.loading ? 'loading' : 'error'
  if (resource.stale) return 'degraded'
  return resource.data.network.operational_state === 'healthy' ? 'healthy'
    : resource.data.network.operational_state === 'unavailable' ? 'error' : 'degraded'
}

export function CosmosExplorerLayout({ network, children }) {
  const overview = useCosmosResource(`/api/networks/${network.id}/overview`)
  const blocks = useCosmosResource(`/api/networks/${network.id}/blocks?limit=20`)
  const blockTime = deriveBlockTimeMetrics(blocks.data?.blocks)
  return <ExplorerLayout
    chainId={network.expectedChainId}
    healthState={healthFor(overview)}
    nextFastRefreshAt={overview.nextRefreshAt}
    averageBlockTimeSeconds={blockTime.average}
    averageBlockTimeSampleSize={blockTime.sampleSize}
    averageBlockTimeIntervalsSeconds={blockTime.intervals}
    documentTitle={`${network.presentation.projectName} Explorer`}
  >
    {typeof children === 'function' ? children({ overview, blocks }) : children}
  </ExplorerLayout>
}
