import { useMemo, useState } from 'react'
import { DataTable } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { SIGNING_STATUSES, getSigningStatusLabel, ValidatorSigningStrip } from '../components/ValidatorSigningStrip'
import { shortAddress } from '../utils/address'
import {
  compareIntegerStrings,
  compareValidatorHealth,
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

const legend = [
  { label: 'Healthy', tone: 'success', detail: 'less than 10% missed' },
  { label: 'Degraded', tone: 'warning', detail: '10–49% missed' },
  { label: 'Critical', tone: 'error', detail: '50–99% missed' },
  { label: 'No signatures', tone: 'error', detail: 'all active blocks missed' },
  { label: 'Unknown / No data', tone: 'neutral', detail: 'incomplete or unavailable signing history' },
]

export function Validators({ validatorsPage }) {
  const [sort, setSort] = useState({ key: 'voting_power', direction: 'descending' })
  const { response, validators, historyResponse, loading, backgroundRefreshing, manualRefreshing, error, historyError, hasSuccessfulResponse, hasSuccessfulHistoryResponse, refresh } = validatorsPage
  const historyMap = useMemo(() => new Map(
    (historyResponse?.items ?? []).filter((item) => item?.address).map((item) => [item.address, item]),
  ), [historyResponse])
  const historyBlocks = historyResponse?.blocks
  const columns = useMemo(() => [
    { key: 'powerRank', label: 'Power Rank', render: (row) => <span className="mono">#{row.powerRank}</span> },
    { key: 'address', label: 'Signing Address', sortable: true, defaultSortDirection: 'ascending', render: (row) => <span className="mono" title={row.address}>{shortAddress(row.address)}</span> },
    { key: 'voting_power', label: 'Voting Power', sortable: true, defaultSortDirection: 'descending', render: (row) => <span className="validator-power mono"><span>{formatIntegerString(row.voting_power)}</span><span className="validator-power__percent">{formatPercent(row.percent)}</span></span> },
    { key: 'uptime_100', label: 'Uptime (100)', sortable: true, defaultSortDirection: 'descending', render: (row) => <span className="mono">{formatPercent(row.uptime_100?.uptime_percent)}</span> },
    { key: 'missed_100', label: 'Signing (100)', sortable: true, defaultSortDirection: 'descending', render: (row) => {
      const missed = getMissedBlocks(row.uptime_100)
      const history = row.address ? historyMap.get(row.address) : null
      return <span className="validator-signing-cell"><strong className={`missed-value missed-value--${missedSeverity(missed)}`} title={getValidatorMissedBreakdown(row.uptime_100)}>{missed} missed</strong><ValidatorSigningStrip blocks={historyBlocks} statuses={history?.statuses} address={row.address} /></span>
    } },
    { key: 'health_100', label: 'Health (100)', sortable: true, defaultSortDirection: 'descending', render: (row) => healthBadge(row.uptime_100) },
    { key: 'proposer_priority', label: 'Proposer Priority', sortable: true, defaultSortDirection: 'descending', headerTitle: 'Consensus proposer-selection priority. A higher current value generally means the validator is closer to proposing. This is not a performance or health score.', render: (row) => <span className="mono">{formatIntegerString(row.proposer_priority)}</span> },
  ], [historyBlocks, historyMap])
  const rows = useMemo(() => validators.map((validator, index) => ({ ...validator, powerRank: index + 1 })), [validators])
  const sortedRows = useMemo(() => [...rows].sort((left, right) => {
    let comparison = 0
    if (sort.key === 'address') comparison = left.address.localeCompare(right.address)
    if (sort.key === 'voting_power') comparison = compareIntegerStrings(left.voting_power, right.voting_power)
    if (sort.key === 'uptime_100') comparison = (left.uptime_100?.uptime_percent ?? 0) - (right.uptime_100?.uptime_percent ?? 0)
    if (sort.key === 'missed_100') comparison = getMissedBlocks(left.uptime_100) - getMissedBlocks(right.uptime_100)
    if (sort.key === 'health_100') comparison = compareValidatorHealth(getValidatorHealth(left.uptime_100).key, getValidatorHealth(right.uptime_100).key)
    if (sort.key === 'proposer_priority') comparison = compareIntegerStrings(left.proposer_priority, right.proposer_priority)
    if (comparison === 0) return left.powerRank - right.powerRank
    return sort.direction === 'ascending' ? comparison : -comparison
  }), [rows, sort])
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
      {historyError && hasSuccessfulHistoryResponse && <p className="validators-page__notice validators-page__notice--warning">Showing the last matched signing history. Refresh failed or checkpoints did not align.</p>}
      {historyError && !hasSuccessfulHistoryResponse && <p className="validators-page__notice validators-page__notice--warning">Signing history is currently unavailable.</p>}

      <div className="validators-page__legend" aria-label="Operational health legend">
        {legend.map((item) => <span key={item.label}><StatusBadge tone={item.tone}>{item.label}</StatusBadge><small>{item.detail}</small></span>)}
      </div>

      <div className="signing-legend" aria-label="Signing history legend">
        <strong>Signing history:</strong>
        {SIGNING_STATUSES.map((status) => <span key={status}><i className={`signing-strip__segment signing-strip__segment--${status}`} aria-hidden="true" />{getSigningStatusLabel(status)}</span>)}
      </div>

      <section className="panel validators-page__table">
        <div className="panel__heading">
          <h2>Active Validators</h2>
          <span className="panel__meta">{response.height === null ? 'Height —' : `Height ${formatHeight(response.height)}`} · Live every 15s</span>
        </div>
        <DataTable columns={columns} rows={sortedRows} rowKey={(row) => row.address} loading={loading} emptyMessage={emptyMessage} sortKey={sort.key} sortDirection={sort.direction} onSort={(key, direction) => setSort({ key, direction })} />
      </section>
    </section>
  )
}
