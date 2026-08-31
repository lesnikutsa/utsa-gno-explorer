import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { relativeTime } from '../utils/time'

const blockHref = (network, height) => `/networks/${network.id}/blocks/${height}`
const shortHash = (value = '') => value.length > 15 ? `${value.slice(0, 6)}...${value.slice(-6)}` : value

export function CosmosBlocks({ network, resource }) {
  const rows = resource.data?.blocks || []
  const newest = rows[0]?.height
  return <div className="cosmos-blocks"><div className="cosmos-title"><h1>Blocks</h1>{resource.stale
    ? <span className="cosmos-stale">Stale · last successful data</span>
    : <span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 5s</span>}</div>
    {resource.loading && !resource.data && <p>Loading blocks…</p>}{resource.error && !resource.data && <p className="cosmos-error">{resource.error}</p>}
    {resource.data && <section className="panel cosmos-blocks-table"><div className="cosmos-table"><table><thead><tr><th>Height</th><th>Time</th><th>Proposer</th><th>Txs</th><th>Block hash</th></tr></thead><tbody>{rows.length ? rows.map((block, index) => <tr key={block.height} className={index === 0 && block.height === newest ? 'is-new-row' : index < 3 ? 'is-settling-row' : ''}>
      <td><a className="table-link" href={blockHref(network, block.height)}><span className="accent-value mono">#{block.height.toLocaleString()}</span></a></td>
      <td><time dateTime={block.timestamp} title={block.timestamp}>{relativeTime(block.timestamp)}</time></td>
      <td><CosmosValidatorIdentity moniker={block.proposer_moniker} address={block.proposer_operator_address || block.proposer} /></td>
      <td>{block.transaction_count.toLocaleString()}</td><td><code className="muted" title={block.hash}>{shortHash(block.hash)}</code></td>
    </tr>) : <tr><td colSpan="5">No locally available blocks.</td></tr>}</tbody></table></div></section>}
  </div>
}
