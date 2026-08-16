import { useState } from 'react'
import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { formatGas } from '../utils/gas'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'
import { formatSuccessRate, realmDetailHref } from '../utils/realm'
import { getRealmDetailViewModel, getRealmSourceStatusParts, realmCallsPageLabel, realmCallsPathForDetail } from '../utils/realmDetail'
import { useRealmCalls } from '../hooks/useRealmCalls'
import { useRealmMetadata } from '../hooks/useRealmMetadata'
import { useTokenSupply } from '../hooks/useTokenSupply'
import { formatTokenSupply } from '../utils/tokenSupply'

const formatCount = (value) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : value == null ? '—' : String(value)
const formatBlock = (value) => value == null ? '—' : <a className="accent-value mono" href={`/blocks/${encodeURIComponent(value)}`} aria-label={`Open block ${value}`}>#{formatCount(value)}</a>
const formatAccount = (value) => value ? <a className="accent-value mono" href={`/accounts/${encodeURIComponent(value)}`} aria-label={`Open account ${value}`} title={value}>{shortAddress(value)}</a> : '—'
const shortHash = (value) => value ? `${value.slice(0, 10)}…${value.slice(-8)}` : '—'
const txHref = (row) => row.tx_hash ? `/blocks/${encodeURIComponent(row.block_height)}/transactions/${encodeURIComponent(row.tx_index)}` : null
const field = (label, value) => <div className="realm-detail__field"><dt>{label}</dt><dd>{value}</dd></div>
const formatBytes = (value) => value == null ? '—' : value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`
const statusLabel = (value) => value ? value.replaceAll('_', ' ') : 'Unavailable'
const fileKindLabel = { gno_source: 'Gno source', gno_test: 'Test', gnomod: 'Module', other: 'Other' }

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

function SourceStatus({ source, item }) {
  const parts = getRealmSourceStatusParts(source, item)
  return (
    <p className="realm-detail__source">
      {parts.map((part, index) => (
        <span key={`${part[0]}-${index}`}>{index > 0 ? ' · ' : ''}{part[0]}{part.length > 1 ? <> {formatCount(part[1])}</> : null}{part.length > 3 ? <> {part[2]} {formatCount(part[3])}</> : null}</span>
      ))}
    </p>
  )
}

function Overview({ item, source }) {
  const deployTxPosition = item.deploy_tx_index == null ? '—' : `#${formatCount(item.deploy_tx_index)}`
  const metrics = [
    field('Direct Calls', formatCount(item.call_count)),
    field('Success Rate', formatSuccessRate(item.success_rate)),
    field('Successful Calls', formatCount(item.successful_call_count)),
    field('Failed Calls', formatCount(item.failed_call_count)),
    item.unknown_result_call_count > 0 ? field('Unknown Results', formatCount(item.unknown_result_call_count)) : null,
    field('First Seen block', formatBlock(item.first_seen_height)),
    field('Last Activity', item.last_activity_at ? <time dateTime={item.last_activity_at} title={item.last_activity_at}>{relativeTime(item.last_activity_at)}</time> : '—'),
    field('Last Activity block', formatBlock(item.last_activity_height)),
    field('Deployment block', formatBlock(item.deploy_height)),
    field('Deployment transaction position', deployTxPosition),
    field('Deployer', formatAccount(item.deployer_address)),
    field('Indexed height', formatBlock(source.indexed_height)),
  ].filter(Boolean)
  return <section className="panel realm-detail__section" aria-labelledby="realm-overview-title"><div className="panel__heading"><h2 id="realm-overview-title">Overview</h2></div><dl className="realm-detail__overview">{metrics}</dl></section>
}

function TokenSummary({ supply }) {
  if (!supply.data) return null
  const data = supply.data
  const totalSupply = data.available
    ? `${formatTokenSupply(data.total_supply)} ${data.symbol}`
    : '—'
  return <section className="panel realm-detail__section realm-detail__token" aria-labelledby="realm-token-title">
    <div className="panel__heading"><h2 id="realm-token-title">Token</h2><StatusBadge tone="neutral">GRC20</StatusBadge></div>
    <dl className="realm-detail__overview">
      {field('Total Supply', <span className="mono">{totalSupply}</span>)}
      {field('Decimals', data.decimals)}
    </dl>
  </section>
}

