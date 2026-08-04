import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { formatGas } from '../utils/gas'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'
import { decodeRealmDetailPath, formatSuccessRate } from '../utils/realm'
import { useRealmDetail } from '../hooks/useRealmDetail'
import { useRealmCalls } from '../hooks/useRealmCalls'

const formatCount = (value) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : value == null ? '—' : String(value)
const formatBlock = (value) => value == null ? '—' : <a className="accent-value mono" href={`/blocks/${encodeURIComponent(value)}`} aria-label={`Open block ${value}`}>#{formatCount(value)}</a>
const formatAccount = (value) => value ? <a className="accent-value mono" href={`/accounts/${encodeURIComponent(value)}`} aria-label={`Open account ${value}`} title={value}>{shortAddress(value)}</a> : '—'
const shortHash = (value) => value ? `${value.slice(0, 10)}…${value.slice(-8)}` : '—'
const txHref = (row) => row.tx_hash ? `/blocks/${encodeURIComponent(row.block_height)}/transactions/${encodeURIComponent(row.tx_index)}` : null
const field = (label, value) => <div className="realm-detail__field"><dt>{label}</dt><dd>{value}</dd></div>

function StatePanel({ title, message, retry }) {
  return (
    <section className="panel realm-detail__state">
      <h1>{title}</h1>
      {message && <p>{message}</p>}
      <div className="realm-detail__actions">
        <a className="transaction-detail__back" href="/realms">← Back to Realms</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

function SourceStatus({ detail }) {
  const source = detail.source ?? detail.summary ?? detail
  const coverageFrom = source.call_history_from_height ?? source.activity_from_height
  const coverageThrough = source.call_history_through_height ?? source.activity_through_height
  return (
    <p className="realm-detail__source">
      Catalog observed at block {formatCount(source.catalog_observed_height)} · Indexed at block {formatCount(source.indexed_height)} · Call history coverage from {formatCount(coverageFrom)} through {formatCount(coverageThrough)} · {detail.call_index_complete === false ? 'History unavailable' : 'History complete'}
    </p>
  )
}

function Overview({ detail }) {
  const deployTxPosition = detail.deployment_tx_index == null ? '—' : `#${formatCount(detail.deployment_tx_index)}`
  const metrics = [
    field('Direct Calls', formatCount(detail.direct_call_count ?? detail.call_count)),
    field('Success Rate', formatSuccessRate(detail.success_rate)),
    field('Successful Calls', formatCount(detail.successful_call_count)),
    field('Failed Calls', formatCount(detail.failed_call_count)),
    (detail.unknown_result_count ?? 0) > 0 ? field('Unknown Results', formatCount(detail.unknown_result_count)) : null,
    field('First Seen block', formatBlock(detail.first_seen_height)),
    field('Last Activity', detail.last_activity_at ? <time dateTime={detail.last_activity_at} title={detail.last_activity_at}>{relativeTime(detail.last_activity_at)}</time> : '—'),
    field('Last Activity block', formatBlock(detail.last_activity_height)),
    field('Deployment block', formatBlock(detail.deployment_height)),
    field('Deployment transaction position', deployTxPosition),
    field('Deployer', formatAccount(detail.deployer)),
    field('Indexed height', formatBlock(detail.indexed_height ?? detail.source?.indexed_height)),
  ].filter(Boolean)
  return <section className="panel realm-detail__section" aria-labelledby="realm-overview-title"><div className="panel__heading"><h2 id="realm-overview-title">Overview</h2></div><dl className="realm-detail__overview">{metrics}</dl></section>
}

const callColumns = [
  { key: 'time', label: 'Time', render: (row) => row.block_time ? <time dateTime={row.block_time} title={row.block_time}>{relativeTime(row.block_time)}</time> : '—' },
  { key: 'function', label: 'Function', render: (row) => <span><strong>{row.function_name ?? 'Unknown'}</strong><small className="realm-detail__message-label">Message #{formatCount(row.message_index)}</small></span> },
  { key: 'caller', label: 'Caller', render: (row) => formatAccount(row.caller) },
  { key: 'block', label: 'Block', render: (row) => formatBlock(row.block_height) },
  { key: 'status', label: 'Status', render: (row) => row.execution_status === 'success' ? <StatusBadge tone="success">Success</StatusBadge> : row.execution_status === 'failed' ? <StatusBadge tone="error">Failed</StatusBadge> : <StatusBadge tone="neutral">Unknown</StatusBadge> },
  { key: 'gas', label: 'Gas Used', render: (row) => <span className="mono">{formatGas(row.gas_used)}</span> },
  { key: 'tx', label: 'Tx Hash', render: (row) => txHref(row) ? <a className="accent-value mono" href={txHref(row)} aria-label={`Open transaction ${row.tx_hash}`} title={row.tx_hash}>{shortHash(row.tx_hash)}</a> : '—' },
]

function RecentCalls({ detail }) {
  const isPackage = detail.kind === 'package'
  const shouldLoadCalls = detail.kind === 'realm' && detail.call_index_complete !== false
  const calls = useRealmCalls(shouldLoadCalls ? detail.path : null)
  if (isPackage) return <section className="panel realm-detail__section realm-detail__note"><h2>Recent Calls</h2><p>Packages do not have direct Realm call history.</p></section>
  if (detail.call_index_complete === false || calls.unavailable) return <section className="panel realm-detail__section realm-detail__note"><h2>Recent Calls</h2><p>Realm call history is temporarily unavailable.</p></section>
  return (
    <section className="panel realm-detail__section realm-detail__calls" aria-labelledby="realm-calls-title">
      <div className="panel__heading"><h2 id="realm-calls-title">Recent Calls</h2>{calls.error && <button className="blocks-page__button" type="button" onClick={calls.retry} disabled={calls.loading}>Retry</button>}</div>
      <DataTable columns={callColumns} rows={calls.items} rowKey={(row) => `${row.block_height}-${row.tx_index}-${row.message_index}`} loading={calls.loading} emptyMessage={calls.error ? 'Realm calls are currently unavailable.' : 'No direct calls have been indexed for this Realm.'} />
      {calls.olderError && <p className="realm-detail__older-error">Older calls could not be loaded. Already loaded calls were preserved.</p>}
      {calls.canLoadOlder && <div className="realm-detail__load-older"><button className="blocks-page__button" type="button" onClick={calls.loadOlder} disabled={calls.loadingOlder}>{calls.loadingOlder ? 'Loading older calls…' : 'Load older calls'}</button></div>}
    </section>
  )
}

export function RealmDetail() {
  const path = decodeRealmDetailPath()
  const detailState = useRealmDetail(path)
  if (!path) return <StatePanel title="Invalid Realm or Package path" message="The path query parameter is required and must be a canonical gno.land/r/... or gno.land/p/... path." />
  if (detailState.loading) return <StatePanel title="Loading Realm or Package details…" />
  if (detailState.notFound) return <StatePanel title="Realm or Package not found" message="This path has not been indexed." />
  if (detailState.temporaryError) return <StatePanel title="Realm details are temporarily unavailable" message="The Explorer API could not load this path right now." retry={detailState.retry} />
  if (detailState.error) return <StatePanel title="Realm details are currently unavailable" message="The Explorer API could not load this path." retry={detailState.retry} />
  const detail = detailState.data
  return (
    <article className="realm-detail" aria-labelledby="realm-detail-title">
      <a className="transaction-detail__back" href="/realms">← Back to Realms</a>
      <header className="realm-detail__header">
        <div className="realm-detail__badges"><StatusBadge tone="neutral">{detail.kind === 'package' ? 'Package' : 'Realm'}</StatusBadge><StatusBadge tone={detail.rpc_visible ? 'success' : 'neutral'}>{detail.rpc_visible ? 'Visible' : 'Historical'}</StatusBadge>{detail.application && <StatusBadge tone="neutral">{detail.application.display_name} · {detail.application.category}</StatusBadge>}</div>
        <h1 id="realm-detail-title" className="mono">{detail.path}</h1>
        {detail.kind === 'realm' && detail.namespace_key && <p className="realm-detail__namespace mono">Namespace: {detail.namespace_key}</p>}
      </header>
      <Overview detail={detail} />
      <SourceStatus detail={detail} />
      <RecentCalls detail={detail} />
    </article>
  )
}
