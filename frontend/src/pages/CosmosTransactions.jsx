import { useMemo } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { relativeTime } from '../utils/time'
import { formatTokenAmount } from '../utils/cosmosFormat'
import '../styles/cosmos-transactions.css'
import '../styles/cosmos-tx-tooltip.css'

const shortHash = (hash) => `${hash.slice(0, 7)}...${hash.slice(-7)}`
const compact = (value) => value == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const fee = (row, assets) => {
  if (!row.fee_amount || !row.fee_denom) return '—'
  const asset = assets.find((item) => item.base === row.fee_denom)
  return asset ? formatTokenAmount(row.fee_amount, asset.exponent, asset.symbol) : `${row.fee_amount} ${row.fee_denom}`
}
const cursorHref = (cursor) => cursor ? `?cursor=${encodeURIComponent(cursor)}` : '?'
const typeTone = (row) => {
  const type = row.primary_message_type || ''
  if (type.includes('.staking.')) return 'staking'
  if (type.includes('.distribution.')) return 'reward'
  if (type.includes('.gov.')) return 'governance'
  if (type.includes('.authz.')) return 'exec'
  if (type.includes('/ibc.core.')) return 'ibc'
  if (type.includes('/ibc.applications.transfer.') || type.includes('.bank.')) return 'transfer'
  return 'other'
}

export function CosmosTransactions({ network }) {
  const cursor = new URLSearchParams(window.location.search).get('cursor')
  const query = cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
  const resource = useCosmosResource(`/api/networks/${network.id}/transactions/history?limit=20${query}`, cursor ? null : 30000)
  const rows = resource.data?.transactions || []
  const newest = useMemo(() => rows[0]?.tx_hash, [rows])
  const state = resource.data?.state
  return <div className="cosmos-blocks cosmos-transactions"><div className="cosmos-title"><h1>Transactions</h1>{resource.stale || resource.error
    ? <span className="cosmos-stale">Stale · last successful data</span>
    : !cursor && state === 'available' ? <span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 30s</span> : null}</div>
    {resource.loading && !resource.data && <p>Loading transactions…</p>}
    {resource.error && !resource.data && <section className="cosmos-card"><h2>Transactions unavailable</h2><p>The upstream API is temporarily unavailable.</p><details className="cosmos-detail-card"><summary>Details</summary><p>{resource.error}</p></details></section>}
    {state === 'indexing_unavailable' && <section className="cosmos-card"><h2>Transaction search unavailable</h2><p>The upstream node does not expose indexed transaction search.</p></section>}
    {state === 'available' && <><section className="panel cosmos-blocks-table"><div className="cosmos-table"><table><thead><tr><th>Type</th><th>Tx hash</th><th>Time</th><th>Block</th><th>Status</th><th>Fee</th><th>Gas</th></tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={row.tx_hash} className={!cursor && row.tx_hash === newest && index === 0 ? 'is-new-row' : ''}>
      <td title={row.primary_message_type || undefined}><span className={`cosmos-tx-type cosmos-tx-type--${typeTone(row)}`}>{row.primary_action}{row.message_count > 1 && <small className="cosmos-tx-more">+{row.message_count - 1}</small>}</span></td>
      <td><a className="cosmos-tx-hash cosmos-tx-tooltip" href={`/networks/${network.id}/transactions/${encodeURIComponent(row.tx_hash)}`} data-tooltip={row.tx_hash} aria-label={`Open transaction ${row.tx_hash}`}>{shortHash(row.tx_hash)}</a></td>
      <td><time dateTime={row.timestamp} title={row.timestamp}>{relativeTime(row.timestamp)}</time></td>
      <td><a className="table-link" href={`/networks/${network.id}/blocks/${row.height}`}><span className="accent-value mono">#{row.height.toLocaleString()}</span></a></td>
      <td><span className={`cosmos-tx-status cosmos-tx-status--${row.success ? 'success' : 'failed'}`}>{row.success ? 'Success' : 'Failed'}</span></td>
      <td>{fee(row, network.assets)}</td><td title={`${row.gas_used} / ${row.gas_wanted}`}>{compact(row.gas_used)}</td>
    </tr>) : <tr><td colSpan="7">No transactions in this result window.</td></tr>}</tbody></table></div></section>
    <nav className="cosmos-pagination">{resource.data.has_newer ? <a href={cursorHref(resource.data.newer_cursor)}>← Newer</a> : <span />}{resource.data.has_older && <a href={cursorHref(resource.data.older_cursor)}>Older →</a>}</nav></>}
  </div>
}
