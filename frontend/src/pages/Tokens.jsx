import { useEffect, useMemo, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ChangedValue } from '../components/ChangedValue'
import { realmDetailHref } from '../utils/realm'
import { formatSuccessRate } from '../utils/realm'
import { relativeTime } from '../utils/time'
import { formatTokenSupply } from '../utils/tokenSupply'
import { networkProfile } from '../config/networkProfile'
import { sortTokenDirectoryItems } from '../utils/tokenDirectory'

const formatCount = (value) => Number.isFinite(value) ? value.toLocaleString() : '—'
const lastActivityChangeValue = (timestamp, label) => `${timestamp ?? 'never'}|${label}`

function LastActivityValue({ timestamp }) {
  const label = timestamp ? relativeTime(timestamp) : 'Never'
  return <ChangedValue value={lastActivityChangeValue(timestamp, label)}>
    {timestamp ? <time dateTime={timestamp} title={timestamp}>{label}</time> : label}
  </ChangedValue>
}
const TOKEN_WINDOW_LABELS = { '24h': '24H', '7d': '7D', '30d': '30D' }
const TOKEN_WINDOW_DESCRIPTIONS = { '24h': 'the last 24 hours', '7d': 'the last 7 days', '30d': 'the last 30 days' }

const grc20Columns = (supplies, suppliesSettled) => [
  { key: 'token', label: 'Token', render: (item) => <a className="tokens-table__token" href={realmDetailHref(item.path)}>
    <span className="tokens-table__identity">{item.identity_verified ? item.name : item.path.split('/').at(-1)}
      {item.identity_verified && item.symbol ? <small>${item.symbol}</small> : null}</span>
    <span className="tokens-table__path mono">{item.path}</span></a> },
  { key: 'application', label: 'App', render: (item) => <span className="tokens-table__app"><strong>{item.application?.display_name ?? item.namespace_key}</strong><small>{item.application?.category ?? 'Namespace'}</small></span> },
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
  { key: 'application', label: 'App', render: (item) => <span className="tokens-table__app"><strong>{item.application?.display_name ?? item.namespace_key}</strong><small>{item.application?.category ?? 'Namespace'}</small></span> },
  { key: 'direct_call_count', label: 'Direct Calls', sortable: true, defaultSortDirection: 'descending', render: (item) => <ChangedValue value={item.direct_call_count}>{formatCount(item.direct_call_count)}</ChangedValue> },
  { key: 'last_activity_at', label: 'Last Activity', sortable: true, defaultSortDirection: 'descending', render: (item) => <LastActivityValue timestamp={item.last_activity_at} /> },
  { key: 'rpc_visible', label: 'Visibility', render: (item) => item.rpc_visible ? <StatusBadge tone="success">Visible</StatusBadge> : <StatusBadge tone="neutral">Historical</StatusBadge> },
]
const nftColumns = commonColumns.filter((column) => column.key !== 'standard').map((column) =>
  column.key === 'asset' ? { ...column, key: 'collection', label: 'Collection' } : column)
nftColumns.splice(2, 0, { key: 'token_count', label: 'NFTs', render: (item) => item.token_count ?? '—' })

