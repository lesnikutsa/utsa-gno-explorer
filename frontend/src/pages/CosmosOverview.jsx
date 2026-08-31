import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { DataTable } from '../components/DataTable'
import { BlocksIcon, ChainIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import { ParameterHelp } from '../components/ParameterHelp'
import { CosmosRpcStatus } from '../components/CosmosRpcStatus'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { shortAddress } from '../utils/address'
import { formatCompactDecimal, formatProtocolDuration, formatProtocolPercent, formatTokenAmount } from '../utils/cosmosFormat'
import { cosmosLivenessRisk, formatApproximateDuration } from '../utils/cosmosSlashing'
import { relativeTime } from '../utils/time'

const sectionUnavailable = (value) => value?.error
const help = {
  'Bonded ratio': 'The share of total token supply currently bonded to validators.',
  'Goal bonded': 'The bonded-token target used by the mint module when adjusting inflation.',
  'Signed blocks window': 'The rolling block window used to evaluate validator availability.',
  'Allowed misses': 'How many blocks a validator may miss within the signing window before downtime penalties apply.',
  'Minimum signed': 'The minimum share of blocks a validator must sign in the window.',
  Quorum: 'The minimum voting power participation required for a governance proposal.',
  Threshold: 'The minimum share of non-abstaining votes required for a proposal to pass.',
  'Community tax': 'The share of staking rewards directed to the community pool.',
  'Unbonding time': 'How long stake remains locked while moving out of the bonded state.',
  'Commission limits': 'Protocol bounds applied to validator commission rates.',
  'Nakamoto Bonus': 'AtomOne distribution parameters for its chain-specific validator incentive mechanism.',
}

const Label = ({ children }) => <span>{children}{help[children] && <ParameterHelp label={children}>{help[children]}</ParameterHelp>}</span>
const Detail = ({ label, value, raw }) => <div><dt><Label>{label}</Label></dt><dd title={raw === undefined || raw === null ? undefined : String(raw)}>{value}</dd></div>
const Advanced = ({ children }) => <details className="cosmos-advanced"><summary>More parameters</summary><dl className="cosmos-metrics">{children}</dl></details>
function ParameterCard({ title, value, children }) { return <section className="panel cosmos-parameter-card"><div className="panel__heading"><h2>{title}</h2></div>{sectionUnavailable(value) ? <p className="cosmos-quiet-state">Section unavailable</p> : children}</section> }

function MarketPanel({ network, market, marketError, history }) {
  const points = history?.points || []
  const prices = points.map((point) => Number(point.price)).filter(Number.isFinite)
  const min = prices.length ? Math.min(...prices) : 0
  const max = prices.length ? Math.max(...prices) : 0
  const range = max - min || 1
  const path = prices.map((price, index) => `${index ? 'L' : 'M'}${(index / Math.max(1, prices.length - 1) * 300).toFixed(2)},${(72 - ((price - min) / range) * 60).toFixed(2)}`).join(' ')
  const change = Number(market?.change_24h)
  const tone = change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral'
  const symbol = network.assets?.[0]?.symbol || network.presentation.nativeToken?.symbol || 'Token'
  return <section className="panel cosmos-market"><div className="cosmos-market__summary"><div><span className="eyebrow">Market · {symbol}</span><strong>{market ? `$${Number(market.price).toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}` : marketError ? 'Unavailable' : '—'}</strong><span className={`cosmos-market__change cosmos-market__change--${tone}`}>{market ? `${change > 0 ? '+' : ''}${change.toFixed(2)}% (24h)` : 'Optional market enrichment'}</span><small className="cosmos-market__source">{market?.source_last_updated_at ? `CoinGecko · updated ${relativeTime(market.source_last_updated_at)}` : 'CoinGecko · unavailable'}</small></div><dl><Detail label="Market cap" value={market ? formatCompactDecimal(market.market_cap, { prefix: '$' }) : '—'} />{prices.length > 1 && <><Detail label="24h low" value={`$${min.toFixed(6)}`} /><Detail label="24h high" value={`$${max.toFixed(6)}`} /></>}</dl></div>
    {path && <svg className={`cosmos-market__chart cosmos-market__chart--${tone}`} viewBox="0 0 300 80" role="img" aria-label={`${network.presentation.projectName} 24 hour USD price history`}><g className="cosmos-market__guides"><line x1="0" x2="300" y1="20" y2="20" /><line x1="0" x2="300" y1="40" y2="40" /><line x1="0" x2="300" y1="60" y2="60" /></g><path className="cosmos-market__area" d={`${path} L300,80 L0,80 Z`} /><path className="cosmos-market__line" d={path} /></svg>}
  </section>
}

export function CosmosOverview({ network, overview: suppliedOverview, blocks: suppliedBlocks, averageBlockSeconds }) {
  const overview = suppliedOverview
  const blocks = suppliedBlocks
  const market = useCosmosResource(`/api/networks/${network.id}/market`, 30000)
  const history = useCosmosResource(`/api/networks/${network.id}/market/history`, 60000)
  if (overview.loading) return <p>Loading {network.presentation.projectName} overview…</p>
  if (!overview.data) return <div className="cosmos-error"><h2>Overview unavailable</h2><p>{overview.error}</p></div>
  return <CosmosOverviewView data={overview.data} market={market.data} marketError={market.error} history={history.data} blocks={blocks.data?.blocks || []} blocksError={blocks.error} blocksStale={blocks.stale} stale={overview.stale} network={network} averageBlockSeconds={averageBlockSeconds} />
}

export function CosmosOverviewView({ data, market, marketError, history, blocks = [], blocksError, blocksStale = false, stale = false, network, averageBlockSeconds }) {
  const latestHeight = blocks[0]?.height ?? data.network.current_local_height
  const firstBlockHeight = blocks[0]?.height ?? null
  const previousHeight = useRef(null); const previousFirst = useRef(null)
  const [updatedHeight, setUpdatedHeight] = useState(null); const [insertedHeight, setInsertedHeight] = useState(null)
  useEffect(() => { const timers = []; if (previousHeight.current !== null && latestHeight !== previousHeight.current) { setUpdatedHeight(latestHeight); timers.push(setTimeout(() => setUpdatedHeight(null), 720)) } if (previousFirst.current !== null && firstBlockHeight !== previousFirst.current) { setInsertedHeight(firstBlockHeight); timers.push(setTimeout(() => setInsertedHeight(null), 900)) } previousHeight.current = latestHeight; previousFirst.current = firstBlockHeight; return () => timers.forEach(clearTimeout) }, [firstBlockHeight, latestHeight])
  const status = stale ? 'degraded' : data.network.operational_state || 'unavailable'
  const assets = data.assets_and_supply?.assets || []
  const blockColumns = useMemo(() => [
    { key: 'height', label: 'Height', render: (row) => <a className="table-link" href={`/networks/${network.id}/blocks/${row.height}`}><span className="accent-value mono">#{BigInt(row.height).toLocaleString()}</span></a> },
    { key: 'timestamp', label: 'Time', render: (row) => relativeTime(row.timestamp) },
    { key: 'proposer', label: 'Proposer', render: (row) => row.proposer_moniker ? <CosmosValidatorIdentity moniker={row.proposer_moniker} address={row.proposer_operator_address || row.proposer} /> : <span className="mono muted" title={row.proposer}>{shortAddress(row.proposer)}</span> },
    { key: 'transaction_count', label: 'Txs' },
    { key: 'hash', label: 'Block Hash', render: (row) => <span className="mono muted" title={row.hash}>{shortAddress(row.hash)}</span> },
  ], [network.id])
  const validators = Array.isArray(data.top_active_validators_by_missed_blocks) ? data.top_active_validators_by_missed_blocks.slice(0, 6) : []
  const riskFor = (row) => !sectionUnavailable(data.slashing) ? cosmosLivenessRisk({ missedBlocks: row.missed_blocks_counter, startHeight: row.start_height, currentHeight: data.network.current_local_height, signedWindow: data.slashing.signed_blocks_window, minimumSigned: data.slashing.minimum_signed_per_window, averageBlockSeconds }) : null
  const validatorColumns = [{ key: 'moniker', label: 'Validator', render: (row) => <CosmosValidatorIdentity moniker={row.moniker} address={row.operator_address || row.consensus_address} /> }, { key: 'missed_blocks_counter', label: 'Liveness risk', render: (row) => { const risk = riskFor(row); return <span className="cosmos-risk"><span className="cosmos-risk__summary"><strong>{row.missed_blocks_counter.toLocaleString()} missed</strong>{risk && <><span className="cosmos-risk__secondary">Budget left: {risk.budgetLeft.toLocaleString()}</span><span className="cosmos-risk__secondary">Penalty ETA: {risk.overThreshold ? 'threshold exceeded' : formatApproximateDuration(risk.seconds)}</span></>}<ParameterHelp label="earliest downtime penalty">Estimate assumes future missed blocks continue increasing the rolling missed-block counter. Exact penalty time may change as older misses leave the signing window.</ParameterHelp></span>{risk && <span className={`cosmos-risk__bar cosmos-risk__bar--${risk.tone}`}><i style={{ width: `${risk.usage * 100}%` }} /></span>}</span> } }]
  const staking = data.staking; const mint = data.mint; const slashing = data.slashing; const governance = data.governance; const distribution = data.distribution
  return <div className="cosmos-overview">
    <section className="status-grid" aria-label="Network summary"><Card eyebrow="Latest Block" icon={BlocksIcon} value={`#${BigInt(latestHeight).toLocaleString()}`} meta="Auto-refresh every 5s" href={`/networks/${network.id}/blocks/${latestHeight}`} updating={updatedHeight === latestHeight} /><Card eyebrow="Network Status" icon={NetworkIcon} value={status.charAt(0).toUpperCase() + status.slice(1)} tone={status === 'healthy' ? 'healthy' : status === 'degraded' || status === 'syncing' ? 'degraded' : 'error'} meta={data.network.catching_up ? 'Node is catching up' : stale ? 'Showing last successful response' : 'API connection status'} /><Card eyebrow="Active Validators" icon={ValidatorsIcon} value={sectionUnavailable(staking) ? 'Unavailable' : staking.active_validator_count.toLocaleString()} meta="Current validator set" /><Card eyebrow="Chain ID" icon={ChainIcon} value={network.expectedChainId} meta={<CosmosRpcStatus source={data.network.rpc_status_source} pool={data.network.rpc_pool} />} /></section>
    <div className="dashboard-grid cosmos-dashboard-grid"><section className="panel dashboard-grid__blocks"><div className="panel__heading"><h2>Latest Blocks</h2>{blocksStale ? <span className="panel__meta cosmos-stale">Stale · last successful data</span> : <span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 5s</span>}</div><DataTable columns={blockColumns} rows={blocks.slice(0, 7)} rowKey={(row) => row.height} rowClassName={(row, index) => insertedHeight === null ? '' : index === 0 && row.height === insertedHeight ? 'is-new-row' : 'is-settling-row'} emptyMessage={blocksError ? 'Blocks are currently unavailable.' : 'No locally available blocks.'} /></section><section className="panel dashboard-grid__validators"><div className="panel__heading"><h2>Validators by Missed Blocks</h2><span className="panel__meta">Active set</span></div><DataTable columns={validatorColumns} rows={validators} rowKey={(row) => row.consensus_address} emptyMessage="No active validator misses reported." /></section></div>
    <MarketPanel network={network} market={market} marketError={marketError} history={history} />
    <div className="cosmos-parameters">
      <ParameterCard title="Economy" value={data.assets_and_supply}><dl className="cosmos-metrics">{assets.map((asset) => <Detail key={asset.base} label={`${asset.symbol} supply`} value={formatTokenAmount(asset.total_supply, asset.exponent, asset.symbol)} raw={asset.total_supply} />)}{!sectionUnavailable(distribution) && Object.entries(distribution.community_pool || {}).map(([denom, amount]) => { const asset = network.assets?.find((item) => item.base === denom); return <Detail key={denom} label={`Community pool · ${asset?.symbol || denom}`} value={asset ? formatTokenAmount(amount, asset.exponent, asset.symbol) : amount} raw={amount} /> })}</dl></ParameterCard>
      <ParameterCard title="Staking / Validator Set" value={staking}><dl className="cosmos-metrics">{(() => { const asset = network.assets?.find((item) => item.base === staking?.bond_denom); return <><Detail label="Bonded tokens" value={asset ? formatTokenAmount(staking?.bonded_tokens, asset.exponent, asset.symbol) : '—'} raw={staking?.bonded_tokens} /><Detail label="Bonded ratio" value={formatProtocolPercent(staking?.bonded_ratio)} raw={staking?.bonded_ratio} /><Detail label="Active validators" value={staking?.active_validator_count ?? '—'} /><Detail label="Max validators" value={staking?.max_validators ?? '—'} /><Detail label="Unbonding time" value={formatProtocolDuration(staking?.unbonding_time)} raw={staking?.unbonding_time} /></> })()}</dl><Advanced>{(() => { const asset = network.assets?.find((item) => item.base === staking?.bond_denom); return <Detail label="Not bonded tokens" value={asset ? formatTokenAmount(staking?.not_bonded_tokens, asset.exponent, asset.symbol) : '—'} /> })()}<Detail label="Max entries" value={staking?.max_entries ?? '—'} /><Detail label="Historical entries" value={staking?.historical_entries ?? '—'} /><Detail label="Bond denom" value={staking?.bond_denom ?? '—'} /><Detail label="Commission limits" value={[formatProtocolPercent(staking?.min_commission_rate), formatProtocolPercent(staking?.max_commission_rate)].join(' – ')} /></Advanced></ParameterCard>
      <ParameterCard title="Inflation / Mint" value={mint}><dl className="cosmos-metrics"><Detail label="Current inflation" value={formatProtocolPercent(mint?.current_inflation)} /><Detail label="Goal bonded" value={formatProtocolPercent(mint?.goal_bonded)} /><Detail label="Inflation range" value={`${formatProtocolPercent(mint?.inflation_min)} – ${formatProtocolPercent(mint?.inflation_max)}`} /><Detail label="Annual rate change" value={formatProtocolPercent(mint?.inflation_rate_change)} /><Detail label="Blocks per year" value={mint?.blocks_per_year?.toLocaleString() ?? '—'} /></dl></ParameterCard>
      <ParameterCard title="Governance" value={governance}><dl className="cosmos-metrics"><Detail label="Quorum" value={formatProtocolPercent(governance?.quorum)} /><Detail label="Threshold" value={formatProtocolPercent(governance?.threshold)} /><Detail label="Voting period" value={formatProtocolDuration(governance?.voting_period)} /></dl><Advanced><Detail label="Maximum deposit period" value={formatProtocolDuration(governance?.maximum_deposit_period)} /><Detail label="Minimum deposit" value={Object.entries(governance?.minimum_deposit || {}).map(([denom, amount]) => `${amount} ${denom}`).join(', ') || '—'} /></Advanced></ParameterCard>
      <ParameterCard title="Security / Slashing" value={slashing}><dl className="cosmos-metrics"><Detail label="Signed blocks window" value={slashing?.signed_blocks_window?.toLocaleString() ?? '—'} /><Detail label="Allowed misses" value={slashing?.allowed_missed_threshold?.toLocaleString() ?? '—'} /><Detail label="Minimum signed" value={formatProtocolPercent(slashing?.minimum_signed_per_window)} /></dl><Advanced><Detail label="Downtime jail" value={formatProtocolDuration(slashing?.downtime_jail_duration)} /><Detail label="Downtime slash" value={formatProtocolPercent(slashing?.downtime_slash_fraction)} /><Detail label="Double-sign slash" value={formatProtocolPercent(slashing?.double_sign_slash_fraction)} /></Advanced></ParameterCard>
      <ParameterCard title="Distribution / Economics" value={distribution}><dl className="cosmos-metrics"><Detail label="Community tax" value={formatProtocolPercent(distribution?.community_tax)} /><Detail label="Withdraw address" value={distribution?.withdraw_address_enabled ? 'Enabled' : 'Disabled'} />{distribution?.nakamoto_bonus && <Detail label="Nakamoto Bonus" value={distribution.nakamoto_bonus.enabled ? 'Enabled' : 'Disabled'} />}</dl>{distribution?.nakamoto_bonus && <Advanced><Detail label="Bonus coefficient" value={`${distribution.nakamoto_bonus.minimum_coefficient} – ${distribution.nakamoto_bonus.maximum_coefficient}`} /><Detail label="Bonus period" value={distribution.nakamoto_bonus.period_epoch_identifier} /></Advanced>}</ParameterCard>
    </div>
    <section className="panel cosmos-node-strip"><div className="panel__heading"><h2>Node / Network</h2></div><dl><Detail label="Tx index" value={data.network.tx_index} /><Detail label="Application" value={[data.network.application_name, data.network.application_version].filter(Boolean).join(' ') || '—'} /><Detail label="SDK" value={data.network.sdk_version || '—'} /><Detail label="CometBFT" value={data.network.cometbft_version || '—'} /><Detail label="Node version" value={data.network.node_version || '—'} /><Detail label="Block history" value={data.network.block_history_state} /><Detail label="Historical state" value={data.network.historical_state} /></dl></section>
  </div>
}
