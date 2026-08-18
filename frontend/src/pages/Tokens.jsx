import { useEffect, useMemo, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ChangedValue } from '../components/ChangedValue'
import { realmDetailHref } from '../utils/realm'
import { formatSuccessRate } from '../utils/realm'
import { relativeTime } from '../utils/time'
import { formatNativeSupply, formatTokenSupply } from '../utils/tokenSupply'
import { networkProfile } from '../config/networkProfile'
import { GNOT_TOKENOMICS } from '../config/gnotTokenomics'
import { sortTokenDirectoryItems } from '../utils/tokenDirectory'
import { applicationPresentation } from '../utils/namespaceDisplay'
import { flattenNftCollectionGroups, groupNftCollections, sortNftCollectionGroups } from '../utils/nftCollections'

const formatCount = (value) => Number.isFinite(value) ? value.toLocaleString() : '—'
const lastActivityChangeValue = (timestamp, label) => `${timestamp ?? 'never'}|${label}`
const EMPTY_SET = new Set()

function LastActivityValue({ timestamp }) {
  const label = timestamp ? relativeTime(timestamp) : 'Never'
  return <ChangedValue value={lastActivityChangeValue(timestamp, label)}>
    {timestamp ? <time dateTime={timestamp} title={timestamp}>{label}</time> : label}
  </ChangedValue>
}
const TOKEN_WINDOW_LABELS = { '24h': '24H', '7d': '7D', '30d': '30D' }
const TOKEN_WINDOW_DESCRIPTIONS = { '24h': 'the last 24 hours', '7d': 'the last 7 days', '30d': 'the last 30 days' }

const applicationLabel = (item) => {
  const presentation = applicationPresentation(item)
  return <span className="tokens-table__app"><strong title={presentation.title} aria-label={presentation.title}>{presentation.label}</strong>
    <small>{item.application?.category ?? 'Namespace'}</small></span>
}
const topApplicationBadge = (item) => {
  const presentation = applicationPresentation(item)
  return <StatusBadge tone="neutral" title={presentation.title} aria-label={presentation.title}>
    {presentation.label} · {item.application?.category ?? 'Namespace'}
  </StatusBadge>
}

const grc20Columns = (supplies, suppliesSettled) => [
  { key: 'token', label: 'Token', render: (item) => <a className="tokens-table__token" href={realmDetailHref(item.path)}>
    <span className="tokens-table__identity">{item.identity_verified ? item.name : item.path.split('/').at(-1)}
      {item.identity_verified && item.symbol ? <small>${item.symbol}</small> : null}</span>
    <span className="tokens-table__path mono">{item.path}</span></a> },
  { key: 'application', label: 'App', render: applicationLabel },
  { key: 'decimals', label: 'Decimals', render: (item) => item.decimals ?? '—' },
  { key: 'total_supply', label: 'Total Supply', sortable: true, sortDisabled: !suppliesSettled,
    defaultSortDirection: 'descending', headerTitle: suppliesSettled ? undefined : 'Total Supply sorting is available after visible supplies settle.',
    render: (item) => <span className="tokens-table__supply mono">{supplies[item.path]?.available ? formatTokenSupply(supplies[item.path].total_supply) : '—'}</span> },
  { key: 'direct_call_count', label: 'Direct Calls', sortable: true, defaultSortDirection: 'descending', render: (item) => <ChangedValue value={item.direct_call_count}>{formatCount(item.direct_call_count)}</ChangedValue> },
  { key: 'last_activity_at', label: 'Last Activity', sortable: true, defaultSortDirection: 'descending', render: (item) => <LastActivityValue timestamp={item.last_activity_at} /> },
  { key: 'rpc_visible', label: 'Visibility', render: (item) => item.rpc_visible ? <StatusBadge tone="success">Visible</StatusBadge> : <StatusBadge tone="neutral">Historical</StatusBadge> },
]

const assetIdentity = (item, label = 'tokens-table__token') => <a className={label} href={realmDetailHref(item.path)}>
  <span className="tokens-table__identity">{item.name}<small>${item.symbol}</small></span>
  <span className="tokens-table__path mono">{item.path}</span></a>
