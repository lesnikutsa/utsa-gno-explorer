import { useMemo, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'

const TABS = ['active', 'inactive', 'jailed']
const fmt = (raw, exponent = 0, digits = 0) => Number(raw || 0) / 10 ** exponent
const signed = (value, digits = 0) => `${value > 0 ? '+' : ''}${Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })}`
const duration = (seconds) => seconds == null ? '—' : `≈${Math.floor(seconds / 3600)}h${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}m`

export function CosmosValidators({ network }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/validators`, 15000)
  const [tab, setTab] = useState('active')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('tokens')
  const [direction, setDirection] = useState(-1)
  const data = resource.data
  const asset = data?.asset || network.presentation.nativeToken
  const rows = useMemo(() => (data?.validators || []).filter((item) => item.category === tab && `${item.moniker} ${item.operator_address}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => {
    const av = sort === 'moniker' ? a.moniker.toLowerCase() : Number(a[sort] ?? a.liveness?.missed_blocks ?? 0)
    const bv = sort === 'moniker' ? b.moniker.toLowerCase() : Number(b[sort] ?? b.liveness?.missed_blocks ?? 0)
    return (av < bv ? -1 : av > bv ? 1 : 0) * direction
  }), [data, tab, query, sort, direction])
  const chooseSort = (key) => { if (sort === key) setDirection((v) => -v); else { setSort(key); setDirection(key === 'moniker' ? 1 : -1) } }
  if (!data && resource.loading) return <section className="cosmos-validators"><p>Loading validators…</p></section>
  if (!data) return <section className="cosmos-validators"><p className="cosmos-error">Validator data is temporarily unavailable.</p></section>
  const counts = Object.fromEntries(TABS.map((kind) => [kind, data.validators.filter((v) => v.category === kind).length]))
  const bonded = fmt(data.summary.bonded_tokens, asset.exponent)
  return <section className="cosmos-validators">
    <header className="page-heading"><div><span className="eyebrow">Consensus</span><h1>Validators</h1><p>Voting power, stake movement, and live signing risk.</p></div></header>
    <div className="cosmos-validator-summary">
      <article><span>Active validators</span><strong>{data.summary.active_validators}</strong></article>
      <article><span>Bonded tokens</span><strong>{bonded.toLocaleString(undefined, { maximumFractionDigits: 2 })} {asset.symbol}</strong></article>
      <article><span>Bonded ratio</span><strong>{data.summary.bonded_ratio == null ? '—' : `${(data.summary.bonded_ratio * 100).toFixed(2)}%`}</strong></article>
      <article><span>24h bonded change</span><strong>{data.summary.bonded_change_24h == null ? 'Collecting history' : `${signed(fmt(data.summary.bonded_change_24h, asset.exponent), 2)} ${asset.symbol}`}</strong></article>
    </div>
    <div className="cosmos-validator-toolbar"><div className="cosmos-validator-tabs" role="tablist">{TABS.map((kind) => <button key={kind} role="tab" aria-selected={tab === kind} className={tab === kind ? 'is-active' : ''} onClick={() => setTab(kind)}>{kind[0].toUpperCase() + kind.slice(1)} <b>{counts[kind]}</b></button>)}</div><input aria-label="Search validators" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search moniker or valoper address" /></div>
    <div className="table-scroll cosmos-validator-table"><table className="data-table"><thead><tr><th>#</th><th><button onClick={() => chooseSort('moniker')}>Validator</button></th><th><button onClick={() => chooseSort('tokens')}>Voting power</button></th>{tab !== 'jailed' && <th><button onClick={() => chooseSort('change_24h')}>24h change</button></th>}{tab === 'jailed' && <><th><button onClick={() => chooseSort('missed_blocks')}>Missed blocks</button></th><th>Jailed until</th><th>Tombstoned</th></>}<th><button onClick={() => chooseSort('commission')}>Commission</button></th>{tab === 'active' && <th><button onClick={() => chooseSort('missed_blocks')}>Signing / liveness</button></th>}</tr></thead>
    <tbody>{rows.map((validator, index) => <tr key={validator.operator_address}><td>{index + 1}</td><td><CosmosValidatorIdentity moniker={validator.moniker} address={validator.operator_address} /></td><td><strong>{fmt(validator.tokens, asset.exponent).toLocaleString(undefined, { maximumFractionDigits: 2 })} {asset.symbol}</strong><small>{validator.stake_share.toFixed(2)}%</small></td>{tab !== 'jailed' && <td><Delta validator={validator} asset={asset} /></td>}{tab === 'jailed' && <><td>{validator.missed_blocks ?? '—'}</td><td>{validator.jailed_until || '—'}</td><td>{validator.tombstoned == null ? '—' : validator.tombstoned ? 'Yes' : 'No'}</td></>}<td>{(Number(validator.commission) * 100).toFixed(2)}%</td>{tab === 'active' && <td><Liveness validator={validator} state={data.signing_history_state} /></td>}</tr>)}</tbody></table></div>
  </section>
}
function Delta({ validator, asset }) { if (validator.change_24h == null) return <span className="muted">Collecting history</span>; const value = fmt(validator.change_24h, asset.exponent); const tone = value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral'; return <span className={`validator-delta is-${tone}`}><strong>{signed(value, 2)} {asset.symbol}</strong><small>{signed(validator.change_24h_percent, 2)}%</small></span> }
function Liveness({ validator, state }) { const live = validator.liveness; if (!live) return <span className="muted">Liveness unavailable</span>; const strip = validator.signing_strip || []; return <div className="validator-liveness"><div><strong>{live.missed_blocks.toLocaleString()} missed</strong> · {live.signed_percent.toFixed(2)}% signed</div><small>Budget left: {live.remaining_budget.toLocaleString()} · Jail ETA: <span title="Estimated time until the missed-block threshold if the validator continues missing every block.">{duration(live.jail_eta_seconds)} ⓘ</span></small><div className="validator-budget"><i style={{ width: `${Math.min(100, live.allowed_misses ? live.missed_blocks / live.allowed_misses * 100 : 100)}%` }} /></div>{strip.length ? <div className="validator-signing-strip" aria-label="Recent 50-block signing history">{strip.map((point, i) => <i key={i} className={`is-${point}`} title={point} />)}</div> : <small className="muted">{state === 'warming' ? 'Loading recent signing history…' : 'Recent history unavailable'}</small>}</div> }
