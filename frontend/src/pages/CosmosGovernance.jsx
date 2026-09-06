import { useMemo, useState } from 'react'
import { useCosmosResource } from '../hooks/useCosmosResource'
import '../styles/cosmos-governance.css'

const TABS = ['all', 'voting', 'deposit', 'passed', 'rejected', 'failed']
const label = (value) => value === 'all' ? 'All' : value[0].toUpperCase() + value.slice(1)

const typeTone = (value) => {
  const text = String(value || '').toLowerCase()
  if (text.includes('upgrade')) return 'upgrade'
  if (text.includes('constitution')) return 'constitution'
  if (text.includes('param')) return 'params'
  if (text.includes('community')) return 'community'
  if (text.includes('legacy')) return 'legacy'
  return 'other'
}

const statusTone = (status) => {
  if (status === 'passed') return 'passed'
  if (status === 'voting') return 'voting'
  if (status === 'deposit') return 'deposit'
  if (status === 'rejected') return 'rejected'
  if (status === 'failed') return 'failed'
  return 'unknown'
}

const dateValue = (value) => {
  if (!value) return { date: '—', time: null }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return { date: '—', time: null }
  return {
    date: parsed.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }),
    time: parsed.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }),
  }
}

const tallyPercentages = (tally) => {
  const names = ['yes', 'no', 'no_with_veto', 'abstain']
  let values
  try {
    values = names.map((name) => BigInt(tally?.[name] || '0'))
  } catch {
    values = names.map(() => 0n)
  }
  const total = values.reduce((sum, value) => sum + value, 0n)
  if (total === 0n) return null
  return Object.fromEntries(names.map((name, index) => {
    const basisPoints = values[index] * 10000n / total
    return [name, Number(basisPoints) / 100]
  }))
}

function VoteSplit({ tally }) {
  const split = tallyPercentages(tally)
  if (!split) return <span className="muted">No tally</span>
  return <div className="cosmos-governance-votes">
    <div className="cosmos-governance-votes__labels">
      <span className="is-yes">YES {split.yes.toFixed(1)}%</span>
      <span className="is-no">NO {split.no.toFixed(1)}%</span>
      <span className="is-veto">VETO {split.no_with_veto.toFixed(1)}%</span>
      <span className="is-abstain">ABSTAIN {split.abstain.toFixed(1)}%</span>
    </div>
    <div className="cosmos-governance-votes__bar" aria-label={`Yes ${split.yes.toFixed(1)}%, no ${split.no.toFixed(1)}%, veto ${split.no_with_veto.toFixed(1)}%, abstain ${split.abstain.toFixed(1)}%`}>
      <i className="is-yes" style={{ width: `${split.yes}%` }} />
      <i className="is-no" style={{ width: `${split.no}%` }} />
      <i className="is-veto" style={{ width: `${split.no_with_veto}%` }} />
      <i className="is-abstain" style={{ width: `${split.abstain}%` }} />
    </div>
  </div>
}

export function CosmosGovernance({ network }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/governance`, 30000)
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')
  const data = resource.data

  const counts = useMemo(() => ({
    all: data?.summary?.total || 0,
    voting: data?.summary?.voting || 0,
    deposit: data?.summary?.deposit || 0,
    passed: data?.summary?.passed || 0,
    rejected: data?.summary?.rejected || 0,
    failed: data?.summary?.failed || 0,
  }), [data])

  const proposals = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (data?.proposals || []).filter((proposal) => {
      if (tab !== 'all' && proposal.status !== tab) return false
      if (!needle) return true
      return `${proposal.proposal_id} ${proposal.title} ${proposal.proposal_type} ${proposal.message_type || ''}`.toLowerCase().includes(needle)
    })
  }, [data, tab, query])

  if (!data && resource.loading) return <section className="cosmos-governance"><p>Loading governance…</p></section>
  if (!data) return <section className="cosmos-governance"><p className="cosmos-error">Governance data is temporarily unavailable.</p></section>

  const active = data.summary.voting + data.summary.deposit
  const rejectedFailed = data.summary.rejected + data.summary.failed

  return <section className="cosmos-governance">
    <header className="cosmos-validators__heading"><h1>Governance</h1></header>

    <div className="cosmos-validator-summary cosmos-governance__summary">
      <article className="card status-card cosmos-validator-summary__card"><span>Total proposals</span><strong>{data.summary.total}</strong></article>
      <article className="card status-card cosmos-validator-summary__card"><span>Active</span><strong>{active}</strong></article>
      <article className="card status-card cosmos-validator-summary__card"><span>Passed</span><strong>{data.summary.passed}</strong></article>
      <article className="card status-card cosmos-validator-summary__card"><span>Rejected / failed</span><strong>{rejectedFailed}</strong></article>
    </div>

    <div className="cosmos-validator-toolbar cosmos-governance__toolbar">
      <div className="cosmos-validator-tabs cosmos-governance__tabs" role="tablist">
        {TABS.map((kind) => <button key={kind} role="tab" aria-selected={tab === kind} className={tab === kind ? 'is-active' : ''} onClick={() => setTab(kind)}>{label(kind)} <b>{counts[kind]}</b></button>)}
      </div>
      <div className="cosmos-validator-search"><input type="search" aria-label="Search governance proposals" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search proposal id, title or type" />{query && <button className="cosmos-validator-search__clear" type="button" onClick={() => setQuery('')} aria-label="Clear governance search">×</button>}</div>
    </div>

    <div className="table-scroll cosmos-governance__table"><table className="data-table"><thead><tr><th>Proposal</th><th>Title</th><th>Type</th><th>Status</th><th>Voting end</th><th>Vote split</th></tr></thead><tbody>
      {proposals.length ? proposals.map((proposal) => {
        const end = dateValue(proposal.voting_end_time)
        return <tr key={proposal.proposal_id}>
          <td><span className="accent-value mono cosmos-governance__proposal-id">#{proposal.proposal_id}</span></td>
          <td><strong className="cosmos-governance__title">{proposal.title}</strong></td>
          <td><span className={`cosmos-gov-type cosmos-gov-type--${typeTone(proposal.proposal_type)}`}>{proposal.proposal_type}</span></td>
          <td><span className={`cosmos-gov-status cosmos-gov-status--${statusTone(proposal.status)}`}>{label(proposal.status)}</span></td>
          <td><span className="cosmos-governance__date">{end.date}</span>{end.time && <small>{end.time}</small>}</td>
          <td><VoteSplit tally={proposal.tally} /></td>
        </tr>
      }) : <tr><td colSpan="6">No proposals match this filter.</td></tr>}
    </tbody></table></div>
  </section>
}
