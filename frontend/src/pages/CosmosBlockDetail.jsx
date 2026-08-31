import { useEffect, useState } from 'react'
import { CopyButton } from '../components/CopyButton'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { relativeTime } from '../utils/time'

const utc = (value) => new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'UTC' }).format(new Date(value)).replace(',', ' ·') + ' UTC'
const Hash = ({ value, label }) => value ? <span className="cosmos-copy-value"><code title={value}>{value}</code><CopyButton value={value} label={`Copy ${label}`} /></span> : <span>—</span>
const Metric = ({ label, children }) => <div><span>{label}</span><strong>{children}</strong></div>

function AvailableBlock({ network, lookup, height }) {
  const detail = useCosmosResource(`/api/networks/${network.id}/blocks/${height}/detail`, null)
  if (!detail.data) return detail.loading ? <p>Loading block detail…</p> : <p className="cosmos-error">{detail.error}</p>
  const data = detail.data
  const primary = [['Block hash', data.hashes.block], ['App hash', data.hashes.app], ['Validators hash', data.hashes.validators]]
  const technical = [['Last block hash', data.hashes.last_block], ['Last commit hash', data.hashes.last_commit], ['Data hash', data.hashes.data], ['Next validators hash', data.hashes.next_validators], ['Consensus hash', data.hashes.consensus], ['Last results hash', data.hashes.last_results], ['Evidence hash', data.hashes.evidence]]
  return <><nav className="cosmos-block-nav">{data.height > 1 && <a href={`/networks/${network.id}/blocks/${data.height - 1}`}>← #{(data.height - 1).toLocaleString()}</a>}<span />{data.height < lookup.local_height ? <a href={`/networks/${network.id}/blocks/${data.height + 1}`}>#{(data.height + 1).toLocaleString()} →</a> : <span>Latest</span>}</nav>
    <section className="cosmos-detail-summary panel"><Metric label="Height">{data.height.toLocaleString()}</Metric><Metric label="Time"><time title={data.timestamp}>{relativeTime(data.timestamp)}</time><small>{utc(data.timestamp)}</small></Metric><Metric label="Transactions">{data.transaction_count.toLocaleString()}</Metric><Metric label="Chain ID">{data.chain_id}</Metric></section>
    <section className="panel cosmos-detail-card"><h2>Block Information</h2><dl><dt>Block hash</dt><dd><Hash value={data.hashes.block} label="block hash" /></dd><dt>Proposer</dt><dd><span className="cosmos-copy-value"><CosmosValidatorIdentity moniker={data.proposer_moniker} address={data.proposer_operator_address || data.proposer} /><CopyButton value={data.proposer_operator_address || data.proposer} label="Copy proposer address" /></span></dd><dt>Timestamp</dt><dd><time title={data.timestamp}>{utc(data.timestamp)} · {relativeTime(data.timestamp)}</time></dd><dt>Block version</dt><dd>{data.block_version}</dd><dt>App version</dt><dd>{data.app_version}</dd></dl></section>
    <section className="panel cosmos-detail-card"><h2>Block Hashes</h2><dl>{primary.map(([label, value]) => <><dt key={`${label}-label`}>{label}</dt><dd key={label}><Hash value={value} label={label} /></dd></>)}</dl><details><summary>More technical hashes</summary><dl>{technical.map(([label, value]) => <><dt key={`${label}-label`}>{label}</dt><dd key={label}><Hash value={value} label={label} /></dd></>)}</dl></details></section>
    <section className="panel cosmos-detail-card"><h2>Commit Summary</h2><div className="cosmos-commit-summary">{Object.entries(data.commit).map(([key, value]) => <Metric key={key} label={key}>{value}</Metric>)}</div><details><summary>Commit Signatures ({data.signatures.length})</summary><div className="cosmos-table"><table><thead><tr><th>Validator</th><th>Status</th><th>Timestamp</th></tr></thead><tbody>{data.signatures.map((sig, index) => <tr key={`${sig.validator_address}-${index}`}><td><CosmosValidatorIdentity moniker={sig.moniker} address={sig.operator_address || sig.validator_address} /></td><td><span className={`cosmos-signature-status cosmos-signature-status--${sig.status}`}>{sig.status}</span></td><td>{sig.timestamp ? <time title={sig.timestamp}>{new Date(sig.timestamp).toISOString().slice(11, 19)}</time> : '—'}</td></tr>)}</tbody></table></div></details></section>
    <section className="panel cosmos-detail-card"><h2>Transactions <span>{data.transactions.length}</span></h2>{data.transactions.length ? <div className="cosmos-table"><table><thead><tr><th>Index</th><th>Tx hash</th><th>Status</th><th>Gas used</th><th>Gas wanted</th></tr></thead><tbody>{data.transactions.map((tx) => <tr key={tx.index}><td>{tx.index}</td><td><Hash value={tx.hash} label="transaction hash" /></td><td>{tx.status === 'success' ? 'Success' : 'Failed'}</td><td>{tx.gas_used?.toLocaleString() ?? '—'}</td><td>{tx.gas_wanted?.toLocaleString() ?? '—'}</td></tr>)}</tbody></table></div> : <p>No transactions in this block.</p>}</section>
    {data.evidence.length > 0 && <section className="panel cosmos-detail-card"><h2>Evidence</h2><ul>{data.evidence.map((item, index) => <li key={index}>{item.type}{item.height ? ` · height ${item.height}` : ''}</li>)}</ul></section>}
    <details className="panel cosmos-normalized-json"><summary>Normalized JSON</summary><pre>{JSON.stringify(data, null, 2)}</pre></details></>
}

export function CosmosBlockDetail({ network, height }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/blocks/${height}`)
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer) }, [])
  if (resource.loading) return <p>Looking up block {height}…</p>
  if (!resource.data) return <p className="cosmos-error">{resource.error}</p>
  const data = resource.data; const eta = data.eta
  const remainingSeconds = eta ? Math.floor((Date.parse(eta.estimated_at) - now) / 1000) : null
  return <div className="cosmos-block-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/blocks`}>← Back to Blocks</a><div className="cosmos-title"><h1>Block #{Number(height).toLocaleString()}</h1>{resource.stale && <span>Stale</span>}</div>
    {data.state === 'available' ? <AvailableBlock network={network} lookup={data} height={height} /> : <section className="cosmos-card"><h2>{data.state.replaceAll('_', ' ')}</h2><p>Local RPC height: {data.local_height}</p>{data.state === 'future' && (eta ? <><p>Estimated from {eta.sample_intervals} block intervals.</p><p>{utc(eta.estimated_at)} · {eta.remaining_blocks} blocks · {remainingSeconds > 0 ? `${remainingSeconds}s remaining` : 'Overdue / awaiting block'}</p></> : <p>ETA unavailable: {data.eta_unavailable_reason?.replaceAll('_', ' ')}.</p>)}{data.state === 'node_not_synced' && <p>The connected RPC is still syncing and has not reached this height.</p>}{data.state === 'history_unavailable' && <p>Connected RPC endpoints do not provide this historical block.</p>}</section>}
  </div>
}
