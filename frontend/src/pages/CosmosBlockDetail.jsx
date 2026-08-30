import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { getCosmosBlock } from '../services/api'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { validateCosmosHeight } from '../utils/cosmosFormat'

const etaReason = {
  insufficient_sample: 'Not enough completed block intervals are available for an ETA.',
  network_appears_stalled: 'Network appears stalled. ETA is paused.',
  date_out_of_range: 'The estimated date is outside the supported display range.',
  overdue_awaiting: 'The estimate has passed. Awaiting confirmation from the API.',
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
  useEffect(() => { if (data?.network) onIdentity(data.network) }, [data?.network, onIdentity])
  useEffect(() => {
    if (data?.state !== 'future' || !data?.eta?.estimated_at) return undefined
    const timer = window.setInterval(() => setClock(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [data?.state, data?.eta?.estimated_at])
  if (validation.error) return <div className="page-state"><h1>Invalid block height</h1><p>{validation.error}</p></div>
  if (resource.loading && !data) return <div className="page-state">Loading block {height}…</div>
  if (!data) return <div className="page-state"><h1>Data temporarily unavailable</h1><p>HTTP 503 or a connection failure does not prove that this block is absent.</p><button onClick={resource.refresh}>Retry</button></div>
  const block = data.block || data
  const eta = data.eta || data.estimate
  const estimatedAt = eta?.estimated_at ? new Date(eta.estimated_at) : null
  const remainingMs = estimatedAt ? Math.max(0, estimatedAt.getTime() - clock) : null
  return <div className="cosmos-page"><div className="page-heading"><div><span className="eyebrow">AtomOne block</span><h1>Block {height}</h1></div><button onClick={resource.refresh}>Refresh</button></div>{resource.stale && <p className="stale-notice">Showing stale data after a failed refresh.</p>}
    {data.state === 'available' && <Card><h2>Completed block</h2><dl className="detail-list"><dt>Height</dt><dd>{block.height}</dd><dt>Time</dt><dd>{block.time ? new Date(block.time).toLocaleString() : '—'}</dd><dt>Hash</dt><dd>{block.hash || '—'}</dd><dt>Proposer</dt><dd>{block.proposer || '—'}</dd><dt>Transactions</dt><dd>{block.transaction_count ?? block.tx_count ?? '—'}</dd></dl></Card>}
    {data.state === 'future' && <Card><h2>Block not produced yet</h2><p>Target {data.target_height ?? height}; confirmed height {data.current_height ?? data.current_local_height}; {data.blocks_remaining ?? '—'} blocks remaining.</p>{eta?.status && eta.status !== 'available' ? <p>{etaReason[eta.status] || 'ETA is unavailable.'}</p> : estimatedAt ? <dl className="detail-list"><dt>Estimate</dt><dd><strong>Estimated</strong>{remainingMs === 0 ? ' · overdue, awaiting API confirmation' : ` · ${Math.ceil(remainingMs / 1000)} seconds`}</dd><dt>UTC</dt><dd>{estimatedAt.toUTCString()}</dd><dt>Local</dt><dd>{estimatedAt.toLocaleString()}</dd><dt>Average interval</dt><dd>{eta.average_block_interval_seconds ?? eta.average_interval_seconds}s</dd><dt>Sample size</dt><dd>{eta.sample_size}</dd></dl> : <p>ETA unavailable.</p>}<p className="section-note">This forecast is approximate. At an update height H, the last completed block may remain H−1.</p></Card>}
    {data.state === 'node_not_synced' && <Card><h2>RPC is still syncing</h2><p>The selected RPC has synchronized only to height {data.current_local_height ?? data.current_height}. It has not reached requested height {height}; no network production time is promised.</p></Card>}
    {data.state === 'history_unavailable' && <Card><h2>Block history unavailable</h2><p>The connected RPC does not provide this block.{data.confirmed_lower_bound ? ` Confirmed lower boundary: ${data.confirmed_lower_bound}.` : ''}</p></Card>}
  </div>
}
