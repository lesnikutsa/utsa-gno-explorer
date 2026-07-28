import { CopyButton } from '../components/CopyButton'
import { DataTable } from '../components/DataTable'
import { GovernanceTiers, GovernanceVoteSplit } from '../components/GovernancePresentation'
import { StatusBadge } from '../components/StatusBadge'
import { shortAddress } from '../utils/address'
import { formatGovernancePercent, governanceAuthorValue, governanceStatusTone, governanceVoteTone } from '../utils/governance'

const present = (value) => value !== null && value !== undefined && value !== ''

function StatePanel({ title, retry }) {
  return (
    <section className="panel governance-detail__state">
      <h1>{title}</h1>
      <div className="governance-detail__state-actions">
        <a className="governance-detail__back" href="/governance">← Back to Governance</a>
        {retry && <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={retry}>Retry</button>}
      </div>
    </section>
  )
}

function Field({ label, children, className = '' }) {
  return (
    <div className={`governance-detail__field ${className}`}>
      <span className="governance-detail__label">{label}</span>
      <div className="governance-detail__value">{children}</div>
    </div>
  )
}

const voteColumns = [
  {
    key: 'voter',
    label: 'Voter',
    render: (vote) => {
      const value = vote.voter_address || vote.voter_display || ''
      return (
        <span className="governance-table__author">
          <span className="mono" title={value}>{shortAddress(value)}</span>
          {value && <CopyButton value={value} label="voter address" />}
        </span>
      )
    },
  },
  { key: 'tier', label: 'Tier', render: (vote) => <GovernanceTiers tiers={vote.tier ? [vote.tier] : []} /> },
  { key: 'option', label: 'Option', render: (vote) => <StatusBadge tone={governanceVoteTone(vote.option)}>{vote.option || 'UNKNOWN'}</StatusBadge> },
  { key: 'voting_power', label: 'Voting Power', render: (vote) => <span className="mono">{vote.voting_power ?? '—'}</span> },
]

const voteRowKey = (vote) => `${vote.voter_address || vote.voter_display || 'unknown'}:${vote.tier || ''}`

export function GovernanceDetail({ governanceDetail }) {
  const { proposal, loading, invalidProposalId, notFound, snapshotMissing, error, retry } = governanceDetail

  if (loading) return <StatePanel title="Loading proposal…" />
  if (invalidProposalId) return <StatePanel title="Invalid proposal ID" />
  if (notFound) return <StatePanel title="Governance proposal not found" />
  if (snapshotMissing) return <StatePanel title="Governance snapshot is not available yet" retry={retry} />
  if (error || !proposal) return <StatePanel title="Governance proposal is currently unavailable" retry={error ? retry : null} />

  const author = governanceAuthorValue(proposal)
  const optionalFields = [
    ['Executor', proposal.executor_text],
    ['Executor Creation Realm', proposal.executor_creation_realm],
    ['Rejection Reason', proposal.rejection_reason],
  ].filter(([, value]) => present(value))
  const metrics = [
    ['YES', proposal.yes_percent, 'yes'],
    ['NO', proposal.no_percent, 'no'],
    ['ABSTAIN', proposal.abstain_percent, 'abstain'],
    ['Voters', proposal.voter_count ?? '—', 'voters'],
  ]

  return (
    <article className="governance-detail" aria-labelledby="governance-detail-title">
      <a className="governance-detail__back" href="/governance">← Back to Governance</a>
      <header className="governance-detail__header">
        <div><h1 id="governance-detail-title">Proposal #{proposal.proposal_id}</h1><p>{proposal.title || 'Untitled proposal'}</p></div>
        <StatusBadge tone={governanceStatusTone(proposal.status)}>{proposal.status || 'UNKNOWN'}</StatusBadge>
      </header>

      <section className="panel governance-detail__section" aria-labelledby="proposal-details-title">
        <div className="panel__heading"><h2 id="proposal-details-title">Proposal Details</h2></div>
        <div className="governance-detail__grid">
          <Field label="Proposal ID"><span className="mono accent-value">#{proposal.proposal_id}</span></Field>
          <Field label="Status"><StatusBadge tone={governanceStatusTone(proposal.status)}>{proposal.status || 'UNKNOWN'}</StatusBadge></Field>
          <Field label="Author"><span className="governance-detail__copy-row"><span className="mono">{author || '—'}</span>{author && <CopyButton value={author} label="proposal author" />}</span></Field>
          <Field label="Eligible Tiers"><GovernanceTiers tiers={proposal.eligible_tiers} /></Field>
          <Field label="Description" className="governance-detail__description">{proposal.description || 'No description provided.'}</Field>
          {optionalFields.map(([label, value]) => <Field label={label} key={label}>{value}</Field>)}
        </div>
      </section>

      <section className="panel governance-detail__section" aria-labelledby="vote-results-title">
        <div className="panel__heading"><h2 id="vote-results-title">Vote Results</h2></div>
        <div className="governance-detail__metrics">
          {metrics.map(([label, value, tone]) => <div className={`governance-detail__metric governance-detail__metric--${tone}`} key={label}><span>{label}</span><strong className="mono">{label === 'Voters' ? value : formatGovernancePercent(value)}</strong></div>)}
        </div>
        <div className="governance-detail__vote-strip"><GovernanceVoteSplit proposal={proposal} /></div>
      </section>

      <section className="panel governance-detail__section governance-detail__votes" aria-labelledby="votes-title">
        <div className="panel__heading"><h2 id="votes-title">Votes</h2></div>
        <DataTable columns={voteColumns} rows={Array.isArray(proposal.votes) ? proposal.votes : []} rowKey={voteRowKey} emptyMessage="No votes stored for this proposal." />
      </section>
    </article>
  )
}