const commonColumns = [
  { key: 'asset', label: 'Asset', render: (item) => assetIdentity(item) },
  { key: 'standard', label: 'Standard', render: (item) => <StatusBadge tone="neutral">{item.standard.toUpperCase()}</StatusBadge> },
  { key: 'application', label: 'App', render: applicationLabel },
  { key: 'direct_call_count', label: 'Direct Calls', sortable: true, defaultSortDirection: 'descending', render: (item) => <ChangedValue value={item.direct_call_count}>{formatCount(item.direct_call_count)}</ChangedValue> },
  { key: 'last_activity_at', label: 'Last Activity', sortable: true, defaultSortDirection: 'descending', render: (item) => <LastActivityValue timestamp={item.last_activity_at} /> },
  { key: 'rpc_visible', label: 'Visibility', render: (item) => item.rpc_visible ? <StatusBadge tone="success">Visible</StatusBadge> : <StatusBadge tone="neutral">Historical</StatusBadge> },
]

const childLabel = (path) => path.split('/').at(-1)
const nftVisibility = (item) => {
  const visibility = item.rowType === 'family' ? item.visibility : item.rpc_visible ? 'Visible' : 'Historical'
  return <StatusBadge tone={visibility === 'Visible' ? 'success' : 'neutral'}>{visibility}</StatusBadge>
}

const nftApplication = (item) => item.rowType === 'family' && item.applicationMode === 'multiple'
  ? <span className="tokens-table__app"><strong>Multiple</strong><small>{item.namespaceCount} {item.namespaceCount === 1 ? 'namespace' : 'namespaces'}</small></span>
  : applicationLabel(item.rowType === 'family' ? item.applicationItem : item)

const nftColumns = (expandedGroupKeys, toggleGroup) => [
  { key: 'collection', label: 'Collection', sortable: true, render: (item) => {
    if (item.rowType === 'family') return <div className="nft-family__identity">
      <button className="nft-family__toggle" type="button" aria-expanded={expandedGroupKeys.has(item.groupKey)} onClick={() => toggleGroup(item.groupKey)}>
        <span aria-hidden="true">{expandedGroupKeys.has(item.groupKey) ? '▼' : '▶'}</span>
        <span className="tokens-table__identity">{item.name}<small>${item.symbol}</small></span>
      </button><small>{item.collectionCountLabel}</small></div>
    if (item.rowType === 'family-child') return <a className="tokens-table__token nft-family__child-link" href={realmDetailHref(item.path)}>
      <span className="tokens-table__identity"><span aria-hidden="true">↳</span> {childLabel(item.path)}<small>Realm collection</small></span>
      <span className="tokens-table__path mono">{item.path}</span></a>
    return assetIdentity(item)
  } },
  { key: 'application', label: 'App', render: nftApplication },
  { key: 'direct_call_count', label: 'Direct Calls', sortable: true, defaultSortDirection: 'descending', render: (item) => <ChangedValue value={item.direct_call_count}>{formatCount(item.direct_call_count)}</ChangedValue> },
  { key: 'last_activity_at', label: 'Last Activity', sortable: true, defaultSortDirection: 'descending', render: (item) => <LastActivityValue timestamp={item.last_activity_at} /> },
  { key: 'rpc_visible', label: 'Visibility', render: nftVisibility },
]

