import { useEffect, useMemo, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { CopyButton } from '../components/CopyButton'
import { formatSignedTokenAmount, formatTokenAmount } from '../utils/cosmosFormat'
import { loadValidatorFavorites, saveValidatorFavorites, toggleValidatorFavorite } from '../utils/validatorFavorites'
import { missedCountClass, validatorRankTone } from '../utils/cosmosValidators'

const pct = (v) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`
const utc = (v) => !v || v.startsWith('1970-01-01T00:00:00') ? '—' : new Date(v).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
const label = (v) => v[0].toUpperCase() + v.slice(1)
const eta = (v) => v == null ? '—' : v === 0 ? 'Threshold reached' : `≈${Math.floor(v / 3600)}h ${Math.floor(v % 3600 / 60)}m`
const website = (v) => { try { const u = new URL(v); return ['http:', 'https:'].includes(u.protocol) ? u.href : null } catch { return null } }
const websiteText = (value) => { const url = new URL(value); const text = `${url.hostname}${url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '')}`; return text.length > 48 ? `${text.slice(0, 45)}…` : text }
const emailHref = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value || '') ? `mailto:${value}` : null
const readableDecimal = (value) => { const [whole, fraction = ''] = String(value ?? '—').split('.'); const decimals = fraction.slice(0, 6).replace(/0+$/, ''); const grouped = /^\d+$/.test(whole) ? BigInt(whole).toLocaleString() : whole; return decimals ? `${grouped}.${decimals}` : grouped }
const minimumSelfDelegation = (value, asset) => value == null ? '—' : BigInt(value) < 10n ** BigInt(asset.exponent) ? `${BigInt(value).toLocaleString()} ${asset.base}` : formatTokenAmount(value, asset.exponent, asset.symbol)

export function CosmosValidatorDetail({ network, operatorAddress }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/validators/${encodeURIComponent(operatorAddress)}`, 5000)
  const key = `cosmos:${network.id}`
  const [favorites, setFavorites] = useState(() => loadValidatorFavorites(key))
  useEffect(() => setFavorites(loadValidatorFavorites(key)), [key])
  const v = resource.data
  const counts = useMemo(() => (v?.signing_strip || []).reduce((a, p) => ({ ...a, [p.status]: a[p.status] + 1 }), { commit: 0, nil: 0, absent: 0, unknown: 0 }), [v])
  if (!v && resource.loading) return <section className="cosmos-validator-detail"><p>Loading validator…</p></section>
  if (!v) return <section className="cosmos-validator-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/validators`}>← Back to Validators</a><p className="cosmos-error">Validator not found or temporarily unavailable.</p></section>
  const asset = v.asset, favorite = favorites.has(v.operator_address), strip = v.signing_strip || [], site = website(v.website)
  const finalized = counts.commit + counts.nil + counts.absent
  const participation = finalized ? (counts.commit + counts.nil) * 100 / finalized : null
  const oldestPoint = strip[0], newestPoint = strip[strip.length - 1]
  const toggle = () => setFavorites((current) => { const next = toggleValidatorFavorite(current, v.operator_address); saveValidatorFavorites(key, next); return next })
  return <section className="cosmos-validator-detail theme-compatible">
    <a className="cosmos-back block-detail__back" href={`/networks/${network.id}/validators`}>← Back to Validators</a>
    <header className="panel cosmos-validator-hero">
      <div className="cosmos-validator-hero__profile">
        <div className="cosmos-validator-hero__main"><CosmosValidatorIdentity moniker={v.moniker} address={v.operator_address} imageSrc={v.avatar_url} showTitles={false} fullAddress metadata={v.identity} action={<button className={`validator-favorite ${favorite ? 'validator-favorite--active' : ''}`} type="button" aria-pressed={favorite} aria-label={`${favorite ? 'Remove' : 'Add'} ${v.moniker} ${favorite ? 'from' : 'to'} favorites`} onClick={toggle}>{favorite ? '★' : '☆'}</button>} /></div>
        {(site || v.contact) && <dl className="cosmos-validator-hero__metadata">{site && <div><dt>Website</dt><dd><a href={site} target="_blank" rel="noopener noreferrer">{websiteText(site)} ↗</a></dd></div>}{v.contact && <div><dt>Contact</dt><dd>{emailHref(v.contact) ? <a href={emailHref(v.contact)}>{v.contact}</a> : v.contact}</dd></div>}</dl>}
      </div>
      <div className="cosmos-validator-hero__facts"><Field label="Rank" value={<span className={`cosmos-validator-rank cosmos-validator-rank--${validatorRankTone(v.stake_share)}`}>#{v.rank}</span>} /><Field label="Status" value={label(v.bond_status)} /><Field label="Jailed" value={v.jailed ? 'Yes' : 'No'} /><Field label="Commission" value={pct(v.commission.rate)} /></div>
      {v.jailed && <div className="cosmos-validator-jailed"><strong>Jailed</strong><span>Until: {utc(v.jailed_until)}</span>{v.tombstoned != null && <span>Tombstoned: {v.tombstoned ? 'Yes' : 'No'}</span>}</div>}
      <div className="cosmos-validator-hero__metrics"><Metric label="Voting Power" value={formatTokenAmount(v.tokens, asset.exponent, asset.symbol)} /><Metric label="Stake Share" value={`${v.stake_share.toFixed(4)}%`} /><Metric label="≈24h Change" value={<Delta validator={v} asset={asset} />} /><Metric label="Minimum Self Delegation" value={minimumSelfDelegation(v.min_self_delegation, asset)} /></div>
      {v.description && <p className="cosmos-validator-hero__description">{v.description}</p>}
    </header>
    <div className="cosmos-validator-detail__primary">
    <section className="panel cosmos-validator-signing"><div className="panel__heading"><div><h2>Signing &amp; Liveness</h2><span className="panel__meta">Canonical finalized consensus participation</span></div></div><div className="cosmos-validator-signing__recent"><h3>Recent finalized participation</h3><div className="cosmos-validator-signing__stats cosmos-validator-signing__mini-metrics"><Field label="Participation" value={participation == null ? '—' : `${participation.toFixed(2)}%`} /><Field label="Commit" value={counts.commit} /><Field label="Nil" value={counts.nil} /><Field label="Absent" value={counts.absent} />{counts.unknown > 0 && <Field label="Unknown" value={counts.unknown} />}</div>{strip.length ? <div className="cosmos-validator-signing__monitor"><div className="cosmos-validator-signing__strip" aria-label="Recent 50-block canonical signing panel">{strip.map((p) => <span key={p.height} tabIndex="0" className={`is-${p.status}`} aria-label={`Block #${p.height} · ${label(p.status)}${p.time ? ` · ${new Date(p.time).toISOString()}` : ''}`} />)}</div><div className="cosmos-validator-signing__range"><span>Past #{oldestPoint.height.toLocaleString()}</span><span>Latest finalized #{newestPoint.height.toLocaleString()}</span></div></div> : <p className="muted">{v.signing_history_state === 'warming' ? 'Loading recent signing history…' : 'Recent participation unavailable for this validator.'}</p>}</div><div className="cosmos-validator-signing__protocol"><div><h3>Protocol slashing window</h3><p>Values come from x/slashing SigningInfo and are separate from the visible 50 blocks.</p></div>{v.liveness ? <div className="cosmos-validator-signing__stats"><Field label="Missed blocks counter" value={<span className={missedCountClass(v.liveness.missed_blocks)}>{v.liveness.missed_blocks.toLocaleString()}</span>} /><Field label="Signed percent" value={`${v.liveness.signed_percent.toFixed(2)}%`} /><Field label="Remaining budget" value={v.liveness.remaining_budget.toLocaleString()} /><Field label="Jail ETA" value={eta(v.liveness.jail_eta_seconds)} /></div> : <span className="muted">Protocol liveness unavailable</span>}</div></section>
      <Panel title="Consensus Identity"><Address label="Account Address" value={v.account_address} /><Address label="Operator Address" value={v.operator_address} /><Address label="Consensus Address (ValCons)" value={v.consensus_address} /><Address label="Consensus Public Key" value={v.consensus_pubkey} full /><Address label="Hex Address" value={v.hex_address} /><Address label="EVM Address" value={v.evm_address} /></Panel>
    </div>
    <div className="cosmos-validator-detail__secondary"><Panel title="Validator Parameters"><Field label="Bonded Tokens" value={formatTokenAmount(v.tokens, asset.exponent, asset.symbol)} /><Field label="Minimum Self Delegation" value={minimumSelfDelegation(v.min_self_delegation, asset)} /></Panel><Panel title="Validator Economics"><Field label="Delegator Shares" value={readableDecimal(v.delegator_shares)} /><Field label="Commission Rate" value={pct(v.commission.rate)} />{v.commission.max_rate != null && <Field label="Max Commission" value={pct(v.commission.max_rate)} />}{v.commission.max_change_rate != null && <Field label="Max Daily Change" value={pct(v.commission.max_change_rate)} />}{v.commission.update_time && <Field label="Commission Updated" value={utc(v.commission.update_time)} />}</Panel></div>
  </section>
}
function Metric({ label, value }) { return <article className="card status-card cosmos-validator-summary__card"><span>{label}</span><strong>{value}</strong></article> }
function Field({ label, value }) { return <div><dt>{label}</dt><dd>{value}</dd></div> }
function Panel({ title, children }) { return <section className="panel cosmos-validator-fields"><h2>{title}</h2><dl>{children}</dl></section> }
function Address({ label, value, full = false }) { const display = value || '—'; return <div><dt>{label}</dt><dd className={`cosmos-copy-value cosmos-validator-address${full ? ' is-full' : ''}`}><code>{display}</code>{value && <CopyButton value={value} label={label.toLowerCase()} />}</dd></div> }
function Delta({ validator: v, asset }) { if (v.change_24h == null || Number(v.change_24h) === 0) return '—'; const positive = Number(v.change_24h) > 0; return <span className={`validator-delta is-${positive ? 'positive' : 'negative'}`}>{formatSignedTokenAmount(v.change_24h, asset.exponent, asset.symbol)}</span> }
