import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { getCosmosBlocks } from '../services/api'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { mergeBlockWindow } from '../utils/cosmosFormat'
import { navigateInternal } from '../utils/navigation'

const short = (text) => text ? `${text.slice(0, 10)}…${text.slice(-8)}` : '—'

export function CosmosBlocks({ network, onIdentity }) {
  const [blocks, setBlocks] = useState([])
  const load = useCallback((signal) => getCosmosBlocks(network.id, { limit: 10, signal }), [network.id])
  const resource = useCosmosResource(load)
  useEffect(() => { setBlocks([]) }, [network.id])
  useEffect(() => {
    if (!resource.data) return
    setBlocks((old) => mergeBlockWindow(old, resource.data))
    onIdentity(resource.data.network || resource.data)
  }, [resource.data, onIdentity])
  return <div className="cosmos-page"><div className="page-heading"><div><span className="eyebrow">AtomOne</span><h1>Latest Blocks</h1><p>{resource.data?.network?.catching_up ? 'Syncing · local RPC height' : 'Latest completed blocks from the selected RPC'}</p></div><button onClick={resource.refresh}>Refresh</button></div>
    {resource.stale && <p className="stale-notice">The latest refresh failed; displayed blocks may be stale.</p>}
    {resource.error && !blocks.length ? <div className="page-state"><p>Block data is temporarily unavailable.</p><button onClick={resource.refresh}>Retry</button></div> : <Card><div className="table-wrap"><table className="cosmos-table"><thead><tr><th>Height</th><th>Time</th><th>Proposer</th><th>Transactions</th><th>Hash</th></tr></thead><tbody>{blocks.map((block) => <tr key={block.height}><td><a href={`${network.routePrefix}/blocks/${block.height}`} onClick={(event) => { event.preventDefault(); navigateInternal(event.currentTarget.href) }}>{block.height}</a></td><td>{block.time ? new Date(block.time).toLocaleString() : '—'}</td><td title={block.proposer}>{short(block.proposer)}</td><td>{block.transaction_count ?? block.tx_count ?? '—'}</td><td title={block.hash}>{short(block.hash)}</td></tr>)}</tbody></table></div></Card>}
  </div>
}