export function Tokens({ tokensPage }) {
  const { items, supplies = {}, summary, topActivity, nativeToken, activityWindow, availableActivityWindows,
    selectActivityWindow, searchInput, appliedSearch, loading, error, setSearchInput, submitSearch,
    clearSearch, retry, pageIndex, canLoadOlder, loadOlder, loadNewer, assetFilter, selectAssetFilter } = tokensPage
  const { activityLoading, activityError, retryActivity } = tokensPage
  const [networkIconFailed, setNetworkIconFailed] = useState(false)
  const [sort, setSort] = useState({ key: 'last_activity_at', direction: 'descending' })
  const expansionContext = `${assetFilter}\u0000${appliedSearch}\u0000${pageIndex}`
  const [nftExpansion, setNftExpansion] = useState(() => ({ context: '', keys: new Set() }))
  const expandedNftGroups = nftExpansion.context === expansionContext ? nftExpansion.keys : EMPTY_SET
  const suppliesSettled = items.filter((item) => item.standard === 'grc20').every((item) => Object.hasOwn(supplies, item.path))
  const supportedSortKeys = assetFilter === 'grc20'
    ? new Set(['total_supply', 'direct_call_count', 'last_activity_at'])
    : assetFilter === 'grc721'
      ? new Set(['collection', 'direct_call_count', 'last_activity_at'])
      : new Set(['direct_call_count', 'last_activity_at'])
  const viewSort = supportedSortKeys.has(sort.key) ? sort : { key: 'last_activity_at', direction: 'descending' }
  const effectiveSortKey = viewSort.key === 'total_supply' && !suppliesSettled ? null : viewSort.key
  const sortedItems = useMemo(() => sortTokenDirectoryItems(items, effectiveSortKey, viewSort.direction, supplies),
    [effectiveSortKey, items, supplies, viewSort.direction])
  const nftGroups = useMemo(() => groupNftCollections(items, { pageIndex, canLoadOlder }), [items, pageIndex, canLoadOlder])
  const nftRows = useMemo(() => flattenNftCollectionGroups(
    sortNftCollectionGroups(nftGroups, viewSort.key, viewSort.direction), expandedNftGroups,
  ), [expandedNftGroups, nftGroups, viewSort.direction, viewSort.key])
  const toggleNftGroup = (groupKey) => setNftExpansion((current) => {
    const next = new Set(current.context === expansionContext ? current.keys : [])
    if (next.has(groupKey)) next.delete(groupKey)
    else next.add(groupKey)
    return { context: expansionContext, keys: next }
  })
  useEffect(() => {
    if (!supportedSortKeys.has(sort.key)) setSort({ key: 'last_activity_at', direction: 'descending' })
  }, [assetFilter, sort.key])
  useEffect(() => {
    setNftExpansion((current) => current.context === expansionContext
      ? current
      : { context: expansionContext, keys: new Set() })
  }, [expansionContext])
  useEffect(() => {
    const available = new Set(nftGroups.filter((group) => group.rowType === 'family').map((group) => group.groupKey))
    setNftExpansion((current) => {
      if (current.context !== expansionContext) return current
      const next = new Set([...current.keys].filter((key) => available.has(key)))
      return next.size === current.keys.size ? current : { ...current, keys: next }
    })
  }, [expansionContext, nftGroups])
  const native = nativeToken ?? networkProfile.nativeToken
  const nativeBaseDenom = native.base_denom ?? native.baseDenom
  const nativeSupply = formatNativeSupply(native.total_supply)
  const donutRadius = 42
  const donutCircumference = 2 * Math.PI * donutRadius
  let donutOffset = 0
  const tableColumns = assetFilter === 'grc20' ? grc20Columns(supplies, suppliesSettled) : assetFilter === 'grc721' ? nftColumns(expandedNftGroups, toggleNftGroup) : commonColumns
  const tableRows = assetFilter === 'grc721' ? nftRows : sortedItems
  const empty = error ? 'Assets are currently unavailable.' : appliedSearch ? `No assets match “${appliedSearch}”.` : 'No verified contract assets have been indexed yet.'
  return <section className="blocks-page tokens-page" aria-labelledby="tokens-page-title">
    <h1 className="sr-only" id="tokens-page-title">Tokens</h1>
    {error && <button className="blocks-page__button blocks-page__button--accent" onClick={retry}>Retry</button>}
    <section className="tokens-native" aria-labelledby="tokens-native-title">
      <h2 id="tokens-native-title">Native Token</h2>
      <div className="panel tokens-native__card">
        <header className="tokens-native__header"><div className="tokens-native__identity">
          {networkIconFailed ? <span className="tokens-native__icon-fallback" aria-hidden="true">G</span>
            : <img className="tokens-native__icon" src={networkProfile.networkIconSrc} alt="" onError={() => setNetworkIconFailed(true)} />}
          <div><h3>{native.name}</h3><p>Native currency · {networkProfile.networkName}</p></div>
        </div><StatusBadge tone="neutral">{native.type}</StatusBadge></header>
        <div className="tokens-native__content">
          <section className="tokens-native__live" aria-labelledby="tokens-native-live-title">
            <div className="tokens-native__section-heading"><h4 id="tokens-native-live-title">Live {networkProfile.networkName}</h4><span>Live RPC</span></div>
            <dl className="tokens-native__supply"><div><dt>On-chain Supply</dt><dd title={native.available ? `Exact on-chain value: ${nativeSupply.exact} GNOT` : undefined}><ChangedValue value={native.available ? native.total_supply : null}>{native.available ? `${nativeSupply.display} GNOT` : '—'}</ChangedValue></dd></div></dl>
            <p className="tokens-native__provenance">{networkProfile.networkName} bank supply · Live RPC<br /><span className="mono">bank/supply/{nativeBaseDenom}</span></p>
            <p className="tokens-native__semantic">Network state — not circulating supply or Mainnet allocation.</p>
            {native.available && <details className="tokens-native__exact"><summary>Exact value</summary><span>Exact on-chain value<br /><strong className="mono">{nativeSupply.exact} GNOT</strong></span></details>}
            <dl className="tokens-native__metrics">
              <div><dt>Base denom</dt><dd className="mono">{nativeBaseDenom}</dd></div>
              <div><dt>Decimals</dt><dd>{native.decimals}</dd></div>
              <div><dt>Network</dt><dd>{networkProfile.networkName}</dd></div>
            </dl>
            <p className="tokens-native__conversion">1 GNOT = 1,000,000 {nativeBaseDenom}</p>
          </section>
          <section className="tokens-native__tokenomics" aria-labelledby="tokens-native-tokenomics-title">
            <div className="tokens-native__tokenomics-heading"><h4 id="tokens-native-tokenomics-title">Mainnet Token Distribution</h4><p>Official allocation · {GNOT_TOKENOMICS.totalDisplay}</p></div>
            <div className="tokens-native__distribution">
              <svg className="tokens-native__donut" viewBox="0 0 100 100" role="img" aria-label={`Mainnet GNOT token distribution, total ${GNOT_TOKENOMICS.accessibleTotal}`}>
                <circle className="tokens-native__donut-track" cx="50" cy="50" r={donutRadius} />
                {GNOT_TOKENOMICS.allocations.map((allocation) => {
                  const length = allocation.amount / GNOT_TOKENOMICS.total * donutCircumference
                  const segment = <circle key={allocation.label} className="tokens-native__donut-segment" cx="50" cy="50" r={donutRadius} stroke={allocation.color} strokeDasharray={`${length} ${donutCircumference - length}`} strokeDashoffset={-donutOffset} />
                  donutOffset += length
                  return segment
                })}
                <text x="50" y="48">1.333B</text><text className="tokens-native__donut-unit" x="50" y="58">GNOT</text>
              </svg>
              <ul className="tokens-native__legend">{GNOT_TOKENOMICS.allocations.map((allocation) => <li key={allocation.label}><span className="tokens-native__legend-dot" style={{ backgroundColor: allocation.color }} aria-hidden="true" /><span>{allocation.label}</span><strong>{allocation.percentage}</strong></li>)}</ul>
            </div>
            <div className="tokens-native__tokenomics-footer"><p><span>Circulating at TGE</span><strong>{GNOT_TOKENOMICS.circulatingAtTge.display} · {GNOT_TOKENOMICS.circulatingAtTge.percentage}</strong></p><a href={GNOT_TOKENOMICS.sourceUrl} target="_blank" rel="noreferrer">Official tokenomics ↗</a></div>
          </section>
        </div>
      </div>
    </section>
    <section className="tokens-top" aria-labelledby="tokens-top-title">
      <div className="realms-applications__heading tokens-top__heading"><div><h2 id="tokens-top-title">Top Tokens</h2><p className="realms-applications__intro">Verified GRC20 tokens ranked by direct calls in {TOKEN_WINDOW_DESCRIPTIONS[activityWindow]}.</p></div>
        <div className="realms-applications__windows" aria-label="Token activity window">{Object.entries(TOKEN_WINDOW_LABELS).map(([value, label]) => <button
          className={activityWindow === value ? 'is-active' : ''} type="button" key={value}
          aria-pressed={activityWindow === value} disabled={activityLoading || !availableActivityWindows.includes(value)}
          onClick={() => selectActivityWindow(value)}>{label}</button>)}</div></div>
      {activityLoading ? <div className="panel tokens-top__state">Loading token activity…</div>
        : activityError ? <div className="panel tokens-top__state">Token activity is currently unavailable.<button className="blocks-page__button" type="button" onClick={retryActivity}>Retry</button></div>
        : topActivity === null ? <div className="panel tokens-top__state">Complete token activity is not available for this period.</div>
        : topActivity.length === 0 ? <div className="panel tokens-top__state">No verified token calls in {TOKEN_WINDOW_DESCRIPTIONS[activityWindow]}.</div>
          : <div className="tokens-top__grid">{topActivity.slice(0, 3).map((token) => <a className="panel tokens-top__card" href={realmDetailHref(token.path)} key={token.path}>
            <header className="tokens-top__card-header"><div className="tokens-top__identity"><h3>{token.name} <small>${token.symbol}</small></h3><p className="mono">{token.path}</p></div>{topApplicationBadge(token)}</header>
            <dl className="tokens-top__primary"><div><dt>Direct Calls ({TOKEN_WINDOW_LABELS[activityWindow]})</dt><dd><ChangedValue value={token.direct_call_count}>{formatCount(token.direct_call_count)}</ChangedValue></dd></div><div><dt>Success ({TOKEN_WINDOW_LABELS[activityWindow]})</dt><dd><ChangedValue value={token.success_rate}>{formatSuccessRate(token.success_rate)}</ChangedValue></dd></div></dl>
            <dl className="tokens-top__metrics"><div><dt className="sr-only">Last activity</dt><dd>Last activity <ChangedValue value={`${token.last_activity_at}|${relativeTime(token.last_activity_at)}`}><time dateTime={token.last_activity_at} title={token.last_activity_at}>{relativeTime(token.last_activity_at)}</time></ChangedValue></dd></div></dl>
          </a>)}</div>}
    </section>
    <section className="tokens-directory" aria-labelledby="tokens-directory-title"><h2 id="tokens-directory-title">Contract Assets</h2>
    <div className="realms-page__filters" aria-label="Asset standard filters">
      {[['all', 'All', summary?.asset_count], ['grc20', 'GRC20 Tokens', summary?.grc20_count], ['grc721', 'NFT Collections · GRC721', summary?.grc721_count]].map(([value, label, count]) => <button
        className={`realms-page__filter ${assetFilter === value ? 'is-active' : ''}`} type="button" key={value}
        aria-pressed={assetFilter === value} onClick={() => selectAssetFilter(value)}>{label}<small>{formatCount(count)}</small></button>)}
    </div>
    <form className="tokens-page__search" onSubmit={submitSearch}>
      <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search asset name, symbol or realm path..." aria-label="Search assets" />
      <button className="blocks-page__button" type="submit">Search</button>
      {appliedSearch && <button className="blocks-page__button" type="button" onClick={clearSearch}>Clear</button>}
    </form>
    <div className="panel blocks-page__table tokens-page__table"><DataTable columns={tableColumns} rows={tableRows} rowKey={(item) => item.rowType === 'family' ? `family:${item.groupKey}` : item.rowType === 'family-child' ? `child:${item.parentGroupKey}:${item.path}` : item.path} rowClassName={(item) => item.rowType === 'family-child' ? 'nft-family__child-row' : item.rowType === 'family' ? 'nft-family__parent-row' : ''} loading={loading} emptyMessage={empty}
      sortKey={viewSort.key} sortDirection={viewSort.direction} onSort={(key, direction) => setSort({ key, direction })} /></div>
    <nav className="blocks-pagination" aria-label="Tokens pagination">
      <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer entries</button>
      <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
      <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older entries</button>
    </nav>
    </section>
  </section>
}
