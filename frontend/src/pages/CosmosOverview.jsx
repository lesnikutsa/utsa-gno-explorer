import { useCosmosResource } from '../hooks/useCosmosResource'

const unavailable = (value) => value?.error ? 'Unavailable' : value ?? '—'
const amount = (value, exponent = 6) => {
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return '—'
  const padded = value.padStart(exponent + 1, '0')
  return `${padded.slice(0, -exponent)}.${padded.slice(-exponent).replace(/0+$/, '') || '0'}`
}
function Section({ title, value, children }) {
  return <section className="cosmos-card"><h2>{title}</h2>{value?.error ? <p className="cosmos-error">Section unavailable</p> : children}</section>
}
export function CosmosOverview({ network }) {
  const overview = useCosmosResource(`/api/networks/${network.id}/overview`)
  const market = useCosmosResource(`/api/networks/${network.id}/market`, 30000)
  if (overview.loading) return <p>Loading AtomOne overview…</p>
  if (!overview.data) return <div className="cosmos-error"><h2>Overview unavailable</h2><p>{overview.error}</p></div>
  return <CosmosOverviewView data={overview.data} market={market.data} marketError={market.error} stale={overview.stale} />
}

export function CosmosOverviewView({ data, market, marketError, stale = false }) {
  return <><div className="cosmos-title"><div><p className="eyebrow">Cosmos network</p><h1>AtomOne Overview</h1></div>{stale && <span>Stale data</span>}</div>
    <div className="cosmos-grid">
      <Section title="Network status"><dl><dt>Status</dt><dd>{data.network.operational_state}</dd><dt>Local RPC height</dt><dd>{data.network.current_local_height}</dd><dt>Latest block time</dt><dd>{data.network.latest_block_time}</dd><dt>Syncing</dt><dd>{data.network.catching_up ? 'Yes' : 'No'}</dd></dl></Section>
      <Section title="ATONE market"><dl><dt>Price</dt><dd>{market ? `$${market.price}` : unavailable(marketError)}</dd><dt>Market cap</dt><dd>{market ? `$${market.market_cap}` : '—'}</dd><dt>24h</dt><dd>{market?.change_24h ?? '—'}%</dd></dl></Section>
      <Section title="Supply" value={data.assets_and_supply}><dl>{data.assets_and_supply.assets?.map((asset) => <div key={asset.base}><dt>{asset.symbol}</dt><dd>{amount(asset.total_supply, asset.exponent)}</dd></div>)}</dl></Section>
      <Section title="Staking" value={data.staking}><dl><dt>Bonded</dt><dd>{amount(data.staking.bonded_tokens)}</dd><dt>Bonded ratio</dt><dd>{data.staking.bonded_ratio}</dd><dt>Active validators</dt><dd>{data.staking.active_validator_count}</dd></dl></Section>
      <Section title="Mint" value={data.mint}><dl><dt>Inflation</dt><dd>{data.mint.current_inflation}</dd><dt>Goal bonded</dt><dd>{data.mint.goal_bonded}</dd></dl></Section>
      <Section title="Slashing" value={data.slashing}><p title="Protocol slashing counter, not Gno health over the last 1000 blocks.">Signed window: {data.slashing.signed_blocks_window}; allowed misses: {data.slashing.allowed_missed_threshold}. Distance to this threshold does not guarantee blocks until jail.</p></Section>
      <Section title="Governance" value={data.governance}><dl><dt>Quorum</dt><dd>{data.governance.quorum}</dd><dt>Threshold</dt><dd>{data.governance.threshold}</dd><dt>Voting period</dt><dd>{data.governance.voting_period}</dd></dl></Section>
      <Section title="Distribution" value={data.distribution}><dl><dt>Community tax</dt><dd>{data.distribution.community_tax}</dd><dt>Withdraw address</dt><dd>{data.distribution.withdraw_address_enabled ? 'Enabled' : 'Disabled'}</dd></dl></Section>
      <Section title="Top active validators by missed blocks" value={data.top_active_validators_by_missed_blocks}>{Array.isArray(data.top_active_validators_by_missed_blocks) && data.top_active_validators_by_missed_blocks.length ? <ol>{data.top_active_validators_by_missed_blocks.map((validator) => <li key={validator.consensus_address}>{validator.moniker}: {validator.missed_blocks_counter}</li>)}</ol> : <p>No active validator misses reported.</p>}</Section>
    </div></>
}
