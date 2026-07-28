import { CopyButton } from '../components/CopyButton'
import { DataTable } from '../components/DataTable'
import { GovernanceTiers, GovernanceVoteSplit } from '../components/GovernancePresentation'
import { StatusBadge } from '../components/StatusBadge'
import { shortAddress } from '../utils/address'
import { governanceAuthorValue, governanceStatusTone } from '../utils/governance'

const proposalHref = (id) => `/governance/${encodeURIComponent(id)}`

const columns = [
  {
    key: 'proposal',
    label: 'Proposal',
    render: (item) => (
      <a className="table-link governance-table__proposal mono accent-value" href={proposalHref(item.proposal_id)} aria-label={`Open proposal #${item.proposal_id}`}>
        #{item.proposal_id}
      </a>
    ),
  },
  {
    key: 'title',
    label: 'Title',
    render: (item) => (
      <a className="table-link governance-table__title" href={proposalHref(item.proposal_id)} title={item.title} aria-label={`Open proposal #${item.proposal_id}: ${item.title || 'Untitled'}`}>
        {item.title || 'Untitled proposal'}
      </a>
    ),
  },
  {
    key: 'author',
    label: 'Author',
    render: (item) => {
      const author = governanceAuthorValue(item)
      return (
        <span className="governance-table__author">
          <span className="mono" title={author}>{shortAddress(author)}</span>
          {author && <CopyButton value={author} label="proposal author" />}
        </span>
      )
    },
  },
  {
    key: 'status',
    label: 'Status',
    render: (item) => <StatusBadge tone={governanceStatusTone(item.status)}>{item.status || 'UNKNOWN'}</StatusBadge>,
  },
  { key: 'tiers', label: 'Eligible Tiers', render: (item) => <GovernanceTiers tiers={item.eligible_tiers} /> },
  { key: 'votes', label: 'Vote Split', render: (item) => <GovernanceVoteSplit proposal={item} /> },
]

export function Governance({ governancePage }) {
  const {
    proposals, source, statusCounts, loading, error, snapshotMissing,
    pageIndex, canLoadOlder, retry, loadOlder, loadNewer,
  } = governancePage
  const emptyMessage = error
    ? 'Governance proposals are currently unavailable.'
    : snapshotMissing
      ? 'Governance snapshot is not available yet.'
      : 'No governance proposals have been saved yet.'
  const metrics = [
    ['Total Proposals', source.proposal_count, 'total'],
    ['Active', statusCounts.active, 'active'],
    ['Accepted', statusCounts.accepted, 'accepted'],
    ['Rejected', statusCounts.rejected, 'rejected'],
  ]

  return (
    <section className="governance-page" aria-labelledby="governance-page-title">
      <header className="blocks-page__header governance-page__header">
        <div>
          <h1 id="governance-page-title">Governance</h1>
          <p>Governance proposals saved by UTSA Explorer.</p>
        </div>
        {error && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </header>

      <div className="governance-page__summary status-grid" aria-label="Governance summary">
        {metrics.map(([label, value, tone]) => (
          <div className={`panel governance-page__metric governance-page__metric--${tone}`} key={label}>
            <span>{label}</span><strong className="mono">{value ?? '—'}</strong>
          </div>
        ))}
      </div>
      {Number(statusCounts.unknown) > 0 && <p className="governance-page__warning">Some proposals have an unknown stored status: {statusCounts.unknown}.</p>}
      <div className="panel governance-page__table">
        <DataTable columns={columns} rows={proposals} rowKey={(item) => item.proposal_id} loading={loading} emptyMessage={emptyMessage} />
      </div>
      <nav className="blocks-pagination" aria-label="Governance proposals pagination">
        <button className="blocks-page__button" type="button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer proposals</button>
        <span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span>
        <button className="blocks-page__button" type="button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older proposals</button>
      </nav>
    </section>
  )
}
