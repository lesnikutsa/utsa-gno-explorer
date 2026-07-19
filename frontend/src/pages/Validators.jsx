import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { shortAddress } from '../utils/address'
import {
  formatIntegerString,
  getMissedBlocks,
  getValidatorHealth,
  getValidatorMissedBreakdown,
} from '../utils/validatorHealth'

const formatPercent = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : '—'
}

const missedSeverity = (missed) => missed >= 10 ? 'high' : missed >= 2 ? 'medium' : 'low'
const formatHeight = (height) => height === null ? '—' : `#${height.toLocaleString()}`

const healthBadge = (uptime) => {
  const health = getValidatorHealth(uptime)
  return <span title={getValidatorMissedBreakdown(uptime)}><StatusBadge tone={health.tone}>{health.label}</StatusBadge></span>
}

const columns = [
  { key: 'rank', label: 'Rank', render: (row) => <span className="mono">#{row.rank}</span> },
  { key: 'address', label: 'Signing Address', render: (row) => <span className="mono" title={row.address}>{shortAddress(row.address)}</span> },
  { key: 'voting_power', label: 'Voting Power', render: (row) => <span className="mono">{formatIntegerString(row.voting_power)}</span> },
  { key: 'percent', label: 'Voting Power %', render: (row) => <span className="mono">{formatPercent(row.percent)}</span> },
  { key: 'uptime_20', label: 'Uptime (20)', render: (row) => <span className="mono">{formatPercent(row.uptime_20?.uptime_percent)}</span> },
  { key: 'uptime_100', label: 'Uptime (100)', render: (row) => <span className="mono">{formatPercent(row.uptime_100?.uptime_percent)}</span> },
  { key: 'missed_100', label: 'Missed (100)', render: (row) => {
    const missed = getMissedBlocks(row.uptime_100)
    return <strong className={`missed-value missed-value--${missedSeverity(missed)}`} title={getValidatorMissedBreakdown(row.uptime_100)}>{missed}</strong>
  } },
  { key: 'health_100', label: 'Health (100)', render: (row) => healthBadge(row.uptime_100) },
  { key: 'proposer_priority', label: 'Proposer Priority', render: (row) => <span className="mono">{formatIntegerString(row.proposer_priority)}</span> },
]

const legend = [
  { label: 'Healthy', tone: 'success', detail: 'less than 10% missed' },
  { label: 'Degraded', tone: 'warning', detail: '10–49% missed' },
  { label: 'Critical', tone: 'error', detail: '50–99% missed' },
  { label: 'No signatures', tone: 'error', detail: 'all active blocks missed' },
  { label: 'Unknown / No data', tone: 'neutral', detail: 'incomplete or unavailable signing history' },
]

export function Validators({ validatorsPage }) {
  const { response, validators, loading, backgroundRefreshing, manualRefreshing, error, hasSuccessfulResponse, refresh } = validatorsPage
  const rows = validators.map((validator, index) => ({ ...validator, rank: index + 1 }))
  const emptyMessage = error && !hasSuccessfulResponse ? 'Validators are currently unavailable.' : 'No active validators returned.'

  return (
    <section className="validators-page" aria-labelledby="validators-page-title">
      <header className="validators-page__header">
        <div>
          <h1 id="validators-page-title">Validators</h1>
          <p>Active validator set indexed by UTSA Explorer.</p>
        </div>
        <button className="blocks-page__button blocks-page__button--accent" type="button" onClick={refresh} disabled={loading || backgroundRefreshing || manualRefreshing}>
          {manualRefreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      <p className="validators-page__notice">All validators shown are members of the current active set. Health reflects signing performance across the latest window of up to 100 network blocks, considering only blocks where the validator was active. It is not a protocol slashing status.</p>

      <div className="validators-page__summary" aria-label="Validator set summary">
        <div className="validators-page__metric"><span>Active Validators</span><strong>{hasSuccessfulResponse ? response.total.toLocaleString() : '—'}</strong></div>
        <div className="validators-page__metric"><span>Indexed Height</span><strong>{hasSuccessfulResponse ? formatHeight(response.height) : '—'}</strong></div>
        <div className="validators-page__metric"><span>Total Voting Power</span><strong>{hasSuccessfulResponse ? formatIntegerString(response.total_voting_power) : '—'}</strong></div>
      </div>

      {error && hasSuccessfulResponse && <p className="validators-page__notice validators-page__notice--warning">Showing the last loaded validator set. Refresh failed.</p>}

      <div className="validators-page__legend" aria-label="Operational health legend">
        {legend.map((item) => <span key={item.label}><StatusBadge tone={item.tone}>{item.label}</StatusBadge><small>{item.detail}</small></span>)}
      </div>

      <section className="panel validators-page__table">
        <div className="panel__heading">
          <h2>Active Validators</h2>
          <span className="panel__meta">{response.height === null ? 'Height —' : `Height ${formatHeight(response.height)}`} · Live every 15s</span>
        </div>
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.address} loading={loading} emptyMessage={emptyMessage} />
      </section>
    </section>
  )
}
