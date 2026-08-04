import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { formatSuccessRate } from '../utils/realm'
import { relativeTime } from '../utils/time'

const formatCount = (value) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—'
const packageMetricPlaceholder = (label = '—') => <span className="realms-table__package-placeholder" title="Package usage through imports is not indexed yet.">{label}</span>

const columns = [
  {
    key: 'path',
    label: 'Path',
    render: (item) => <span className="realms-table__path mono" title={item.path}>{item.path}</span>,
  },
  {
    key: 'kind',
    label: 'Type',
    render: (item) => item.kind === 'realm'
      ? <span className="realms-table__type realms-table__type--realm"><StatusBadge tone="neutral">Realm</StatusBadge></span>
      : item.kind === 'package'
        ? <span className="realms-table__type realms-table__type--package"><StatusBadge tone="neutral">Package</StatusBadge></span>
        : <StatusBadge tone="neutral">Unknown</StatusBadge>,
  },
  { key: 'call_count', label: 'Direct Calls', render: (item) => item.kind === 'package' ? packageMetricPlaceholder() : formatCount(item.call_count) },
  { key: 'success_rate', label: 'Success Rate', render: (item) => item.kind === 'package' ? packageMetricPlaceholder() : formatSuccessRate(item.success_rate) },
  {
    key: 'last_activity_at',
    label: 'Last Activity',
    render: (item) => item.kind === 'package'
      ? packageMetricPlaceholder('Not tracked')
      : item.last_activity_at
      ? <time dateTime={item.last_activity_at} title={item.last_activity_at}>{relativeTime(item.last_activity_at)}</time>
      : 'Never',
  },
  {
    key: 'rpc_visible',
    label: 'Visibility',
    render: (item) => item.rpc_visible
      ? <span title="Present in the latest Realm catalog RPC snapshot"><StatusBadge tone="success">Visible</StatusBadge></span>
      : <span title="Observed in indexed transactions but absent from the latest Realm catalog RPC snapshot"><StatusBadge tone="neutral">Historical</StatusBadge></span>,
  },
]

function emptyMessage({ error, snapshotMissing, appliedSearch, kind }) {
  if (error) return 'Realms and packages are currently unavailable.'
  if (snapshotMissing) return 'The Realm catalog is not available yet.'
  if (appliedSearch) return <>No realms or packages match “{appliedSearch}”.</>
  if (kind === 'realm') return 'No realms match the current filters.'
  if (kind === 'package') return 'No packages match the current filters.'
  return 'No realms or packages have been indexed yet.'
}

