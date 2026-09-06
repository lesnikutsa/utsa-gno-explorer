import { CosmosNodeNetworkStrip } from '../components/CosmosNodeNetworkStrip'
import { CosmosResourceFooter } from '../components/CosmosResourceFooter'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { deriveBlockTimeMetrics } from '../utils/cosmosBlockTime'
import { usePathname } from '../utils/navigation'
import { ExplorerLayout } from './ExplorerLayout'
import '../styles/cosmos-responsive.css'

const healthFor = (resource) => {
  if (!resource.data) return resource.loading ? 'loading' : 'error'
  if (resource.stale) return 'degraded'
  return resource.data.network.operational_state === 'healthy' ? 'healthy'
    : resource.data.network.operational_state === 'unavailable' ? 'error' : 'degraded'
}

export function CosmosExplorerLayout({ network, children }) {
  const pathname = usePathname()
  const overview = useCosmosResource(`/api/networks/${network.id}/overview`)
  const blocks = useCosmosResource(`/api/networks/${network.id}/blocks?limit=20`)
  const blockTime = deriveBlockTimeMetrics(blocks.data?.blocks)
  const healthState = healthFor(overview) === 'healthy' && blocks.stale ? 'degraded' : healthFor(overview)
  const overviewPath = `/networks/${network.id}`
  const isOverview = pathname === overviewPath || pathname === `${overviewPath}/`
  return <ExplorerLayout
    chainId={network.expectedChainId}
    healthState={healthState}
    nextFastRefreshAt={overview.nextRefreshAt}
    averageBlockTimeSeconds={blockTime.average}
    averageBlockTimeSampleSize={blockTime.sampleSize}
    averageBlockTimeIntervalsSeconds={blockTime.intervals}
    documentTitle={`${network.presentation.projectName} Explorer`}
  >
    {typeof children === 'function' ? children({ overview, blocks, blockTime }) : children}
    {!isOverview && <CosmosNodeNetworkStrip network={network} overview={overview} />}
    <CosmosResourceFooter />
  </ExplorerLayout>
}
