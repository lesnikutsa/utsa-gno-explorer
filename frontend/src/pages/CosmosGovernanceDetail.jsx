import { useEffect, useMemo, useState } from 'react'
import { CopyButton } from '../components/CopyButton'
import { useCosmosResource } from '../hooks/useCosmosResource'
import { formatTokenAmount } from '../utils/cosmosFormat'
import { countdownParts } from '../utils/futureBlock'
import '../styles/cosmos-governance.css'
import '../styles/cosmos-governance-detail.css'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const CHOICES = [
  ['yes', 'YES', 'is-yes'],
  ['no', 'NO', 'is-no'],
  ['no_with_veto', 'VETO', 'is-veto'],
  ['abstain', 'ABSTAIN', 'is-abstain'],
]

const label = (value) => value ? value[0].toUpperCase() + value.slice(1).replaceAll('_', ' ') : 'Unknown'

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
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  const day = String(parsed.getUTCDate()).padStart(2, '0')
  const month = MONTHS[parsed.getUTCMonth()]
  const year = parsed.getUTCFullYear()
  const hours = String(parsed.getUTCHours()).padStart(2, '0')
  const minutes = String(parsed.getUTCMinutes()).padStart(2, '0')
  const seconds = String(parsed.getUTCSeconds()).padStart(2, '0')
  return `${day} ${month} ${year} · ${hours}:${minutes}:${seconds} UTC`
}

const tallyPercentages = (tally) => {
  let values
  try {
    values = CHOICES.map(([name]) => BigInt(tally?.[name] || '0'))
  } catch {
    values = CHOICES.map(() => 0n)
  }
  const total = values.reduce((sum, value) => sum + value, 0n)
  if (total === 0n) return null
  const percentages = Object.fromEntries(CHOICES.map(([name], index) => {
    const hundredths = values[index] * 10000n / total
    return [name, Number(hundredths) / 100]
  }))
  return { total, values, percentages }
}

const compactInteger = (value) => {
  let number
  try { number = BigInt(value || '0') } catch { return '—' }
  const text = number.toString()
  return text.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

const weightLabel = (weight) => {
  const number = Number(weight)
  if (!Number.isFinite(number)) return weight
  const percent = number * 100
  return `${percent.toFixed(percent === Math.trunc(percent) ? 0 : 2)}%`
}

function VoteHero({ tally }) {
  const result = useMemo(() => tallyPercentages(tally), [tally])
  return <section className="panel cosmos-governance-detail__vote-panel">
    <div className="panel__heading"><h2>Vote Results</h2></div>
    {!result ? <p className="muted cosmos-governance-detail__empty-tally">No tally is available for this proposal yet.</p> : <>
      <div className="cosmos-governance-detail__vote-metrics">
        {CHOICES.map(([key, text, tone], index) => <article className={`cosmos-governance-detail__vote-metric ${tone}`} key={key}>
          <span>{text}</span>
          <strong>{result.percentages[key].toFixed(2)}%</strong>
          <small>{compactInteger(result.values[index])}</small>
        </article>)}
      </div>
      <div className="cosmos-governance-detail__vote-bar" aria-label="Proposal vote split">
        {CHOICES.map(([key, , tone]) => <i className={tone} key={key} style={{ width: `${result.percentages[key]}%` }} />)}
      </div>
    </>}
  </section>
}

function ProposalCountdown({ proposal }) {
  const target = proposal.status === 'voting'
    ? proposal.voting_end_time
    : proposal.status === 'deposit' ? proposal.deposit_end_time : null
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!target) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [target])

  if (!target) return null
  const targetTime = Date.parse(target)
  if (!Number.isFinite(targetTime) || targetTime <= now) return null
  const countdown = countdownParts(target, now)
  if (!countdown) return null

  const heading = proposal.status === 'voting' ? 'Voting ends in' : 'Deposit period ends in'
  return <section className="panel cosmos-governance-detail__deadline">
    <div className="cosmos-future-countdown" aria-label={heading}>
      <p>{heading}</p>
      <div className="cosmos-future-countdown__grid">
        {[['Days', countdown.days], ['Hours', countdown.hours], ['Minutes', countdown.minutes], ['Seconds', countdown.seconds]].map(([unit, value]) => <div key={unit}>
          <strong>{unit === 'Days' ? value.toLocaleString('en-US') : String(value).padStart(2, '0')}</strong>
          <span>{unit}</span>
        </div>)}
      </div>
    </div>
    <p className="cosmos-governance-detail__deadline-time">{heading.replace(' in', '')}: <strong>{dateValue(target)}</strong></p>
  </section>
}