export function Tokens({ tokensPage }) {
  const { items, supplies = {}, summary, topActivity, nativeToken, activityWindow, availableActivityWindows,
    selectActivityWindow, searchInput, appliedSearch, loading, error, setSearchInput, submitSearch,
    clearSearch, retry, pageIndex, canLoadOlder, loadOlder, loadNewer, assetFilter, selectAssetFilter } = tokensPage
  const { activityLoading, activityError, retryActivity } = tokensPage
  const [networkIconFailed, setNetworkIconFailed] = useState(false)
  const [sort, setSort] = useState({ key: 'last_activity_at', direction: 'descending' })
  const suppliesSettled = items.filter((item) => item.standard === 'grc20').every((item) => Object.hasOwn(supplies, item.path))
  const supportedSortKeys = assetFilter === 'grc20'
    ? new Set(['total_supply', 'direct_call_count', 'last_activity_at'])
    : new Set(['direct_call_count', 'last_activity_at'])
  const viewSort = supportedSortKeys.has(sort.key) ? sort : { key: 'last_activity_at', direction: 'descending' }
  const effectiveSortKey = viewSort.key === 'total_supply' && !suppliesSettled ? null : viewSort.key
  const sortedItems = useMemo(() => sortTokenDirectoryItems(items, effectiveSortKey, viewSort.direction, supplies),
    [effectiveSortKey, items, supplies, viewSort.direction])
  useEffect(() => {
    if (!supportedSortKeys.has(sort.key)) setSort({ key: 'last_activity_at', direction: 'descending' })
  }, [assetFilter, sort.key])
  const native = nativeToken ?? networkProfile.nativeToken
  const tableColumns = assetFilter === 'grc20' ? grc20Columns(supplies, suppliesSettled) : assetFilter === 'grc721' ? nftColumns : commonColumns
  const empty = error ? 'Assets are currently unavailable.' : appliedSearch ? `No assets match “${appliedSearch}”.` : 'No verified contract assets have been indexed yet.'
  return <section className="blocks-page tokens-page" aria-labelledby="tokens-page-title">
    <header className="blocks-page__header tokens-page__header"><h1 id="tokens-page-title">Tokens</h1>
      {error && <button className="blocks-page__button blocks-page__button--accent" onClick={retry}>Retry</button>}</header>
    <div className="status-grid tokens-page__summary">
      <div className="panel tokens-page__metric"><span>GRC20 Tokens</span><strong><ChangedValue value={summary?.grc20_count}>{formatCount(summary?.grc20_count)}</ChangedValue></strong></div>
      <div className="panel tokens-page__metric"><span>NFT Collections</span><strong><ChangedValue value={summary?.grc721_count}>{formatCount(summary?.grc721_count)}</ChangedValue></strong></div>
    </div>
    <section className="tokens-native" aria-labelledby="tokens-native-title">
      <h2 id="tokens-native-title">Native Token</h2>
      <div className="panel tokens-native__card">
        <header className="tokens-native__header"><div className="tokens-native__identity">
          {networkIconFailed ? <span className="tokens-native__icon-fallback" aria-hidden="true">G</span>
            : <img className="tokens-native__icon" src={networkProfile.networkIconSrc} alt="" onError={() => setNetworkIconFailed(true)} />}
          <div><h3>{native.name}</h3><p>Native currency · {networkProfile.networkName}</p></div>
        </div><StatusBadge tone="neutral">{native.type}</StatusBadge></header>
        <dl className="tokens-native__metrics">
          <div><dt>Total Supply</dt><dd><ChangedValue value={native.available ? native.total_supply : null}>{native.available ? `${formatTokenSupply(native.total_supply)} GNOT` : '—'}</ChangedValue></dd></div>
          <div><dt>Base denom</dt><dd className="mono">{native.base_denom ?? native.baseDenom}</dd></div>
          <div><dt>Decimals</dt><dd>{native.decimals}</dd></div>
          <div><dt>Network</dt><dd>{networkProfile.networkName}</dd></div>
        </dl>
        <p className="tokens-native__conversion">1 GNOT = 1,000,000 ugnot</p>
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
            <header className="tokens-top__card-header"><div className="tokens-top__identity"><h3>{token.name} <small>${token.symbol}</small></h3><p className="mono">{token.path}</p></div><StatusBadge tone="neutral">{token.application?.display_name ?? token.namespace_key} · {token.application?.category ?? 'Namespace'}</StatusBadge></header>
            <dl className="tokens-top__primary"><div><dt>Direct Calls ({TOKEN_WINDOW_LABELS[activityWindow]})</dt><dd><ChangedValue value={token.direct_call_count}>{formatCount(token.direct_call_count)}</ChangedValue></dd></div><div><dt>Success ({TOKEN_WINDOW_LABELS[activityWindow]})</dt><dd><ChangedValue value={token.success_rate}>{formatSuccessRate(token.success_rate)}</ChangedValue></dd></div></dl>
            <dl className="tokens-top__metrics"><div><dt className="sr-only">Last activity</dt><dd>Last activity <ChangedValue value={`${token.last_activity_at}|${relativeTime(token.last_activity_at)}`}><time dateTime={token.last_activity_at} title={token.last_activity_at}>{relativeTime(token.last_activity_at)}</time></ChangedValue></dd></div></dl>
          </a>)}</div>}
    </section>
    <section className="tokens-directory" aria-labelledby="tokens-directory-title"><h2 id="tokens-directory-title">Contract Assets</h2>
    <div className="realms-page__filters" aria-label="Asset standard filters">
      {[['all', 'All', summary?.asset_count], ['grc20', 'GRC20 Tokens', summary?.grc20_count], ['grc721', 'NFTs', summary?.grc721_count]].map(([value, label, count]) => <button
        className={`realms-page__filter ${assetFilter === value ? 'is-active' : ''}`} type="button" key={value}
        aria-pressed={assetFilter === value} onClick={() => selectAssetFilter(value)}>{label}<small>{formatCount(count)}</small></button>)}
    </div>
    <form className="tokens-page__search" onSubmit={submitSearch}>
      <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search asset name, symbol or realm path..." aria-label="Search assets" />
      <button className="blocks-page__button" type="submit">Search</button>
      {appliedSearch && <button className="blocks-page__button" type="button" onClick={clearSearch}>Clear</button>}
    </form>
    <div className="panel blocks-page__table tokens-page__table"><DataTable columns={tableColumns} rows={sortedItems} rowKey={(item) => item.path} loading={loading} emptyMessage={empty}
      sortKey={viewSort.key} sortDirection={viewSort.direction} onSort={(key, direction) => setSort({ key, direction })} /></div>
    <nav className="blocks-pagination" aria-label="Tokens pagination">
      <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer entries</button>
      <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
      <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older entries</button>
    </nav>
    </section>
  </section>
}
