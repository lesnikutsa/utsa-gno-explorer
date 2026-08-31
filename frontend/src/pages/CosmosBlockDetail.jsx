import { useEffect, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'

export function CosmosBlockDetail({ network, height }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/blocks/${height}`)
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer) }, [])
  if (resource.loading) return <p>Looking up block {height}…</p>
  if (!resource.data) return <p className="cosmos-error">{resource.error}</p>
  const data = resource.data
  const eta = data.eta
  const remainingSeconds = eta ? Math.floor((Date.parse(eta.estimated_at) - now) / 1000) : null
  return <><div className="cosmos-title"><div><p className="eyebrow">Block lookup</p><h1>Height {height}</h1></div>{resource.stale && <span>Stale data</span>}</div>
    <section className="cosmos-card"><h2>{data.state.replaceAll('_', ' ')}</h2><p>Local RPC height: {data.local_height}</p>
      {data.state === 'available' && <dl><dt>Hash</dt><dd><code>{data.block.hash}</code></dd><dt>Timestamp</dt><dd>{data.block.timestamp}</dd><dt>Proposer</dt><dd><code>{data.block.proposer}</code></dd><dt>Transactions</dt><dd>{data.block.transaction_count}</dd></dl>}
      {data.state === 'future' && <div>{eta ? <><p><strong>Estimated</strong> from the last confirmed block and {eta.sample_intervals} trimmed intervals.</p><p>UTC: {new Date(eta.estimated_at).toISOString()}</p><p>Local: {new Date(eta.estimated_at).toLocaleString()}</p><p>{eta.remaining_blocks} blocks · {remainingSeconds > 0 ? `${remainingSeconds}s remaining` : 'Overdue / awaiting block'}</p></> : <p>ETA unavailable: {data.eta_unavailable_reason?.replaceAll('_', ' ')}.</p>}<p>At an upgrade height H, the last completed block may remain H−1.</p></div>}
      {data.state === 'node_not_synced' && <p>The connected RPC is still syncing and has not reached this height.</p>}
      {data.state === 'history_unavailable' && <p>Connected RPC endpoints do not provide this historical block.</p>}
    </section></>
}
