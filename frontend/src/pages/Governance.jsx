import { CopyButton } from '../components/CopyButton'
import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { shortAddress } from '../utils/address'
import { relativeTime } from '../utils/time'
import { formatGovernancePercent, governanceAuthorValue, governanceStatusTone, normalizeVoteWidth } from '../utils/governance'

const proposalHref = (id) => `/governance/${encodeURIComponent(id)}`
export function GovernanceTiers({ tiers }) { return <span className="governance-tiers">{Array.isArray(tiers) && tiers.length ? tiers.map((tier) => <span className="governance-tier" key={tier}>{tier}</span>) : '—'}</span> }
export function VoteSplit({ proposal }) {
  const values = [proposal.yes_percent, proposal.no_percent, proposal.abstain_percent]
  if (values.every((value) => formatGovernancePercent(value) === '—')) return <span className="governance-vote-split__unavailable">Vote data unavailable</span>
  return <div className="governance-vote-split"><div className="governance-vote-split__text"><span>YES {formatGovernancePercent(values[0])}</span><span>NO {formatGovernancePercent(values[1])}</span><span>ABSTAIN {formatGovernancePercent(values[2])}</span></div><div className="governance-vote-bar" aria-hidden="true"><i className="governance-vote-bar__yes" style={{ width: `${normalizeVoteWidth(values[0])}%` }} /><i className="governance-vote-bar__no" style={{ width: `${normalizeVoteWidth(values[1])}%` }} /><i className="governance-vote-bar__abstain" style={{ width: `${normalizeVoteWidth(values[2])}%` }} /></div></div>
}
const columns = [
  { key: 'proposal', label: 'Proposal', render: (item) => <a className="table-link governance-table__proposal mono accent-value" href={proposalHref(item.proposal_id)} aria-label={`Open proposal #${item.proposal_id}`}>#{item.proposal_id}</a> },
  { key: 'title', label: 'Title', render: (item) => <a className="table-link governance-table__title" href={proposalHref(item.proposal_id)} title={item.title} aria-label={`Open proposal #${item.proposal_id}: ${item.title || 'Untitled'}`}>{item.title || 'Untitled proposal'}</a> },
  { key: 'author', label: 'Author', render: (item) => { const author = governanceAuthorValue(item); return <span className="governance-table__author"><span className="mono" title={author}>{shortAddress(author)}</span>{author && <CopyButton value={author} label="proposal author" />}</span> } },
  { key: 'status', label: 'Status', render: (item) => <StatusBadge tone={governanceStatusTone(item.status)}>{item.status || 'UNKNOWN'}</StatusBadge> },
  { key: 'tiers', label: 'Eligible Tiers', render: (item) => <GovernanceTiers tiers={item.eligible_tiers} /> },
  { key: 'votes', label: 'Vote Split', render: (item) => <VoteSplit proposal={item} /> },
]
export function Governance({ governancePage }) {
  const { proposals, source, statusCounts, loading, error, snapshotMissing, pageIndex, canLoadOlder, retry, loadOlder, loadNewer } = governancePage
  const emptyMessage = error ? 'Governance proposals are currently unavailable.' : snapshotMissing ? 'Governance snapshot is not available yet.' : 'No governance proposals have been saved yet.'
  return <section className="governance-page" aria-labelledby="governance-page-title">
    <header className="blocks-page__header governance-page__header"><div><h1 id="governance-page-title">Governance</h1><p>Governance proposals saved by UTSA Explorer.</p>{source.chain_id && <p className="governance-page__context">{source.chain_id} · {source.realm_path} · Snapshot at block <a href={`/blocks/${source.source_height}`} className="accent-value">#{Number(source.source_height).toLocaleString()}</a> · Saved <time dateTime={source.last_success_at} title={source.last_success_at}>{relativeTime(source.last_success_at)}</time></p>}</div>{error && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}</header>
    <div className="governance-page__summary status-grid" aria-label="Governance summary">{[['Total Proposals', source.proposal_count, 'total'], ['Active', statusCounts.active, 'active'], ['Accepted', statusCounts.accepted, 'accepted'], ['Rejected', statusCounts.rejected, 'rejected']].map(([label, value, tone]) => <div className={`panel governance-page__metric governance-page__metric--${tone}`} key={label}><span>{label}</span><strong className="mono">{value ?? '—'}</strong></div>)}</div>
    {Number(statusCounts.unknown) > 0 && <p className="governance-page__warning">Some proposals have an unknown stored status: {statusCounts.unknown}.</p>}
    <div className="panel governance-page__table"><DataTable columns={columns} rows={proposals} rowKey={(item) => item.proposal_id} loading={loading} emptyMessage={emptyMessage} /></div>
    <nav className="blocks-pagination" aria-label="Governance proposals pagination"><button className="blocks-page__button" onClick={loadNewer} disabled={loading || pageIndex === 0}>Newer proposals</button><span>{pageIndex === 0 ? 'Latest' : `Page ${pageIndex + 1}`}</span><button className="blocks-page__button" onClick={loadOlder} disabled={loading || !canLoadOlder}>Older proposals</button></nav>
  </section>
}
