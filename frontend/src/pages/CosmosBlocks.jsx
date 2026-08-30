import { useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { navigateInternal } from '../utils/navigation'

export function CosmosBlocks({ network }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/blocks?limit=10`)
  const [height, setHeight] = useState('')
  const submit = (event) => {
    event.preventDefault()
    if (!/^[1-9]\d{0,18}$/.test(height) || BigInt(height) > 9223372036854775807n) return
    navigateInternal(`/networks/${network.id}/blocks/${height}`)
  }
  return <><div className="cosmos-title"><div><p className="eyebrow">CometBFT metadata</p><h1>Latest blocks</h1></div>{resource.stale && <span>Stale data</span>}</div>
    <form className="cosmos-height-search" onSubmit={submit}><label>Block height <input value={height} onChange={(event) => setHeight(event.target.value)} inputMode="numeric" /></label><button>Search</button></form>
    {resource.loading && <p>Loading blocks…</p>}{resource.error && !resource.data && <p className="cosmos-error">{resource.error}</p>}
    {resource.data && <div className="cosmos-card cosmos-table"><table><thead><tr><th>Height</th><th>Hash</th><th>Time</th><th>Proposer</th><th>Txs</th></tr></thead><tbody>{resource.data.blocks.length ? resource.data.blocks.map((block) => <tr key={block.height}><td><a href={`/networks/${network.id}/blocks/${block.height}`}>{block.height}</a></td><td><code>{block.hash}</code></td><td>{block.timestamp}</td><td><code>{block.proposer}</code></td><td>{block.transaction_count}</td></tr>) : <tr><td colSpan="5">No locally available blocks.</td></tr>}</tbody></table></div>}
  </>
}