function ProposalField({ label: fieldLabel, children, wide = false }) {
  return <div className={`cosmos-governance-detail__field${wide ? ' is-wide' : ''}`}><dt>{fieldLabel}</dt><dd>{children}</dd></div>
}

function formatDeposit(coin, network) {
  const asset = network.assets?.find((item) => item.base === coin.denom)
  return asset ? formatTokenAmount(coin.amount, asset.exponent, asset.symbol) : `${compactInteger(coin.amount)} ${coin.denom}`
}

function VoteOptions({ options }) {
  return <div className="cosmos-governance-detail__vote-options">{(options || []).map((choice, index) => {
    const tone = CHOICES.find(([key]) => key === choice.option)?.[2] || 'is-unknown'
    const text = CHOICES.find(([key]) => key === choice.option)?.[1] || label(choice.option)
    return <span className={`cosmos-governance-detail__vote-choice ${tone}`} key={`${choice.option}-${index}`}>{text} <small>{weightLabel(choice.weight)}</small></span>
  })}</div>
}

function VotersList({ network, proposalId, proposalStatus }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/governance/${proposalId}/votes`, 0)
  if (!resource.data && resource.loading) return <div className="cosmos-governance-detail__voters-state">Loading voters…</div>
  if (!resource.data) return <div className="cosmos-governance-detail__voters-state cosmos-error">Voter list is temporarily unavailable.</div>
  const votes = resource.data.votes || []
  const emptyMessage = proposalStatus === 'deposit'
    ? 'Voting has not started yet.'
    : proposalStatus === 'voting'
      ? 'No votes have been returned yet.'
      : 'No live voter records are exposed for this completed proposal.'
  return <div className="cosmos-governance-detail__voters-content">
    <div className="cosmos-governance-detail__voters-heading"><span>Voters</span><strong>{resource.data.total}</strong></div>
    <div className="table-scroll cosmos-governance-detail__voters-table"><table className="data-table"><thead><tr><th>Voter</th><th>Vote</th></tr></thead><tbody>
      {votes.length ? votes.map((vote) => <tr key={vote.voter}>
        <td><span className="cosmos-governance-detail__voter"><a href={`/networks/${network.id}/accounts/${encodeURIComponent(vote.voter)}`}>{vote.voter}</a><CopyButton value={vote.voter} label="voter address" showTitle={false} /></span></td>
        <td><VoteOptions options={vote.options} /></td>
      </tr>) : <tr><td colSpan="2" className="cosmos-governance-detail__voters-empty">{emptyMessage}</td></tr>}
    </tbody></table></div>
  </div>
}

const descriptionBlocks = (value) => {
  const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let paragraph = []
  const flush = () => {
    if (!paragraph.length) return
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }
  for (const line of lines) {
    const text = line.trim()
    if (!text) {
      flush()
      continue
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(text)
    if (heading) {
      flush()
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] })
      continue
    }
    paragraph.push(text)
  }
  flush()
  return blocks
}

const renderInlineLinks = (text, prefix) => {
  const parts = []
  const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<]+)/g
  let cursor = 0
  let match
  let index = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index))
    const href = match[2] || match[3]
    const visible = match[1] || href
    parts.push(<a href={href} key={`${prefix}-${index}`} target="_blank" rel="noreferrer">{visible}</a>)
    cursor = match.index + match[0].length
    index += 1
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}

function ProposalDescription({ value }) {
  const blocks = descriptionBlocks(value)
  if (!blocks.length) return <p>No summary provided.</p>
  return blocks.map((block, index) => {
    if (block.kind === 'heading') {
      const Heading = block.level === 1 ? 'h3' : 'h4'
      return <Heading key={`heading-${index}`}>{renderInlineLinks(block.text, `heading-${index}`)}</Heading>
    }
    return <p key={`paragraph-${index}`}>{renderInlineLinks(block.text, `paragraph-${index}`)}</p>
  })
}

function TechnicalDetails({ messages, metadata }) {
  const [open, setOpen] = useState(false)
  return <section className="panel cosmos-governance-detail__technical">
    <button className="cosmos-governance-detail__toggle" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? '▼' : '▶'} Technical details</button>
    {open && <div className="cosmos-governance-detail__technical-body">
      {metadata && <div><h3>Metadata</h3><pre>{metadata}</pre></div>}
      {(messages || []).map((message, index) => <div key={`${message.message_type || 'message'}-${index}`}><h3>{message.message_type || `Message ${index + 1}`}</h3><pre>{message.content}</pre></div>)}
      {!metadata && !(messages || []).length && <p className="muted">No technical payload is exposed for this proposal.</p>}
    </div>}
  </section>
}

export function CosmosGovernanceDetail({ network, proposalId }) {
  const resource = useCosmosResource(`/api/networks/${network.id}/governance/${proposalId}`, 15000)
  const [showVoters, setShowVoters] = useState(false)
  const data = resource.data

  if (!data && resource.loading) return <section className="cosmos-governance-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/governance`}>← Back to Governance</a><p>Loading proposal…</p></section>
  if (!data) return <section className="cosmos-governance-detail"><a className="cosmos-back block-detail__back" href={`/networks/${network.id}/governance`}>← Back to Governance</a><p className="cosmos-error">Governance proposal is temporarily unavailable.</p></section>

  const proposal = data.proposal
  return <section className="cosmos-governance-detail">
    <a className="cosmos-back block-detail__back" href={`/networks/${network.id}/governance`}>← Back to Governance</a>

    <header className="cosmos-governance-detail__hero">
      <div className="cosmos-governance-detail__hero-title"><span>Proposal #{proposal.proposal_id}</span><h1>{proposal.title}</h1></div>
      <div className="cosmos-governance-detail__hero-badges"><span className={`cosmos-gov-type cosmos-gov-type--${typeTone(proposal.proposal_type)}`}>{proposal.proposal_type}</span><span className={`cosmos-gov-status cosmos-gov-status--${statusTone(proposal.status)}`}>{label(proposal.status)}</span></div>
    </header>

    <VoteHero tally={proposal.tally} />
    <ProposalCountdown proposal={proposal} />

    <section className="panel cosmos-governance-detail__details">
      <div className="panel__heading"><h2>Proposal Details</h2></div>
      <dl className="cosmos-governance-detail__details-grid">
        <ProposalField label="Proposal ID"><span className="cosmos-governance__proposal-id">{proposal.proposal_id}</span></ProposalField>
        <ProposalField label="Status"><span className={`cosmos-gov-status cosmos-gov-status--${statusTone(proposal.status)}`}>{label(proposal.status)}</span></ProposalField>
        <ProposalField label="Type"><span className={`cosmos-gov-type cosmos-gov-type--${typeTone(proposal.proposal_type)}`}>{proposal.proposal_type}</span></ProposalField>
        <ProposalField label="Total Deposit">{data.total_deposit?.length ? data.total_deposit.map((coin) => <span className="cosmos-governance-detail__deposit" key={coin.denom}>{formatDeposit(coin, network)}</span>) : '—'}</ProposalField>
        <ProposalField label="Proposer" wide>{proposal.proposer ? <span className="cosmos-governance-detail__copy-row"><a href={`/networks/${network.id}/accounts/${encodeURIComponent(proposal.proposer)}`}>{proposal.proposer}</a><CopyButton value={proposal.proposer} label="proposal proposer" showTitle={false} /></span> : '—'}</ProposalField>
        <ProposalField label="Submitted">{dateValue(proposal.submit_time)}</ProposalField>
        <ProposalField label="Deposit End">{dateValue(proposal.deposit_end_time)}</ProposalField>
        <ProposalField label="Voting Start">{dateValue(proposal.voting_start_time)}</ProposalField>
        <ProposalField label="Voting End">{dateValue(proposal.voting_end_time)}</ProposalField>
        <ProposalField label="Message Type" wide><code>{proposal.message_type || '—'}</code></ProposalField>
      </dl>
    </section>

    <section className="panel cosmos-governance-detail__description">
      <div className="panel__heading"><h2>Description</h2></div>
      <div className="cosmos-governance-detail__description-body"><ProposalDescription value={data.summary} /></div>
    </section>

    <section className="panel cosmos-governance-detail__voters">
      <button className="cosmos-governance-detail__toggle cosmos-governance-detail__voters-toggle" type="button" aria-expanded={showVoters} onClick={() => setShowVoters((value) => !value)}>{showVoters ? '▼' : '▶'} Voters</button>
      {showVoters && <VotersList network={network} proposalId={proposal.proposal_id} proposalStatus={proposal.status} />}
    </section>

    <TechnicalDetails messages={data.messages} metadata={data.metadata} />
  </section>
}
