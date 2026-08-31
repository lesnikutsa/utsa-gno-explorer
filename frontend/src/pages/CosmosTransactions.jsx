import { useMemo } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { relativeTime } from '../utils/time'
import { formatTokenAmount } from '../utils/cosmosFormat'

const shortHash = (hash) => `${hash.slice(0, 7)}...${hash.slice(-7)}`
const compact = (value) => value == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const fee = (row, assets) => {
  if (!row.fee_amount || !row.fee_denom) return '—'
  const asset = assets.find((item) => item.base === row.fee_denom)
  return asset ? formatTokenAmount(row.fee_amount, asset.exponent, asset.symbol) : `${row.fee_amount} ${row.fee_denom}`
}

export function CosmosTransactions({ network }) {
  const page = Math.max(1, Number(new URLSearchParams(window.location.search).get('page')) || 1)
  const resource = useCosmosResource(`/api/networks/${network.id}/transactions?limit=20&page=${page}`, page === 1 ? 10000 : null)
  const rows = resource.data?.transactions || []
  const newest = useMemo(() => rows[0]?.tx_hash, [rows])
  const state = resource.data?.state
  return <div className="cosmos-blocks cosmos-transactions"><div className="cosmos-title"><h1>Transactions</h1>{resource.stale || resource.error
    ? <span className="cosmos-stale">Stale · last successful data</span>
    : page === 1 && state === 'available' ? <span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 10s</span> : null}</div>
    {resource.loading && !resource.data && <p>Loading transactions…</p>}
    {resource.error && !resource.data && <section className="cosmos-card"><h2>Transactions unavailable</h2><p>The upstream API is temporarily unavailable.</p><details className="cosmos-detail-card"><summary>Details</summary><p>{resource.error}</p></details></section>}
    {state === 'indexing_unavailable' && <section className="cosmos-card"><h2>Transaction search unavailable</h2><p>The upstream node does not expose indexed transaction search.</p></section>}
    {state === 'available' && <><section className="panel cosmos-blocks-table"><div className="cosmos-table"><table><thead><tr><th>Time</th><th>Type</th><th>Tx hash</th><th>Block</th><th>Status</th><th>Fee</th><th>Gas</th></tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={row.tx_hash} className={page === 1 && row.tx_hash === newest && index === 0 ? 'is-new-row' : ''}>
      <td><time dateTime={row.timestamp} title={row.timestamp}>{relativeTime(row.timestamp)}</time></td>
      <td title={row.primary_message_type || undefined}>{row.primary_action}{row.message_count > 1 && <small className="cosmos-tx-more">+{row.message_count - 1}</small>}</td>
      <td><code className="accent-value" title={row.tx_hash}>{shortHash(row.tx_hash)}</code></td>
      <td><a className="table-link" href={`/networks/${network.id}/blocks/${row.height}`}><span className="accent-value mono">#{row.height.toLocaleString()}</span></a></td>
      <td><span className={`cosmos-tx-status cosmos-tx-status--${row.success ? 'success' : 'failed'}`}>{row.success ? 'Success' : 'Failed'}</span></td>
      <td>{fee(row, network.assets)}</td><td title={`${row.gas_used} / ${row.gas_wanted}`}>{compact(row.gas_used)}</td>
    </tr>) : <tr><td colSpan="7">No transactions in this result window.</td></tr>}</tbody></table></div></section>
    <nav className="cosmos-pagination">{resource.data.has_newer ? <a href={`?page=${page - 1}`}>← Newer</a> : <span />}{resource.data.has_older && <a href={`?page=${page + 1}`}>Older →</a>}</nav></>}
  </div>
}
