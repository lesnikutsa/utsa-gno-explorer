import { useEffect, useMemo, useRef, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { CosmosAccountLink } from '../components/CosmosAccountLink'
import { CosmosValidatorIdentity } from '../components/CosmosValidatorIdentity'
import { CopyButton } from '../components/CopyButton'
import { ParameterHelp } from '../components/ParameterHelp'
import { getCosmosTransactionByHash, getCosmosValidatorActivity, getCosmosValidatorDelegations } from '../services/api'
import { navigateInternal } from '../utils/navigation'
import { formatDelegationShare, formatSignedTokenAmount, formatTokenAmount } from '../utils/cosmosFormat'
import { loadValidatorFavorites, saveValidatorFavorites, toggleValidatorFavorite } from '../utils/validatorFavorites'
import { missedCountClass, validatorRankTone } from '../utils/cosmosValidators'
import '../styles/cosmos-validator-detail.css'
import '../styles/cosmos-tx-tooltip.css'
import '../styles/cosmos-validator-reward-usd.css'

const pct = (v) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`
const utc = (v) => !v || v.startsWith('1970-01-01T00:00:00') ? '—' : new Date(v).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })
const label = (v) => v[0].toUpperCase() + v.slice(1)
const rankLabel = (category) => ({ active: 'Active Rank', inactive: 'Inactive Rank', jailed: 'Jailed Rank' })[category] || 'Rank'
const eta = (v) => v == null ? '—' : v === 0 ? 'Threshold reached' : `≈${Math.floor(v / 3600)}h ${Math.floor(v % 3600 / 60)}m`
const website = (v) => { try { const u = new URL(v); return ['http:', 'https:'].includes(u.protocol) ? u.href : null } catch { return null } }
const websiteText = (value) => { const url = new URL(value); const text = `${url.hostname}${url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '')}`; return text.length > 48 ? `${text.slice(0, 45)}…` : text }
const emailHref = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value || '') ? `mailto:${value}` : null
const readableDecimal = (value) => { const [whole, fraction = ''] = String(value ?? '—').split('.'); const decimals = fraction.slice(0, 6).replace(/0+$/, ''); const grouped = /^\d+$/.test(whole) ? BigInt(whole).toLocaleString() : whole; return decimals ? `${grouped}.${decimals}` : grouped }
const compactShares = (value) => { const number = Number(value); if (!Number.isFinite(number)) return '—'; const units = [[1e15, 'Q'], [1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']]; const unit = units.find(([size]) => Math.abs(number) >= size); if (!unit) return readableDecimal(value); return `${(number / unit[0]).toFixed(2).replace(/\.0+$|(?<=\.[0-9]*?)0+$/g, '')}${unit[1]}` }
const minimumSelfDelegation = (value, asset) => value == null ? '—' : BigInt(value) < 10n ** BigInt(asset.exponent) ? `${BigInt(value).toLocaleString()} ${asset.base}` : formatTokenAmount(value, asset.exponent, asset.symbol)
const signingPointLabel = (point) => `Block #${point.height} · ${label(point.status)}${point.time ? ` · ${new Date(point.time).toISOString()}` : ''}`

