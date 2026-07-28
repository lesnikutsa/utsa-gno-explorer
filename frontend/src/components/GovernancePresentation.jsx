import { formatGovernancePercent, normalizeVoteWidth } from '../utils/governance'

export function GovernanceTiers({ tiers }) {
  return (
    <span className="governance-tiers">
      {Array.isArray(tiers) && tiers.length
        ? tiers.map((tier) => <span className="governance-tier" key={tier}>{tier}</span>)
        : '—'}
    </span>
  )
}

export function GovernanceVoteSplit({ proposal }) {
  const values = [proposal.yes_percent, proposal.no_percent, proposal.abstain_percent]
  if (values.every((value) => formatGovernancePercent(value) === '—')) {
    return <span className="governance-vote-split__unavailable">Vote data unavailable</span>
  }

  return (
    <div className="governance-vote-split">
      <div className="governance-vote-split__text">
        <span>YES {formatGovernancePercent(values[0])}</span>
        <span>NO {formatGovernancePercent(values[1])}</span>
        <span>ABSTAIN {formatGovernancePercent(values[2])}</span>
      </div>
      <div className="governance-vote-bar" aria-hidden="true">
        <i className="governance-vote-bar__yes" style={{ width: `${normalizeVoteWidth(values[0])}%` }} />
        <i className="governance-vote-bar__no" style={{ width: `${normalizeVoteWidth(values[1])}%` }} />
        <i className="governance-vote-bar__abstain" style={{ width: `${normalizeVoteWidth(values[2])}%` }} />
      </div>
    </div>
  )
}