function RealmApplications({ applications }) {
  const { items, source, loading, error, snapshotMissing, retry } = applications
  const activityFromHeight = source?.activity_from_height
  const intro = activityFromHeight !== null && activityFromHeight !== undefined
    ? `Curated Realm namespaces ranked by indexed direct calls since #${formatCount(activityFromHeight)}.`
    : 'Curated Realm namespaces ranked by indexed direct calls.'

  return (
    <section className="realms-applications" aria-labelledby="realms-applications-title">
      <div className="realms-applications__heading">
        <div>
          <h2 id="realms-applications-title">Applications</h2>
          <p className="realms-applications__intro">{intro}</p>
        </div>
        {error && <button className="blocks-page__button" type="button" onClick={retry} disabled={loading}>Retry</button>}
      </div>
      {loading ? (
        <div className="panel realms-applications__state">Loading applications…</div>
      ) : error ? (
        <div className="panel realms-applications__state">Applications are currently unavailable.</div>
      ) : snapshotMissing ? (
        <div className="panel realms-applications__state">Application ranking is not available yet.</div>
      ) : items.length === 0 ? (
        <div className="panel realms-applications__state">No curated applications are available yet.</div>
      ) : (
        <div className="realms-applications__grid">
          {items.map((item) => (
            <article className="panel realms-application-card" key={item.namespace_key}>
              <header className="realms-application-card__header">
                <div className="realms-application-card__identity">
                  <h3>{item.application.display_name}</h3>
                  <p className="realms-application-card__namespace mono">Namespace: {item.namespace_key}</p>
                </div>
                <StatusBadge tone="neutral">{item.application.category}</StatusBadge>
              </header>
              <dl className="realms-application-card__primary">
                <dt>Direct Calls</dt>
                <dd>{formatCount(item.direct_call_count)}</dd>
              </dl>
              <dl className="realms-application-card__metrics">
                <div><dt>Realms</dt><dd>{formatCount(item.realm_count)}</dd></div>
                <div><dt>Called Realms</dt><dd>{formatCount(item.called_realm_count)}</dd></div>
                <div><dt>Success Rate</dt><dd>{formatSuccessRate(item.success_rate)}</dd></div>
                <div><dt>Last Activity</dt><dd>{item.last_activity_at ? <time dateTime={item.last_activity_at} title={item.last_activity_at}>{relativeTime(item.last_activity_at)}</time> : 'Never'}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

export function Realms({ realmsPage, realmApplications }) {
  const { items, summary, loading, error, snapshotMissing, kind, searchInput, appliedSearch, pageIndex, canLoadOlder, setSearchInput, selectKind, submitSearch, clearSearch, retry, loadOlder, loadNewer } = realmsPage
  const metrics = [
    ['Realms', summary?.total_realms],
    ['Packages', summary?.total_packages],
    ['Active 24h', summary?.active_24h],
    ['RPC Visible', summary?.rpc_visible_items],
  ]
  const filters = [
    ['all', 'All', summary?.total_items],
    ['realm', 'Realms', summary?.total_realms],
    ['package', 'Packages', summary?.total_packages],
  ]

  return (
    <section className="blocks-page realms-page" aria-labelledby="realms-page-title">
      <header className="blocks-page__header realms-page__header">
        <h1 id="realms-page-title">Realms &amp; Packages</h1>
        {error && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry} disabled={loading}>Retry</button>}
      </header>

      <div className="status-grid realms-page__summary">
        {metrics.map(([label, value]) => <div className="panel realms-page__metric" key={label}><span>{label}</span><strong>{formatCount(value)}</strong></div>)}
      </div>
      {summary && <p className="realms-page__metadata">Catalog snapshot #{formatCount(summary.catalog_observed_height)} · Indexed #{formatCount(summary.indexed_height)}</p>}

      <RealmApplications applications={realmApplications} />

      <div className="realms-page__toolbar">
        <div className="realms-page__filters" aria-label="Realm kind filters">
          {filters.map(([value, label, count]) => (
            <button className={`realms-page__filter ${kind === value ? 'is-active' : ''}`} type="button" key={value} aria-pressed={kind === value} onClick={() => selectKind(value)}>
              <span>{label}</span> <small>{formatCount(count)}</small>
            </button>
          ))}
        </div>
        <form className="realms-page__search" onSubmit={submitSearch}>
          <label className="sr-only" htmlFor="realm-path-search">Search realm or package path</label>
          <input id="realm-path-search" type="search" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} maxLength={128} placeholder="Search realm or package path" />
          <button className="blocks-page__button blocks-page__button--accent" type="submit" disabled={loading}>Search</button>
          {appliedSearch && <button className="blocks-page__button" type="button" onClick={clearSearch} disabled={loading}>Clear</button>}
        </form>
      </div>

      <p className="realms-page__package-note">Package usage through imports is not indexed yet. Direct-call metrics apply to realms only.</p>

      <div className="panel blocks-page__table realms-page__table">
        <DataTable columns={columns} rows={items} rowKey={(item) => item.path} loading={loading} emptyMessage={emptyMessage({ error, snapshotMissing, appliedSearch, kind })} />
      </div>
      <nav className="blocks-pagination" aria-label="Realms pagination">
        <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer entries</button>
        <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
        <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older entries</button>
      </nav>
    </section>
  )
}
