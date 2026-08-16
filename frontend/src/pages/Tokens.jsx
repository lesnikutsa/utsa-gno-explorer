import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { realmDetailHref } from '../utils/realm'
import { relativeTime } from '../utils/time'

const formatCount = (value) => Number.isFinite(value) ? value.toLocaleString() : '—'

const columns = [
  { key: 'token', label: 'Token', render: (item) => <a className="tokens-table__token" href={realmDetailHref(item.path)}>
    <span className="tokens-table__identity">{item.identity_verified ? item.name : item.path.split('/').at(-1)}
      {item.identity_verified && item.symbol ? <small>${item.symbol}</small> : null}</span>
    <span className="tokens-table__path mono">{item.path}</span></a> },
  { key: 'application', label: 'App', render: (item) => <span className="tokens-table__app"><strong>{item.application?.display_name ?? item.namespace_key}</strong><small>{item.application?.category ?? 'Namespace'}</small></span> },
  { key: 'decimals', label: 'Decimals', render: (item) => item.decimals ?? '—' },
  { key: 'direct_call_count', label: 'Direct Calls', render: (item) => formatCount(item.direct_call_count) },
  { key: 'last_activity_at', label: 'Last Activity', render: (item) => item.last_activity_at ? <time dateTime={item.last_activity_at} title={item.last_activity_at}>{relativeTime(item.last_activity_at)}</time> : 'Never' },
  { key: 'rpc_visible', label: 'Visibility', render: (item) => item.rpc_visible ? <StatusBadge tone="success">Visible</StatusBadge> : <StatusBadge tone="neutral">Historical</StatusBadge> },
]

export function Tokens({ tokensPage }) {
  const { items, summary, searchInput, appliedSearch, loading, error, setSearchInput, submitSearch, clearSearch, retry, pageIndex, canLoadOlder, loadOlder, loadNewer } = tokensPage
  const empty = error ? 'Tokens are currently unavailable.' : appliedSearch ? `No tokens match “${appliedSearch}”.` : 'No confirmed GRC20 tokens have been indexed yet.'
  return <section className="blocks-page tokens-page" aria-labelledby="tokens-page-title">
    <header className="blocks-page__header tokens-page__header"><h1 id="tokens-page-title">Tokens</h1>
      {error && <button className="blocks-page__button blocks-page__button--accent" onClick={retry}>Retry</button>}</header>
    <div className="status-grid tokens-page__summary">
      <div className="panel tokens-page__metric"><span>GRC20 Tokens</span><strong>{formatCount(summary?.token_count)}</strong></div>
      <div className="panel tokens-page__metric"><span>Active 24H</span><strong>{formatCount(summary?.active_24h_count)}</strong></div>
    </div>
    <form className="tokens-page__search" onSubmit={submitSearch}>
      <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search token name, symbol or realm path..." aria-label="Search tokens" />
      <button className="blocks-page__button" type="submit">Search</button>
      {appliedSearch && <button className="blocks-page__button" type="button" onClick={clearSearch}>Clear</button>}
    </form>
    <div className="panel blocks-page__table tokens-page__table"><DataTable columns={columns} rows={items} rowKey={(item) => item.path} loading={loading} emptyMessage={empty} /></div>
    <nav className="blocks-pagination" aria-label="Tokens pagination">
      <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer entries</button>
      <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
      <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older entries</button>
    </nav>
  </section>
}
