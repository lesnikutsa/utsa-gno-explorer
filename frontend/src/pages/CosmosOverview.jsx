import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { InfoTip } from '../components/InfoTip'
import { getCosmosMarket, getCosmosOverview } from '../services/api'
import { formatBaseAmount, formatMarketPercent, formatRatio, isSectionError } from '../utils/cosmosFormat'
import { useCosmosResource } from '../hooks/useCosmosResource'

const value = (candidate, suffix = '') => candidate === null || candidate === undefined ? '—' : `${candidate}${suffix}`
const date = (candidate) => candidate ? new Date(candidate).toLocaleString() : '—'
const Section = ({ title, data, children }) => <Card><h2>{title}</h2>{isSectionError(data) ? <p className="section-error">This section is temporarily unavailable.</p> : children}</Card>
const Metric = ({ label, children, tip }) => <div className="cosmos-metric"><span>{label}{tip && <InfoTip>{tip}</InfoTip>}</span><strong>{children}</strong></div>

export function CosmosOverview({ network, onIdentity }) {
  const loadOverview = useCallback((signal) => getCosmosOverview(network.id, { signal }), [network.id])
  const loadMarket = useCallback((signal) => getCosmosMarket(network.id, { signal }), [network.id])
  const overview = useCosmosResource(loadOverview)
  const market = useCosmosResource(loadMarket, { interval: 30_000 })
  const data = overview.data
  useEffect(() => { onIdentity(data?.network || null) }, [data?.network, onIdentity])
  if (overview.loading && !data) return <div className="page-state">Loading AtomOne overview…</div>
  if (!data) return <div className="page-state"><h1>AtomOne unavailable</h1><p>{overview.error?.detail || 'Explorer API data is temporarily unavailable.'}</p><button onClick={overview.refresh}>Retry</button></div>
  const staking = data.staking
  const mint = data.mint
  return <div className="cosmos-page">
    <div className="page-heading"><div><span className="eyebrow">Cosmos network</span><h1>AtomOne Overview</h1><p>{data.network.chain_id} · RPC local height {data.network.current_local_height?.toLocaleString()}</p></div><button onClick={overview.refresh}>Refresh</button></div>
    {(overview.stale || market.stale) && <p className="stale-notice">Showing previous data because the latest background refresh failed.</p>}
    <div className="cosmos-grid">
      <Card><h2>Network</h2><Metric label="Status">{data.network.operational_state}</Metric><Metric label="Local RPC height">{value(data.network.current_local_height?.toLocaleString())}</Metric><Metric label="Last block">{date(data.network.latest_block_time)}</Metric></Card>
      <Card><h2>ATONE market</h2>{market.data ? <><Metric label="Price">${Number(market.data.price).toLocaleString()}</Metric><Metric label="24h change">{formatMarketPercent(market.data.change_24h)}</Metric><Metric label="Market cap">${Number(market.data.market_cap).toLocaleString()}</Metric><Metric label="CoinGecko updated">{date(market.data.source_last_updated_at)}</Metric></> : <p className="section-error">Market data is temporarily unavailable. Network data remains available.</p>}</Card>
      <Section title="Supply" data={data.assets_and_supply}>{data.assets_and_supply?.assets?.map((asset) => <Metric key={asset.base} label={asset.symbol}>{formatBaseAmount(asset.total_supply, asset.exponent)} {asset.symbol}</Metric>)}</Section>
      <Section title="Staking" data={staking}><Metric label="Active validators">{value(staking?.active_validator_count)} / {value(staking?.max_validators)}</Metric><Metric label="Bonded tokens">{formatBaseAmount(staking?.bonded_tokens, 6)} ATONE</Metric><Metric label="Bonded ratio" tip="The share of staking tokens currently bonded to active validators.">{formatRatio(staking?.bonded_ratio)}</Metric><Metric label="Unbonding" tip="The protocol waiting period before undelegated tokens become transferable.">{value(staking?.unbonding_time)}</Metric></Section>
      <Section title="Mint" data={mint}><Metric label="Inflation" tip="The current annualized rate at which the protocol expands token supply.">{formatRatio(mint?.current_inflation)}</Metric><Metric label="Target bonded">{formatRatio(mint?.goal_bonded)}</Metric></Section>
      <Section title="Slashing" data={data.slashing}><Metric label="Signing window" tip="Validators may be penalized when their missed-block counter exceeds the protocol threshold in this window.">{value(data.slashing?.signed_blocks_window)}</Metric><Metric label="Allowed misses">{value(data.slashing?.allowed_missed_threshold)}</Metric><Metric label="Downtime jail">{value(data.slashing?.downtime_jail_duration)}</Metric></Section>
      <Section title="Governance" data={data.governance}><Metric label="Quorum" tip="The minimum voting participation required for a proposal to be valid.">{formatRatio(data.governance?.quorum)}</Metric><Metric label="Threshold" tip="The minimum Yes share required among counted votes after quorum is met.">{formatRatio(data.governance?.threshold)}</Metric><Metric label="Voting period">{value(data.governance?.voting_period)}</Metric></Section>
      <Section title="Distribution" data={data.distribution}><Metric label="Community tax">{formatRatio(data.distribution?.community_tax)}</Metric><Metric label="Withdraw address">{data.distribution?.withdraw_address_enabled ? 'Enabled' : 'Disabled'}</Metric></Section>
    </div>
    <Section title="Active validators with most missed blocks" data={data.top_active_validators_by_missed_blocks}><p className="section-note">This is the protocol counter within the slashing window, not Gno health over the last 1,000 blocks. Distance to threshold is not a guaranteed number of blocks before jail.</p><div className="cosmos-validator-list">{data.top_active_validators_by_missed_blocks?.map((validator) => <div key={validator.operator_address}><strong>{validator.moniker}</strong><span>{validator.missed_blocks_counter} missed · {validator.remaining_misses_before_threshold} to threshold</span><span>{validator.jailed ? 'Jailed' : 'Active'}{validator.tombstoned ? ' · Tombstoned' : ''}</span></div>)}</div></Section>
    <details className="cosmos-advanced"><summary>Advanced protocol parameters</summary><pre>{JSON.stringify({ staking: data.staking, mint: data.mint, slashing: data.slashing, governance: data.governance, distribution: data.distribution }, null, 2)}</pre></details>
  </div>
}
