import { Card } from '../components/Card'
import { DataTable } from '../components/DataTable'
import { BlocksIcon, ChainIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { shortAddress } from '../utils/address'
import { formatProtocolDuration, formatProtocolPercent, formatTokenAmount } from '../utils/cosmosFormat'
import { relativeTime } from '../utils/time'

const sectionUnavailable = (value) => value?.error
const exactTitle = (value) => value === null || value === undefined ? undefined : String(value)

function ParameterCard({ title, value, children }) {
  return <section className="panel cosmos-parameter-card"><div className="panel__heading"><h2>{title}</h2></div>
    {sectionUnavailable(value) ? <p className="cosmos-error">Section unavailable</p> : children}
  </section>
}

const Detail = ({ label, value, raw }) => <div><dt>{label}</dt><dd title={exactTitle(raw)}>{value}</dd></div>

export function CosmosOverview({ network }) {
  const overview = useCosmosResource(`/api/networks/${network.id}/overview`)
  const market = useCosmosResource(`/api/networks/${network.id}/market`, 30000)
  const blocks = useCosmosResource(`/api/networks/${network.id}/blocks?limit=7`)
  if (overview.loading) return <p>Loading AtomOne overview…</p>
  if (!overview.data) return <div className="cosmos-error"><h2>Overview unavailable</h2><p>{overview.error}</p></div>
  return <CosmosOverviewView data={overview.data} market={market.data} marketError={market.error} blocks={blocks.data?.blocks || []} blocksError={blocks.error} stale={overview.stale} network={network} />
}

export function CosmosOverviewView({ data, market, marketError, blocks = [], blocksError, stale = false, network }) {
  const status = data.network.operational_state || 'unknown'
  const healthState = status === 'healthy' ? 'healthy' : status === 'degraded' ? 'degraded' : 'error'
  const assets = data.assets_and_supply?.assets || []
  const blockColumns = [
    { key: 'height', label: 'Height', render: (row) => <a className="table-link" href={`/networks/${network.id}/blocks/${row.height}`}><span className="accent-value mono">#{BigInt(row.height).toLocaleString()}</span></a> },
    { key: 'timestamp', label: 'Time', render: (row) => relativeTime(row.timestamp) },
    { key: 'proposer', label: 'Proposer', render: (row) => <span className="mono muted" title={row.proposer}>{shortAddress(row.proposer)}</span> },
    { key: 'transaction_count', label: 'Txs' },
    { key: 'hash', label: 'Block Hash', render: (row) => <span className="mono muted" title={row.hash}>{shortAddress(row.hash)}</span> },
  ]
  const validators = Array.isArray(data.top_active_validators_by_missed_blocks) ? data.top_active_validators_by_missed_blocks : []
  const validatorColumns = [
    { key: 'moniker', label: 'Validator', render: (row) => <span className="cosmos-validator"><strong title={row.moniker}>{row.moniker || 'Unnamed validator'}</strong><span className="mono muted" title={row.consensus_address}>{shortAddress(row.consensus_address)}</span></span> },
    { key: 'missed_blocks_counter', label: 'Missed Blocks', render: (row) => <strong className="missed-value missed-value--medium">{row.missed_blocks_counter}</strong> },
  ]
  return <div className="cosmos-overview">
    <div className="page-heading"><div><p className="eyebrow">Cosmos network</p><h1>{network.presentation.projectName} Overview</h1></div>{stale && <span className="cosmos-stale">Stale data</span>}</div>
    <section className="status-grid" aria-label="Network summary">
      <Card eyebrow="Latest Block" icon={BlocksIcon} value={`#${BigInt(data.network.current_local_height).toLocaleString()}`} meta="Latest locally available height" href={`/networks/${network.id}/blocks/${data.network.current_local_height}`} />
      <Card eyebrow="Network Status" icon={NetworkIcon} value={status.charAt(0).toUpperCase() + status.slice(1)} tone={healthState} meta={data.network.catching_up ? 'Node is catching up' : 'Node is synchronized'} />
      <Card eyebrow="Active Validators" icon={ValidatorsIcon} value={sectionUnavailable(data.staking) ? 'Unavailable' : data.staking.active_validator_count.toLocaleString()} meta="Current active set" />
      <Card eyebrow="Chain ID" icon={ChainIcon} value={network.expectedChainId} meta={data.network.latest_block_time ? `Latest block ${relativeTime(data.network.latest_block_time)}` : 'Configured network identity'} />
    </section>
    <div className="dashboard-grid cosmos-dashboard-grid">
      <section className="panel dashboard-grid__blocks"><div className="panel__heading"><h2>Latest Blocks</h2><a className="panel__meta" href={`/networks/${network.id}/blocks`}>View all</a></div><DataTable columns={blockColumns} rows={blocks} rowKey={(row) => row.height} emptyMessage={blocksError ? 'Blocks are currently unavailable.' : 'No locally available blocks.'} /></section>
      <section className="panel dashboard-grid__validators"><div className="panel__heading"><h2>Validators by Missed Blocks</h2><span className="panel__meta">Active set</span></div><DataTable columns={validatorColumns} rows={validators} rowKey={(row) => row.consensus_address} emptyMessage={sectionUnavailable(data.top_active_validators_by_missed_blocks) ? 'Validator data is unavailable.' : 'No active validator misses reported.'} /></section>
    </div>
    <div className="cosmos-parameters">
      <ParameterCard title="Market"><dl className="cosmos-metrics"><Detail label="ATONE price" value={market ? `$${market.price}` : marketError ? 'Unavailable' : '—'} raw={market?.price} /><Detail label="Market cap" value={market ? `$${market.market_cap}` : '—'} raw={market?.market_cap} /><Detail label="24h change" value={market?.change_24h === undefined ? '—' : `${market.change_24h}%`} raw={market?.change_24h} /></dl></ParameterCard>
      <ParameterCard title="Supply" value={data.assets_and_supply}><dl className="cosmos-metrics">{assets.map((asset) => <Detail key={asset.base} label={asset.symbol} value={formatTokenAmount(asset.total_supply, asset.exponent, asset.symbol)} raw={asset.total_supply} />)}</dl></ParameterCard>
      <ParameterCard title="Staking" value={data.staking}><dl className="cosmos-metrics"><Detail label="Bonded tokens" value={formatTokenAmount(data.staking?.bonded_tokens, 6, 'ATONE')} raw={data.staking?.bonded_tokens} /><Detail label="Bonded ratio" value={formatProtocolPercent(data.staking?.bonded_ratio)} raw={data.staking?.bonded_ratio} /><Detail label="Active validators" value={data.staking?.active_validator_count ?? '—'} /></dl></ParameterCard>
      <ParameterCard title="Mint" value={data.mint}><dl className="cosmos-metrics"><Detail label="Inflation" value={formatProtocolPercent(data.mint?.current_inflation)} raw={data.mint?.current_inflation} /><Detail label="Goal bonded" value={formatProtocolPercent(data.mint?.goal_bonded)} raw={data.mint?.goal_bonded} /></dl></ParameterCard>
      <ParameterCard title="Slashing" value={data.slashing}><dl className="cosmos-metrics"><Detail label="Signed blocks window" value={data.slashing?.signed_blocks_window?.toLocaleString() ?? '—'} /><Detail label="Allowed misses" value={data.slashing?.allowed_missed_threshold?.toLocaleString() ?? '—'} /></dl><p className="cosmos-parameter-note">Protocol slashing counter; distance to this threshold does not guarantee blocks until jail.</p></ParameterCard>
      <ParameterCard title="Governance" value={data.governance}><dl className="cosmos-metrics"><Detail label="Quorum" value={formatProtocolPercent(data.governance?.quorum)} raw={data.governance?.quorum} /><Detail label="Threshold" value={formatProtocolPercent(data.governance?.threshold)} raw={data.governance?.threshold} /><Detail label="Voting period" value={formatProtocolDuration(data.governance?.voting_period)} raw={data.governance?.voting_period} /></dl></ParameterCard>
      <ParameterCard title="Distribution" value={data.distribution}><dl className="cosmos-metrics"><Detail label="Community tax" value={formatProtocolPercent(data.distribution?.community_tax)} raw={data.distribution?.community_tax} /><Detail label="Withdraw address" value={data.distribution?.withdraw_address_enabled ? 'Enabled' : 'Disabled'} /></dl></ParameterCard>
    </div>
  </div>
}
