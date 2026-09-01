import { useEffect, useMemo, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { loadValidatorFavorites, saveValidatorFavorites, toggleValidatorFavorite } from '../utils/validatorFavorites'
import { cosmosRiskToneFromUsage } from '../utils/cosmosSlashing'
import { compareIntegerStrings } from '../utils/validatorHealth'
import { directedValidatorComparison, favoriteFirst, missedCountClass } from '../utils/cosmosValidators'

const TABS = ['active', 'inactive', 'jailed']
const fmt = (raw, exponent = 0) => Number(raw || 0) / 10 ** exponent
const signed = (value, digits = 0) => `${value > 0 ? '+' : ''}${Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })}`
const duration = (seconds) => seconds == null ? '—' : `≈${Math.floor(seconds / 3600)}h${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}m`
const arrow = (key, sort, direction) => key !== sort ? '↕' : direction > 0 ? '↑' : '↓'
const pointTime = (point) => point.time ? `${new Date(point.time).toISOString().slice(11, 19)} UTC` : null
const jailedUntil = (value) => !value || value.startsWith('1970-01-01T00:00:00') ? '—' : new Date(value).toLocaleString()


export function CosmosValidators({ network }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/validators`, 15000)
  const [tab, setTab] = useState('active')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('tokens')
  const [direction, setDirection] = useState(-1)
  const [favorites, setFavorites] = useState(() => loadValidatorFavorites(`cosmos:${network.id}`))
  const data = resource.data
  const asset = data?.asset || network.presentation.nativeToken
  useEffect(() => setFavorites(loadValidatorFavorites(`cosmos:${network.id}`)), [network.id])
  const powerRanks = useMemo(() => {
    const ranks = new Map()
    for (const category of TABS) {
      ;[...(data?.validators || [])].filter((item) => item.category === category)
        .sort((a, b) => compareIntegerStrings(b.tokens, a.tokens) || a.operator_address.localeCompare(b.operator_address))
        .forEach((item, index) => ranks.set(item.operator_address, index + 1))
    }
    return ranks
  }, [data])
  const rows = useMemo(() => {
    const filtered = (data?.validators || []).filter((item) => item.category === tab && `${item.moniker} ${item.operator_address}`.toLowerCase().includes(query.toLowerCase()))
    const compare = (a, b) => directedValidatorComparison(a, b, sort, direction)
      || (powerRanks.get(a.operator_address) - powerRanks.get(b.operator_address))
    return favoriteFirst(filtered, favorites, compare)
  }, [data, tab, query, sort, direction, favorites, powerRanks])
  const chooseSort = (key) => { if (sort === key) setDirection((v) => -v); else { setSort(key); setDirection(key === 'moniker' ? 1 : -1) } }
  const toggleFavorite = (address) => setFavorites((current) => { const next = toggleValidatorFavorite(current, address); saveValidatorFavorites(`cosmos:${network.id}`, next); return next })
  const SortHeader = ({ field, children }) => <button className={`data-table__sort ${sort === field ? 'is-active' : ''}`} onClick={() => chooseSort(field)}>{children}<span className="data-table__sort-arrow" aria-hidden="true">{arrow(field, sort, direction)}</span></button>
  if (!data && resource.loading) return <section className="cosmos-validators"><p>Loading validators…</p></section>
  if (!data) return <section className="cosmos-validators"><p className="cosmos-error">Validator data is temporarily unavailable.</p></section>
  const counts = Object.fromEntries(TABS.map((kind) => [kind, data.validators.filter((v) => v.category === kind).length]))
  const bonded = fmt(data.summary.bonded_tokens, asset.exponent)
  return <section className="cosmos-validators">
    <header className="cosmos-validators__heading"><h1>Validators</h1></header>
    <div className="cosmos-validator-summary">
      <article><span>Active validators</span><strong>{data.summary.active_validators}</strong></article>
      <article><span>Bonded tokens</span><strong>{bonded.toLocaleString(undefined, { maximumFractionDigits: 2 })} {asset.symbol}</strong></article>
      <article><span>Bonded ratio</span><strong>{data.summary.bonded_ratio == null ? '—' : `${(data.summary.bonded_ratio * 100).toFixed(2)}%`}</strong></article>
      <article><span>24h bonded change</span><strong>{data.summary.bonded_change_24h == null ? 'History unavailable' : `${signed(fmt(data.summary.bonded_change_24h, asset.exponent), 2)} ${asset.symbol}`}</strong></article>
    </div>
    <div className="cosmos-validator-toolbar"><div className="cosmos-validator-tabs" role="tablist">{TABS.map((kind) => <button key={kind} role="tab" aria-selected={tab === kind} className={tab === kind ? 'is-active' : ''} onClick={() => setTab(kind)}>{kind[0].toUpperCase() + kind.slice(1)} <b>{counts[kind]}</b></button>)}</div><input aria-label="Search validators" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search moniker or valoper address" /></div>
    <div className="table-scroll cosmos-validator-table"><table className="data-table"><thead><tr><th>#</th><th><SortHeader field="moniker">Validator</SortHeader></th><th><SortHeader field="tokens">Voting power</SortHeader></th>{tab === 'active' && <th><SortHeader field="change_24h">24h change</SortHeader></th>}{tab === 'jailed' && <><th>Jailed until</th><th>Tombstoned</th></>}<th><SortHeader field="commission">Commission</SortHeader></th>{tab === 'active' && <th><SortHeader field="missed_blocks">Signing / liveness</SortHeader></th>}</tr></thead>
    <tbody>{rows.map((validator) => <tr key={validator.operator_address}><td>{powerRanks.get(validator.operator_address)}</td><td><span className="cosmos-validator-favorite-identity"><button className={`validator-favorite ${favorites.has(validator.operator_address) ? 'validator-favorite--active' : ''}`} type="button" aria-pressed={favorites.has(validator.operator_address)} aria-label={`${favorites.has(validator.operator_address) ? 'Remove' : 'Add'} ${validator.moniker} ${favorites.has(validator.operator_address) ? 'from' : 'to'} favorites`} onClick={() => toggleFavorite(validator.operator_address)}>{favorites.has(validator.operator_address) ? '★' : '☆'}</button><CosmosValidatorIdentity moniker={validator.moniker} address={validator.operator_address} imageSrc={validator.avatar_url} showTitles={false} /></span></td><td><strong>{fmt(validator.tokens, asset.exponent).toLocaleString(undefined, { maximumFractionDigits: 2 })} {asset.symbol}</strong><small className="cosmos-validator-stake-share">{validator.stake_share.toFixed(2)}%</small></td>{tab === 'active' && <td><Delta validator={validator} asset={asset} /></td>}{tab === 'jailed' && <><td>{jailedUntil(validator.jailed_until)}</td><td>{validator.tombstoned == null ? '—' : validator.tombstoned ? 'Yes' : 'No'}</td></>}<td>{(Number(validator.commission) * 100).toFixed(2)}%</td>{tab === 'active' && <td><Liveness validator={validator} state={data.signing_history_state} /></td>}</tr>)}</tbody></table></div>
  </section>
}
function Delta({ validator, asset }) { if (validator.change_24h == null) return <span className="muted">History unavailable</span>; if (validator.change_24h === '0') return <span className="muted">—</span>; const value = fmt(validator.change_24h, asset.exponent); const tone = value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral'; return <span className={`validator-delta is-${tone}`}><strong>{signed(value, 2)} {asset.symbol}</strong><small>{validator.change_24h_percent == null ? '—' : `${signed(validator.change_24h_percent, 2)}%`}</small></span> }
function Liveness({ validator, state }) { const live = validator.liveness; if (!live) return <span className="muted">Liveness unavailable</span>; const strip = validator.signing_strip || []; const usage = live.allowed_misses ? live.missed_blocks / live.allowed_misses : 1; const tone = cosmosRiskToneFromUsage(usage); return <div className="validator-liveness"><div><strong className={missedCountClass(live.missed_blocks)}>{live.missed_blocks.toLocaleString()} missed</strong> · {live.signed_percent.toFixed(2)}% signed</div><small>Budget left: {live.remaining_budget.toLocaleString()} · Jail ETA: <span>{duration(live.jail_eta_seconds)}</span></small><div className={`validator-budget cosmos-risk__bar cosmos-risk__bar--${tone}`}><i style={{ width: `${Math.min(100, usage * 100)}%` }} /></div>{strip.length ? <div className="validator-signing-strip" aria-label="Recent 50-block signing history">{strip.map((point) => <i key={point.height} className={`is-${point.status}`} aria-label={`Block ${point.height} ${point.status}${pointTime(point) ? ` ${pointTime(point)}` : ""}`} />)}</div> : <small className="muted">{state === 'warming' ? 'Loading recent signing history…' : 'Recent history unavailable'}</small>}</div> }