export function CosmosValidatorDetail({ network, operatorAddress }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/validators/${encodeURIComponent(operatorAddress)}`, 5000)
  const market = useCosmosResource(`/api/networks/${network.id}/market`, 30000)
  const key = `cosmos:${network.id}`
  const [favorites, setFavorites] = useState(() => loadValidatorFavorites(key))
  useEffect(() => setFavorites(loadValidatorFavorites(key)), [key])
  const v = resource.data
  const counts = useMemo(() => (v?.signing_strip || []).reduce((a, p) => ({ ...a, [p.status]: a[p.status] + 1 }), { commit: 0, nil: 0, absent: 0, unknown: 0 }), [v])
  const latestHeight = v?.signing_strip?.at(-1)?.height ?? null
  const previousLatestHeight = useRef(null)
  const [animatedHeight, setAnimatedHeight] = useState(null)
  useEffect(() => {
    if (latestHeight == null) return undefined
    if (previousLatestHeight.current == null) { previousLatestHeight.current = latestHeight; return undefined }
    if (previousLatestHeight.current === latestHeight) return undefined
    previousLatestHeight.current = latestHeight
    setAnimatedHeight(latestHeight)
    const timer = window.setTimeout(() => setAnimatedHeight((current) => current === latestHeight ? null : current), 1800)
    return () => window.clearTimeout(timer)
  }, [latestHeight])
  if (!v && resource.loading) return <section className="cosmos-validator-detail"><p>Loading validator…</p></section>
  if (!v) return <section className="cosmos-validator-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/validators`}>← Back to Validators</a><p className="cosmos-error">Validator not found or temporarily unavailable.</p></section>
  const asset = v.asset, favorite = favorites.has(v.operator_address), strip = v.signing_strip || [], site = website(v.website)
  const finalized = counts.commit + counts.nil + counts.absent
  const participation = finalized ? (counts.commit + counts.nil) * 100 / finalized : null
  const oldestPoint = strip[0], newestPoint = strip[strip.length - 1]
  const registeredAssets = network.assets?.length ? network.assets : [asset]
  const commissionRewards = v.commission_rewards?.length ? v.commission_rewards : (v.commission_earned == null ? [] : [{ denom: asset.base, amount: v.commission_earned }])
  const outstandingRewards = v.outstanding_rewards?.length ? v.outstanding_rewards : (v.delegators_total_rewards == null ? [] : [{ denom: asset.base, amount: v.delegators_total_rewards }])
  const toggle = () => setFavorites((current) => { const next = toggleValidatorFavorite(current, v.operator_address); saveValidatorFavorites(key, next); return next })
  return <section className="cosmos-validator-detail theme-compatible">
    <a className="cosmos-back block-detail__back" href={`/networks/${network.id}/validators`}>← Back to Validators</a>
    <header className="panel cosmos-validator-hero">
      <div className="cosmos-validator-hero__profile">
        <div className="cosmos-validator-hero__main"><CosmosValidatorIdentity moniker={v.moniker} address={v.operator_address} imageSrc={v.avatar_url} showTitles={false} fullAddress metadata={v.identity} action={<button className={`validator-favorite ${favorite ? 'validator-favorite--active' : ''}`} type="button" aria-pressed={favorite} aria-label={`${favorite ? 'Remove' : 'Add'} ${v.moniker} ${favorite ? 'from' : 'to'} favorites`} onClick={toggle}>{favorite ? '★' : '☆'}</button>} /></div>
        {(site || v.contact) && <dl className="cosmos-validator-hero__metadata">{site && <div><dt><MetaIcon type="website" />Website</dt><dd><a href={site} target="_blank" rel="noopener noreferrer">{websiteText(site)} ↗</a></dd></div>}{v.contact && <div><dt><MetaIcon type="contact" />Contact</dt><dd>{emailHref(v.contact) ? <a href={emailHref(v.contact)}>{v.contact}</a> : v.contact}</dd></div>}</dl>}
      </div>
      <div className="cosmos-validator-hero__facts"><Field label="Rank" displayLabel={rankLabel(v.category)} value={<span className={`cosmos-validator-rank cosmos-validator-rank--${validatorRankTone(v.stake_share)}`}>#{v.rank}</span>} /><Field label="Status" value={label(v.bond_status)} /><Field label="Jailed" value={v.jailed ? 'Yes' : 'No'} /><Field label="Commission" value={pct(v.commission.rate)} /></div>
      {v.jailed && <div className="cosmos-validator-jailed"><strong>Jailed</strong><span>Until: {utc(v.jailed_until)}</span>{v.tombstoned != null && <span>Tombstoned: {v.tombstoned ? 'Yes' : 'No'}</span>}</div>}
      <div className="cosmos-validator-hero__metrics"><Metric label="Voting Power" value={formatTokenAmount(v.tokens, asset.exponent, asset.symbol)} /><Metric label="Stake Share" value={`${v.stake_share.toFixed(4)}%`} /><Metric label="≈24h Change" value={<Delta validator={v} asset={asset} />} /><Metric label="Minimum Self Delegation" value={minimumSelfDelegation(v.min_self_delegation, asset)} /></div>
      {v.description && <p className="cosmos-validator-hero__description">{v.description}</p>}
    </header>
    <div className="cosmos-validator-detail__primary">
      <section className="panel cosmos-validator-signing"><div className="panel__heading"><div><h2>Signing &amp; Liveness</h2><span className="panel__meta">Canonical finalized consensus participation</span></div></div><div className="cosmos-validator-signing__recent"><h3>Recent finalized participation</h3><div className="cosmos-validator-signing__stats cosmos-validator-signing__mini-metrics"><Field label="Participation" value={participation == null ? '—' : `${participation.toFixed(2)}%`} /><Field label="Commit" value={counts.commit} /><Field label="Nil" value={counts.nil} /><Field label="Absent" value={counts.absent} /></div>{strip.length ? <div className="cosmos-validator-signing__monitor"><div className="cosmos-validator-signing__strip" aria-label="Recent 50-block canonical signing panel">{strip.map((p, index) => { const pointLabel = signingPointLabel(p); return <span key={p.height} tabIndex="0" data-tooltip={pointLabel.replaceAll(' · ', '\n')} className={`is-${p.status}${index === strip.length - 1 ? ' is-latest' : ''}${p.height === animatedHeight ? ' is-new' : ''}`} aria-label={pointLabel} /> })}</div><div className="cosmos-validator-signing__range"><span>Past #{oldestPoint.height.toLocaleString()}</span><span className={newestPoint.height === animatedHeight ? 'is-new' : ''}>Latest finalized #{newestPoint.height.toLocaleString()}</span></div></div> : <p className="muted">{v.signing_history_state === 'warming' ? 'Loading recent signing history…' : 'Recent participation unavailable for this validator.'}</p>}</div><div className="cosmos-validator-signing__protocol"><div><h3>Protocol slashing window</h3><p>Values come from x/slashing SigningInfo and are separate from the visible 50 blocks.</p></div>{v.liveness ? <div className="cosmos-validator-signing__stats"><Field label="Missed blocks counter" value={<span className={missedCountClass(v.liveness.missed_blocks)}>{v.liveness.missed_blocks.toLocaleString()}</span>} /><Field label="Signed percent" value={`${v.liveness.signed_percent.toFixed(2)}%`} /><Field label="Remaining budget" value={v.liveness.remaining_budget.toLocaleString()} /><Field label="Jail ETA" value={eta(v.liveness.jail_eta_seconds)} /></div> : <span className="muted">Protocol liveness unavailable</span>}</div></section>
      <Panel title="Consensus Identity" className="cosmos-validator-identity-fields"><Address label="Account Address" value={v.account_address} accent networkId={network.id} /><Address label="Operator Address" value={v.operator_address} /><Address label="Consensus Address (ValCons)" value={v.consensus_address} /><Address label="Consensus Public Key" value={v.consensus_pubkey} full /><Address label="Consensus Hex Address" value={v.hex_address} /><Address label="EVM Address" value={v.evm_address} /></Panel>
    </div>
    <div className="cosmos-validator-detail__secondary"><Panel title="Rewards & Commission" className="cosmos-validator-reward-fields"><RewardRows commissionCoins={commissionRewards} rewardCoins={outstandingRewards} assets={registeredAssets} market={market.data} /></Panel><Panel title="Validator Economics"><Field label="Delegator Shares" value={<DelegatorShares value={v.delegator_shares} />} /><Field label="Commission Rate" value={pct(v.commission.rate)} />{v.commission.max_rate != null && <Field label="Max Commission" value={pct(v.commission.max_rate)} />}{v.commission.max_change_rate != null && <Field label="Max Daily Change" value={pct(v.commission.max_change_rate)} />}{v.commission.update_time && <Field label="Commission Updated" value={utc(v.commission.update_time)} />}</Panel></div>
    <div className="cosmos-validator-detail__lower"><Delegators network={network} operatorAddress={v.operator_address} assets={registeredAssets} totalShares={v.delegator_shares} validatorAccountAddress={v.account_address} /><ValidatorActivity network={network} operatorAddress={v.operator_address} assets={registeredAssets} /></div>
  </section>
}

function Metric({ label, value }) { return <article className="card status-card cosmos-validator-summary__card"><span>{label}</span><strong>{value}</strong></article> }
function Field({ label, value, displayLabel = label }) { return <div><dt>{displayLabel}</dt><dd>{value}</dd></div> }
function Panel({ title, children, className = '' }) { return <section className={`panel cosmos-validator-fields ${className}`.trim()}><div className="panel__heading"><h2>{title}</h2></div><dl>{children}</dl></section> }
function Address({ label, value, full = false, accent = false, networkId = null }) { const display = value || '—'; const content = <code>{display}</code>; return <div className="cosmos-validator-address-row"><dt>{label}</dt><dd className={`cosmos-copy-value cosmos-validator-address${full ? ' is-full' : ''}${accent ? ' is-accent' : ''}`}>{value && networkId ? <CosmosAccountLink networkId={networkId} address={value}>{content}</CosmosAccountLink> : content}{value && <CopyButton value={value} label={label.toLowerCase()} showTitle={false} />}</dd></div> }
function Delta({ validator: v, asset }) { if (v.change_24h == null || Number(v.change_24h) === 0) return '—'; const positive = Number(v.change_24h) > 0; return <span className={`validator-delta is-${positive ? 'positive' : 'negative'}`}>{formatSignedTokenAmount(v.change_24h, asset.exponent, asset.symbol)}</span> }
function DelegatorShares({ value }) { if (value == null) return '—'; return <span className="cosmos-validator-shares"><span>{compactShares(String(value))} shares</span><CopyButton value={String(value)} label="delegator shares" showTitle={false} /></span> }
function Delegators({ network, operatorAddress, assets, totalShares, validatorAccountAddress }) {
  const [sort, setSort] = useState('network')
  const [state, setState] = useState({ items: [], nextKey: null, loading: true, loadingMore: false, error: false, expanded: false })
  const requestScope = useRef({ generation: 0, identity: null, controller: null })
  useEffect(() => {
    requestScope.current.controller?.abort()
    const controller = new AbortController()
    const generation = requestScope.current.generation + 1
    const identity = `${network.id}:${operatorAddress}`
    requestScope.current = { generation, identity, controller }
    const isCurrent = () => requestScope.current.generation === generation && requestScope.current.identity === identity && requestScope.current.controller === controller
    setState({ items: [], nextKey: null, loading: true, loadingMore: false, error: false, expanded: false })
    getCosmosValidatorDelegations({ networkId: network.id, operatorAddress, limit: 10, signal: controller.signal })
      .then((data) => { if (isCurrent()) setState({ items: data.items, nextKey: data.next_key ?? null, loading: false, loadingMore: false, error: false, expanded: false }) })
      .catch((error) => { if (error.name !== 'AbortError' && isCurrent()) setState((current) => ({ ...current, loading: false, error: true })) })
    return () => {
      controller.abort()
      requestScope.current.controller?.abort()
      if (requestScope.current.identity === identity) {
        requestScope.current.controller?.abort()
        requestScope.current = { generation: requestScope.current.generation + 1, identity: null, controller: null }
      }
    }
  }, [network.id, operatorAddress])
  const showMore = async () => {
    if (!state.nextKey || state.loadingMore) return
    requestScope.current.controller?.abort()
    const controller = new AbortController()
    const generation = requestScope.current.generation + 1
    const identity = `${network.id}:${operatorAddress}`
    requestScope.current = { generation, identity, controller }
    const isCurrent = () => requestScope.current.generation === generation && requestScope.current.identity === identity && requestScope.current.controller === controller
    setState((current) => ({ ...current, loadingMore: true, error: false }))
    try {
      const data = await getCosmosValidatorDelegations({ networkId: network.id, operatorAddress, limit: 10, paginationKey: state.nextKey, signal: controller.signal })
      if (isCurrent()) setState((current) => ({ ...current, items: [...current.items, ...data.items], nextKey: data.next_key ?? null, loadingMore: false, expanded: true }))
    } catch (error) {
      if (error.name !== 'AbortError' && isCurrent()) setState((current) => ({ ...current, loadingMore: false, error: true }))
    }
  }
  const ordered = useMemo(() => sort === 'delegated' ? [...state.items].sort((a, b) => compareIntegerAmountsDescending(a.balance.amount, b.balance.amount)) : state.items, [sort, state.items])
  const visible = state.expanded ? ordered : ordered.slice(0, 10)
  return <section className="panel cosmos-validator-delegators"><div className="panel__heading"><div><h2>Delegators</h2><span className="panel__meta">Current delegations to this validator</span></div></div>
    {state.loading ? <p className="muted">Loading delegators…</p> : state.error && !state.items.length ? <p className="cosmos-error">Delegator data is temporarily unavailable.</p> : !state.items.length ? <p className="muted">No delegations found.</p> : <><div className="cosmos-validator-delegators__scroll"><table><thead><tr><th>Delegator</th><th aria-sort={sort === 'delegated' ? 'descending' : 'none'}><button type="button" className={`data-table__sort ${sort === 'delegated' ? 'is-active' : ''}`} aria-label={`Delegated: ${sort === 'delegated' ? 'sorted descending. Activate to restore network order.' : 'network order. Activate to sort descending.'}`} onClick={() => setSort((current) => current === 'delegated' ? 'network' : 'delegated')}>Delegated<span className="data-table__sort-arrow" aria-hidden="true">{sort === 'delegated' ? '↓' : '↕'}</span></button></th><th>Share</th></tr></thead><tbody>{visible.map((item) => <tr key={`${item.delegator_address}:${item.validator_address}`}><td><span className={`cosmos-validator-delegator${item.delegator_address === validatorAccountAddress ? ' is-self-delegation' : ''}`}><CosmosAccountLink networkId={network.id} address={item.delegator_address}><code>{item.delegator_address}</code></CosmosAccountLink><CopyButton value={item.delegator_address} label="delegator address" showTitle={false} /></span></td><td className="cosmos-validator-delegated">{formatDelegationBalance(item.balance, assets)}</td><td className="cosmos-validator-delegation-share">{formatDelegationShare(item.shares, totalShares)}</td></tr>)}</tbody></table></div><div className="cosmos-validator-delegators__actions">{state.expanded && state.items.length > 10 && <button className="cosmos-detail-toggle" type="button" onClick={() => setState((current) => ({ ...current, expanded: false }))}>Show less ↑</button>}{state.expanded && state.nextKey && <button className="cosmos-detail-toggle" type="button" disabled={state.loadingMore} onClick={showMore}>{state.loadingMore ? 'Loading delegators…' : 'Show 10 more ↓'}</button>}{!state.expanded && state.items.length > 10 && <button className="cosmos-detail-toggle" type="button" onClick={() => setState((current) => ({ ...current, expanded: true }))}>Show 10 more ↓</button>}{!state.expanded && state.items.length <= 10 && state.nextKey && <button className="cosmos-detail-toggle" type="button" onClick={showMore}>Show 10 more ↓</button>}</div>{state.error && <p className="cosmos-error">Delegator data is temporarily unavailable.</p>}</>}
  </section>
}
function ValidatorActivity({ network, operatorAddress, assets }) {
  const [filter, setFilter] = useState('all')
  const [state, setState] = useState({ status: 'loading', items: [], page: 1, hasMore: false, expanded: false, loadingMore: false })
  const requestScope = useRef({ generation: 0, identity: null, controller: null, loadingMore: false })
  const txLookup = useRef({ generation: 0, identity: null, controller: null })
  useEffect(() => {
    requestScope.current.controller?.abort()
    txLookup.current.controller?.abort()
    const controller = new AbortController()
    const generation = requestScope.current.generation + 1
    const identity = `${network.id}:${operatorAddress}`
    requestScope.current = { generation, identity, controller, loadingMore: false }
    txLookup.current = { generation: txLookup.current.generation + 1, identity, controller: null }
    const isCurrent = () => requestScope.current.generation === generation && requestScope.current.identity === identity && requestScope.current.controller === controller
    setState({ status: 'loading', items: [], page: 1, hasMore: false, expanded: false, loadingMore: false })
    getCosmosValidatorActivity({ networkId: network.id, operatorAddress, signal: controller.signal })
      .then((data) => { if (isCurrent()) setState({ status: data.state, items: data.items, page: 1, hasMore: data.has_more, expanded: false, loadingMore: false }) })
      .catch((error) => { if (error.name !== 'AbortError' && isCurrent()) setState({ status: 'error', items: [], page: 1, hasMore: false, expanded: false, loadingMore: false }) })
    return () => {
      controller.abort()
      txLookup.current.controller?.abort()
      if (requestScope.current.identity === identity) requestScope.current = { generation: requestScope.current.generation + 1, identity: null, controller: null, loadingMore: false }
      if (txLookup.current.identity === identity) txLookup.current = { generation: txLookup.current.generation + 1, identity: null, controller: null }
    }
  }, [network.id, operatorAddress])
  const more = async () => {
    if (!state.hasMore || state.loadingMore || requestScope.current.loadingMore) return
    requestScope.current.controller?.abort()
    const controller = new AbortController()
    const generation = requestScope.current.generation + 1
    const identity = `${network.id}:${operatorAddress}`
    const next = state.page + 1
    requestScope.current = { generation, identity, controller, loadingMore: true }
    const isCurrent = () => requestScope.current.generation === generation && requestScope.current.identity === identity && requestScope.current.controller === controller
    setState((current) => ({ ...current, loadingMore: true }))
    try {
      const data = await getCosmosValidatorActivity({ networkId: network.id, operatorAddress, page: next, signal: controller.signal })
      if (isCurrent()) {
        requestScope.current.loadingMore = false
        setState((current) => ({ ...current, status: data.state, items: mergeActivityItems(current.items, data.items), page: next, hasMore: data.has_more, expanded: true, loadingMore: false }))
      }
    } catch (error) {
      if (isCurrent()) requestScope.current.loadingMore = false
      if (error.name !== 'AbortError' && isCurrent()) setState((current) => ({ ...current, status: 'error', loadingMore: false }))
    }
  }
  const filteredItems = useMemo(() => state.items.filter((item) => filter === 'all' || activityGroups[filter].includes(item.action)), [filter, state.items])
  const rows = state.expanded ? filteredItems : filteredItems.slice(0, 10)
  const openTx = async (event, hash) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    txLookup.current.controller?.abort()
    const controller = new AbortController(), identity = `${network.id}:${operatorAddress}`, generation = txLookup.current.generation + 1
    txLookup.current = { generation, identity, controller }
    try {
      const tx = await getCosmosTransactionByHash({ networkId: network.id, txHash: hash, signal: controller.signal })
      if (txLookup.current.generation === generation && txLookup.current.identity === identity && txLookup.current.controller === controller) navigateInternal(`/networks/${network.id}/blocks/${tx.height}/transactions/${tx.index}`)
    } catch { /* Keep the independent panel usable. */ }
  }
  const hiddenLoadedRows = !state.expanded && filteredItems.length > 10
  return <section className="panel cosmos-validator-activity"><div className="panel__heading"><div><h2>Validator Activity</h2><span className="panel__meta">Recent validator-related transactions{state.status === 'partial' && <ParameterHelp label="validator activity availability">Some validator activity types are unavailable from the current RPC/API.</ParameterHelp>}</span></div></div>{state.status !== 'indexing_unavailable' && <div className="cosmos-validator-activity__filters" aria-label="Filter loaded validator activity">{Object.keys(activityGroups).map((key) => <button key={key} type="button" className={filter === key ? 'is-active' : ''} aria-pressed={filter === key} onClick={() => setFilter(key)}>{key === 'validator' ? 'Validator ops' : label(key)}</button>)}</div>}{state.status === 'indexing_unavailable' ? <p className="muted">Validator activity is unavailable from the current RPC/API.</p> : <>{state.status === 'error' && !state.items.length ? <p className="cosmos-error">Validator activity is temporarily unavailable.</p> : state.status === 'loading' ? <p className="muted">Loading validator activity…</p> : !rows.length ? <p className="muted">No recent validator activity found.</p> : <div className="cosmos-validator-activity__scroll"><table><thead><tr><th>Activity</th><th>Amount / detail</th><th>Height / time</th><th>TX</th></tr></thead><tbody>{rows.map((item) => <tr key={`${item.tx_hash}:${item.message_index}:${item.action}`}><td><strong className={`is-${item.direction}`}>{activityLabel(item.action)}</strong>{item.account_address ? <CosmosAccountLink networkId={network.id} address={item.account_address}><code>{shortValue(item.account_address)}</code></CosmosAccountLink> : <code>—</code>}</td><td className={`is-${item.direction}`}>{item.amounts.length ? item.amounts.map((coin) => <span key={coin.denom}>{item.direction === 'positive' ? '+' : item.direction === 'negative' ? '−' : ''}{formatDelegationBalance(coin, assets)}</span>) : item.detail || '—'}</td><td><a className="accent-value" href={`/networks/${network.id}/blocks/${item.height}`}>#{item.height}</a><time>{utc(item.timestamp)}</time></td><td><a href={`/networks/${network.id}/transactions/${item.tx_hash}`} className="mono cosmos-validator-activity__tx cosmos-tx-tooltip" data-tooltip={item.tx_hash} aria-label={`Open transaction ${item.tx_hash}`} onClick={(event) => openTx(event, item.tx_hash)}>{shortValue(item.tx_hash)}</a></td></tr>)}</tbody></table></div>}<div className="cosmos-validator-delegators__actions">{state.expanded && filteredItems.length > 10 && <button className="cosmos-detail-toggle" type="button" onClick={() => setState((current) => ({ ...current, expanded: false }))}>Show less ↑</button>}{hiddenLoadedRows ? <button className="cosmos-detail-toggle" type="button" onClick={() => setState((current) => ({ ...current, expanded: true }))}>Show 10 more ↓</button> : state.hasMore && <button className="cosmos-detail-toggle" type="button" disabled={state.loadingMore} onClick={more}>{state.loadingMore ? 'Loading activity…' : 'Show 10 more ↓'}</button>}</div></>}</section>
}
const activityGroups = { all: [], staking: ['delegate', 'undelegate', 'redelegate_in', 'redelegate_out'], rewards: ['withdraw_reward', 'withdraw_commission'], validator: ['edit_validator', 'unjail'] }
const activityIdentity = (item) => `${item.tx_hash}:${item.message_index}:${item.action}`
const mergeActivityItems = (current, incoming) => [...new Map([...current, ...incoming].map((item) => [activityIdentity(item), item])).values()].sort((a, b) => compareIntegerAmountsDescending(String(a.height), String(b.height)) || a.tx_hash.localeCompare(b.tx_hash) || a.message_index - b.message_index || a.action.localeCompare(b.action)).slice(0, 50)
const compareIntegerAmountsDescending = (left, right) => { const valid = /^\d+$/; if (!valid.test(left) || !valid.test(right)) return String(right).localeCompare(String(left)); const a = BigInt(left), b = BigInt(right); return a === b ? 0 : a > b ? -1 : 1 }
const shortValue = (value) => !value ? '—' : value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value
const activityLabel = (value) => ({ delegate: 'Delegate', undelegate: 'Undelegate', redelegate_in: 'Redelegate in', redelegate_out: 'Redelegate out', withdraw_reward: 'Withdraw reward', withdraw_commission: 'Withdraw commission', edit_validator: 'Edit validator', unjail: 'Unjail' })[value] || value
function formatDelegationBalance(balance, assets) { const asset = assets.find((item) => item.base === balance.denom); return asset ? formatTokenAmount(balance.amount, asset.exponent, asset.symbol) : `${readableDecimal(balance.amount)} ${balance.denom}` }
function RewardRows({ commissionCoins, rewardCoins, assets, market }) {
  const [expanded, setExpanded] = useState(false)
  const rows = [...(commissionCoins || []).map((coin) => ({ label: 'Validator Commission', coin })), ...(rewardCoins || []).map((coin) => ({ label: 'Rewards', coin }))]
  if (!rows.length) return <><Field label="Validator Commission" value="—" /><Field label="Rewards" value="—" /></>
  const visible = expanded ? rows : rows.slice(0, 4)
  const remaining = Math.max(0, rows.length - 4)
  return <>{visible.map((row, index) => <Field key={`${row.label}:${row.coin.denom}:${index}`} label={row.label} value={<RewardValue coin={row.coin} assets={assets} market={market} />} />)}{remaining > 0 && <div className="cosmos-validator-rewards__more"><dt><span className="sr-only">Additional reward assets</span></dt><dd><button type="button" className="cosmos-validator-rewards__toggle" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Show less ↑' : `Show ${remaining} more ↓`}</button></dd></div>}</>
}
function RewardValue({ coin, assets, market }) { const usd = approximateRewardUsd(coin, assets, market); return <span className="cosmos-validator-reward-value"><span>{formatRewardCoin(coin, assets)}</span>{usd && <span className="cosmos-validator-reward-usd">{usd}</span>}</span> }
function approximateRewardUsd(coin, assets, market) {
  // Network-level CoinGecko pricing follows the primary configured Cosmos asset, matching the Overview market card.
  const marketAsset = assets?.[0]
  const price = Number(market?.price)
  const amount = Number(coin?.amount)
  const exponent = marketAsset?.exponent
  if (!marketAsset || coin?.denom !== marketAsset.base || !Number.isFinite(price) || price <= 0 || !Number.isFinite(amount) || amount < 0 || !Number.isInteger(exponent) || exponent < 0 || exponent > 30) return null
  const usd = amount / (10 ** exponent) * price
  if (!Number.isFinite(usd) || usd <= 0) return null
  if (usd >= 1000) return `$${usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (usd >= 1) return `$${usd.toFixed(2)}`
  const digits = usd >= 0.01 ? 4 : 8
  return `$${usd.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '')}`
}
function formatRewardCoin(coin, assets) { const registered = assets.find((item) => item.base === coin.denom); return registered ? formatTokenAmount(String(coin.amount), registered.exponent, registered.symbol) : `${readableDecimal(coin.amount)} ${coin.denom}` }
function MetaIcon({ type }) { return type === 'website' ? <svg className="cosmos-validator-meta-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a3 3 0 0 0 4.2 0l3-3a3 3 0 0 0-4.2-4.2l-1.1 1.1"/><path d="M14 10a3 3 0 0 0-4.2 0l-3 3A3 3 0 0 0 11 17.2l1.1-1.1"/></svg> : <svg className="cosmos-validator-meta-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/></svg> }
