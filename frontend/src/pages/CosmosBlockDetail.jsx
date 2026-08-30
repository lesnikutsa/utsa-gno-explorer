import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CosmosPanel } from '../components/CosmosPanel'
import { getCosmosBlock } from '../services/api'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { cosmosBlockLookupOperationalState, validateCosmosHeight } from '../utils/cosmosFormat'

const etaReasons = {
  insufficient_sample: 'Not enough completed block intervals are available for an ETA.',
  network_appears_stalled: 'Network appears stalled. ETA is paused.',
  date_out_of_range: 'The estimated date is outside the supported display range.',
}

export function CosmosBlockDetailContent({ data, height, clock = Date.now() }) {
  const block = data.block
  const eta = data.eta
  const estimatedAt = eta?.estimated_at ? new Date(eta.estimated_at) : null
  const remainingMs = estimatedAt ? Math.max(0, estimatedAt.getTime() - clock) : null
  return <>
    {data.state === 'available' && <CosmosPanel><h2>Completed block</h2><dl className="detail-list"><dt>Height</dt><dd>{block.height}</dd><dt>Time</dt><dd>{block.timestamp ? new Date(block.timestamp).toLocaleString() : '—'}</dd><dt>Hash</dt><dd>{block.hash}</dd><dt>Proposer</dt><dd>{block.proposer}</dd><dt>Transactions</dt><dd>{block.transaction_count}</dd></dl></CosmosPanel>}
    {data.state === 'future' && <CosmosPanel><h2>Block not produced yet</h2><p>Target {data.target_height ?? height}; confirmed height {data.current_height}; {eta?.remaining_blocks ?? '—'} blocks remaining.</p>{eta ? <dl className="detail-list"><dt>Estimate</dt><dd><strong>Estimated</strong>{eta.status === 'overdue_awaiting' || remainingMs === 0 ? ' · overdue, awaiting API confirmation' : ` · ${Math.ceil(remainingMs / 1000)} seconds`}</dd><dt>UTC</dt><dd>{estimatedAt?.toUTCString()}</dd><dt>Local</dt><dd>{estimatedAt?.toLocaleString()}</dd><dt>Average interval</dt><dd>{eta.average_interval_seconds}s</dd><dt>Sample size</dt><dd>{eta.sample_interval_count}</dd></dl> : <p>{etaReasons[data.eta_unavailable_reason] || 'ETA is unavailable.'}</p>}<p className="section-note">This forecast is approximate. At an update height H, the last completed block may remain H−1.</p></CosmosPanel>}
    {data.state === 'node_not_synced' && <CosmosPanel><h2>RPC is still syncing</h2><p>The selected RPC has synchronized only to height {data.current_height}. It has not reached requested height {height}; no network production time is promised.</p></CosmosPanel>}
    {data.state === 'history_unavailable' && <CosmosPanel><h2>Block history unavailable</h2><p>The connected RPC does not provide this block.{data.lowest_available_height ? ` Lowest confirmed available height: ${data.lowest_available_height}.` : ''}</p></CosmosPanel>}
  </>
}

export function CosmosBlockDetail({ network, height, onIdentity }) {
  const validation = useMemo(() => validateCosmosHeight(height), [height])
  const [clock, setClock] = useState(Date.now())
  const completed = useRef(false)
  const load = useCallback((signal) => validation.height ? getCosmosBlock(network.id, validation.height, { signal }) : Promise.resolve(null), [network.id, validation.height])
  const stopWhen = useCallback(() => completed.current, [])
  const resource = useCosmosResource(load, { enabled: Boolean(validation.height), stopWhen })
  const data = resource.data
  useEffect(() => { completed.current = data?.state === 'available' }, [data?.state])
  useEffect(() => { if (data) onIdentity({ chain_id: data.chain_id, operational_state: cosmosBlockLookupOperationalState(data) }) }, [data, onIdentity])
  useEffect(() => {
    if (data?.state !== 'future' || !data?.eta?.estimated_at) return undefined
    const timer = window.setInterval(() => setClock(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [data?.state, data?.eta?.estimated_at])
  if (validation.error) return <div className="page-state"><h1>Invalid block height</h1><p>{validation.error}</p></div>
  if (resource.loading && !data) return <div className="page-state">Loading block {height}…</div>
  if (!data) return <div className="page-state"><h1>Data temporarily unavailable</h1><p>HTTP 503 or a connection failure does not prove that this block is absent.</p><button onClick={resource.refresh}>Retry</button></div>
  return <div className="cosmos-page"><div className="page-heading"><div><span className="eyebrow">AtomOne block</span><h1>Block {height}</h1></div><button onClick={resource.refresh}>Refresh</button></div>{resource.stale && <p className="stale-notice">Showing stale data after a failed refresh.</p>}<CosmosBlockDetailContent data={data} height={height} clock={clock} /></div>
}