const callColumns = [
  { key: 'time', label: 'Time', render: (row) => row.block_time ? <time dateTime={row.block_time} title={row.block_time}>{relativeTime(row.block_time)}</time> : '—' },
  { key: 'function', label: 'Function', render: (row) => <span><strong>{row.function_name ?? 'Unknown'}</strong><small className="realm-detail__message-label">Message #{formatCount(row.message_index)}</small></span> },
  { key: 'caller', label: 'Caller', render: (row) => formatAccount(row.caller_address) },
  { key: 'block', label: 'Block', render: (row) => formatBlock(row.block_height) },
  { key: 'status', label: 'Status', render: (row) => row.execution_status === 'success' ? <StatusBadge tone="success">Success</StatusBadge> : row.execution_status === 'failed' ? <StatusBadge tone="error">Failed</StatusBadge> : <StatusBadge tone="neutral">Unknown</StatusBadge> },
  { key: 'gas', label: 'Gas Used', render: (row) => <span className="mono">{formatGas(row.gas_used)}</span> },
  { key: 'tx', label: 'Tx Hash', render: (row) => txHref(row) ? <a className="accent-value mono" href={txHref(row)} aria-label={`Open transaction ${row.tx_hash}`} title={row.tx_hash}>{shortHash(row.tx_hash)}</a> : '—' },
]

export function RecentCalls({ response }) {
  const viewModel = getRealmDetailViewModel(response)
  const callsPath = realmCallsPathForDetail(response)
  const calls = useRealmCalls(callsPath)
  if (viewModel.item.kind === 'package') return <section className="panel realm-detail__section realm-detail__note"><h2>Recent Calls</h2><p>Packages do not have direct Realm call history.</p></section>
  if (viewModel.source.call_index_complete !== true || calls.unavailable) return <section className="panel realm-detail__section realm-detail__note"><h2>Recent Calls</h2><p>Realm call history is temporarily unavailable.</p></section>
  return (
    <section className="panel realm-detail__section realm-detail__calls" aria-labelledby="realm-calls-title">
      <div className="panel__heading"><h2 id="realm-calls-title">Recent Calls</h2>{calls.initialError && <button className="blocks-page__button" type="button" onClick={calls.retry} disabled={calls.loading}>Retry</button>}</div>
      <DataTable columns={callColumns} rows={calls.items} rowKey={(row) => `${row.block_height}-${row.tx_index}-${row.message_index}`} loading={calls.loading || calls.pageLoading} emptyMessage={calls.initialError ? 'Realm calls are currently unavailable.' : 'No direct calls have been indexed for this Realm.'} />
      {calls.pageError && <p className="realm-detail__older-error">Realm call page could not be loaded. <button className="blocks-page__button" type="button" onClick={calls.retry} disabled={calls.loading || calls.pageLoading}>Retry</button></p>}
      <nav className="blocks-pagination realm-detail__calls-pagination" aria-label="Realm calls pagination">
        <button className="blocks-page__button" type="button" onClick={calls.loadNewer} disabled={calls.loading || calls.pageLoading || !calls.canLoadNewer}>Newer calls</button>
        <span>{realmCallsPageLabel(calls.pageIndex)}</span>
        <button className="blocks-page__button" type="button" onClick={calls.loadOlder} disabled={calls.loading || calls.pageLoading || !calls.canLoadOlder}>Older calls</button>
      </nav>
    </section>
  )
}

function Metadata({ metadata }) {
  const [sourceExpanded, setSourceExpanded] = useState(false)
  if (metadata.loading) return <section className="panel realm-detail__section realm-detail__note"><h2>Metadata</h2><p>Loading persisted metadata…</p></section>
  if (metadata.notFound) return <section className="panel realm-detail__section realm-detail__note"><h2>Metadata</h2><p>Metadata has not been collected for this path yet.</p></section>
  if (metadata.error || !metadata.data) return <section className="panel realm-detail__section realm-detail__note"><h2>Metadata</h2><p>Metadata is temporarily unavailable.</p></section>
  const data = metadata.data
  const summary = data.summary
  const funcs = summary.qfuncs_status === 'ok' ? summary.qfuncs_summary : null
  const docs = summary.qdoc_status === 'ok' ? summary.qdoc_summary : null
  const storageAvailable = summary.qstorage_status === 'ok'
  const selectedFile = data.files.find((file) => file.filename === metadata.selectedFilename)
  const sourceFile = metadata.source.data || selectedFile
  return (
    <section className="panel realm-detail__section realm-metadata" aria-labelledby="realm-metadata-title">
      <div className="panel__heading"><h2 id="realm-metadata-title">Metadata</h2><StatusBadge tone={data.collection_status === 'complete' ? 'success' : 'neutral'}>{data.collection_status === 'complete' ? 'Complete' : 'Partial'}</StatusBadge></div>
      {data.collection_status === 'partial' && <p className="realm-metadata__partial">Some metadata capabilities were unavailable during collection.</p>}
      <dl className="realm-detail__overview">
        {field('Files', formatCount(summary.file_count))}
        {field('Functions', funcs ? formatCount(funcs.function_count) : 'Unavailable')}
        {field('Dependencies', formatCount(summary.dependency_count))}
        {field('Docs', docs?.available ? 'Available' : statusLabel(summary.qdoc_status))}
        {field('Metadata height', `#${formatCount(data.observed_height)}`)}
        {field('Collected', <time dateTime={data.collected_at} title={data.collected_at}>{relativeTime(data.collected_at)}</time>)}
        {field('Package metadata', statusLabel(summary.qpkg_json_status))}
        {data.kind === 'realm' && field('Storage', storageAvailable && summary.qstorage_bytes != null ? `${summary.qstorage_bytes} bytes` : statusLabel(summary.qstorage_status))}
        {data.kind === 'realm' && field('Deposit', storageAvailable && summary.qstorage_deposit_ugnot != null ? `${summary.qstorage_deposit_ugnot} uGNOT` : statusLabel(summary.qstorage_status))}
        {data.kind === 'realm' && field('Render', summary.qrender_status === 'ok' ? 'Available' : statusLabel(summary.qrender_status))}
      </dl>
      <div className="realm-metadata__grid">
        <div><h3>Dependencies <span>{formatCount(summary.dependency_count)}</span></h3>{summary.dependency_count === 0 ? <p>No dependencies</p> : <ul className="realm-metadata__names">{data.dependencies.map((dependency) => <li key={`${dependency.imported_path}-${dependency.imported_kind}`}><a className="mono" href={realmDetailHref(dependency.imported_path)}>{dependency.imported_path}</a></li>)}</ul>}{data.dependencies_truncated && <p>Showing first 200 dependencies</p>}</div>
        <div><h3>Functions {funcs && <span>{formatCount(funcs.function_count)}</span>}</h3>{funcs ? <><ul className="realm-metadata__names">{funcs.function_names.map((name, index) => <li className="mono" key={`${name}-${index}`}>{name}</li>)}</ul>{funcs.function_count > funcs.function_names.length && <p>Showing {funcs.function_names.length} of {funcs.function_count} functions</p>}</> : <p>Functions unavailable · {statusLabel(summary.qfuncs_status)}</p>}</div>
        <div><h3>Files <span>{formatCount(summary.file_count)}</span></h3><ul className="realm-metadata__files">{data.files.map((file) => <li key={file.filename}><button className={file.filename === metadata.selectedFilename ? 'is-selected' : undefined} type="button" aria-pressed={file.filename === metadata.selectedFilename} onClick={() => metadata.selectFile(file.filename)}><span className="realm-metadata__filename mono">{file.filename}</span><StatusBadge tone="neutral">{fileKindLabel[file.file_kind]}</StatusBadge><small>{formatBytes(file.byte_count)} · {formatCount(file.line_count)} lines</small></button></li>)}</ul></div>
        <div><h3>Docs</h3>{docs ? <dl className="realm-metadata__docs"><dt>Available</dt><dd><StatusBadge tone={docs.available ? 'success' : 'neutral'}>{docs.available ? 'Yes' : 'No'}</StatusBadge></dd><dt>Package doc</dt><dd><StatusBadge tone={docs.package_doc_present ? 'success' : 'neutral'}>{docs.package_doc_present ? 'Yes' : 'No'}</StatusBadge></dd><dt>Documented functions</dt><dd>{docs.documented_function_count}</dd><dt>Values</dt><dd>{docs.value_count}</dd><dt>Types</dt><dd>{docs.type_count}</dd></dl> : <p>Docs unavailable · {statusLabel(summary.qdoc_status)}</p>}</div>
      </div>
      <div className="realm-metadata__source"><div className="realm-metadata__source-header"><h3>Source</h3><button className="blocks-page__button realm-metadata__source-toggle" type="button" aria-expanded={sourceExpanded} onClick={() => setSourceExpanded((expanded) => !expanded)} disabled={!sourceFile}>{sourceExpanded ? 'Hide source ↑' : 'Show source ↓'}</button></div>{sourceFile && <p className="mono">{sourceFile.filename} · {formatBytes(sourceFile.byte_count)} · {formatCount(sourceFile.line_count)} lines</p>}{metadata.source.loading && <p>Loading source…</p>}{metadata.source.error && <p>Source file is temporarily unavailable.</p>}{sourceExpanded && metadata.source.data && <pre><code>{metadata.source.data.content}</code></pre>}</div>
    </section>
  )
}

export function RealmDetail({ path, detailState }) {
  const metadata = useRealmMetadata(path)
  const tokenSupply = useTokenSupply(path)
  if (!path) return <StatePanel title="Invalid Realm or Package path" message="The path query parameter is required and must be a canonical gno.land/r/... or gno.land/p/... path." />
  if (detailState.loading) return <StatePanel title="Loading Realm or Package details…" />
  if (detailState.notFound) return <StatePanel title="Realm or Package not found" message="This path has not been indexed." />
  if (detailState.temporaryError) return <StatePanel title="Realm details are temporarily unavailable" message="The Explorer API could not load this path right now." retry={detailState.retry} />
  if (detailState.error) return <StatePanel title="Realm details are currently unavailable" message="The Explorer API could not load this path." retry={detailState.retry} />
  if (!detailState.data) return <StatePanel title="Loading Realm or Package details…" />

  const response = detailState.data
  const item = response.item
  const source = response.source
  const namespaceKey = response.namespace_key
  const application = response.application
  return (
    <article className="realm-detail" aria-labelledby="realm-detail-title">
      <a className="transaction-detail__back" href="/realms">← Back to Realms</a>
      <header className="realm-detail__header">
        <div className="realm-detail__badges"><StatusBadge tone="neutral">{item.kind === 'package' ? 'Package' : 'Realm'}</StatusBadge><StatusBadge tone={item.rpc_visible ? 'success' : 'neutral'}>{item.rpc_visible ? 'Visible' : 'Historical'}</StatusBadge>{application && <StatusBadge tone="neutral">{application.display_name} · {application.category}</StatusBadge>}</div>
        <h1 id="realm-detail-title" className="mono">{item.path}</h1>
        {item.kind === 'realm' && namespaceKey && <p className="realm-detail__namespace mono">Namespace: {namespaceKey}</p>}
      </header>
      <TokenSummary supply={tokenSupply} />
      <Overview item={item} source={source} />
      <SourceStatus source={source} item={item} />
      <Metadata metadata={metadata} />
      <RecentCalls response={response} />
    </article>
  )
}
