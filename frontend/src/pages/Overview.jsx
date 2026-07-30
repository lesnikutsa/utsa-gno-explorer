import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { DataTable } from '../components/DataTable'
import { ResourceStrip } from '../components/ResourceStrip'
import { StatusBadge } from '../components/StatusBadge'
import { ValidatorSigningStrip } from '../components/ValidatorSigningStrip'
import { ProposerIdentity } from '../components/ProposerIdentity'
import { NetworkDistributionPanel } from '../components/NetworkDistributionPanel'
import { RpcPoolStatus } from '../components/RpcPoolStatus'
import { BlocksIcon, ChainIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import { relativeTime } from '../utils/time'
import { shortAddress } from '../utils/address'
import { getMissedBlocks, getValidatorHealth, getValidatorMissedBreakdown } from '../utils/validatorHealth'
import { hasValidatorMoniker } from '../utils/validatorIdentity'
import { networkProfile } from '../config/networkProfile'

const missedSeverity = (missed) => missed >= 50 ? 'high' : missed >= 10 ? 'medium' : 'low'
const LATEST_BLOCKS_ROW_LIMIT = 7
const OVERVIEW_VALIDATOR_ROW_LIMIT = 6

const formatUptime = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  const uptime = Number(value)
  return Number.isFinite(uptime) ? `${uptime.toFixed(2)}%` : '—'
}

const sortableUptime = (value) => value === null || value === undefined || value === '' ? Infinity : Number(value)

const blockColumns = [
  { key: 'height', label: 'Height', render: (row) => <a className="table-link" href={`/blocks/${row.height}`}><span className="accent-value mono">#{row.height.toLocaleString()}</span></a> },
  { key: 'time', label: 'Time', render: (row) => relativeTime(row.time) },
  { key: 'proposer_address', label: 'Proposer', render: (row) => <ProposerIdentity address={row.proposer_address} moniker={row.proposer_moniker} compact /> },
  { key: 'tx_count', label: 'Txs' },
  { key: 'block_hash', label: 'Block Hash', render: (row) => <span className="mono muted" title={row.block_hash}>{shortAddress(row.block_hash)}</span> },
]

export function Overview({ explorerData, mascotSrc = null }) {
  const { data, errors, loading, healthState } = explorerData
  const networkLabel = { loading: '—', healthy: 'Healthy', degraded: 'Degraded', error: 'Error' }[healthState]
  const latestHeight = data.network?.latest_block.height ?? null
  const firstBlockHeight = data.blocks[0]?.height ?? null
  const previousLatestHeight = useRef(null)
  const previousFirstBlockHeight = useRef(null)
  const [updatedLatestHeight, setUpdatedLatestHeight] = useState(null)
  const [insertedBlockHeight, setInsertedBlockHeight] = useState(null)
  const historyMap = useMemo(() => new Map(
    (data.validatorHistory?.items ?? []).filter((item) => item?.address).map((item) => [item.address, item]),
  ), [data.validatorHistory])
  const historyBlocks = data.validatorHistory?.blocks
  const validatorColumns = useMemo(() => [
    { key: 'address', label: 'Validator', render: (row) => (
      <a className="validator-identity validator-identity--link" href={`/validators/${encodeURIComponent(row.address)}`} title={row.address}>
        {hasValidatorMoniker(row) ? (
          <>
            <strong className="validator-identity__moniker">{row.moniker}</strong>
            <span className="validator-identity__address mono">{shortAddress(row.address)}</span>
          </>
        ) : (
          <strong className="validator-identity__fallback mono">{shortAddress(row.address)}</strong>
        )}
      </a>
    ) },
    { key: 'signing', label: 'Signing (1000)', render: (row) => {
      const history = row.address ? historyMap.get(row.address) : null
      return <span className="validator-signing-cell"><span title={getValidatorMissedBreakdown(row.uptime_1000)}><strong className={`missed-value missed-value--${missedSeverity(row.missedTotal)}`}>{row.missedTotal} missed</strong><span className="muted"> · {formatUptime(row.uptime_1000?.uptime_percent)} uptime</span></span><ValidatorSigningStrip blocks={historyBlocks} statuses={history?.statuses} compact address={row.address} /></span>
    } },
    { key: 'health', label: 'Health', render: (row) => {
      const health = getValidatorHealth(row.uptime_1000)
      return <span title={`Active set\n${getValidatorMissedBreakdown(row.uptime_1000)}`}><StatusBadge tone={health.tone}>{health.label}</StatusBadge></span>
    } },
  ], [historyBlocks, historyMap])
  const validatorsByMisses = useMemo(() => data.validators
    .map((validator) => ({ ...validator, missedTotal: getMissedBlocks(validator.uptime_1000) }))
    .filter((validator) => validator.missedTotal > 0)
    .sort((left, right) => {
      if (right.missedTotal !== left.missedTotal) return right.missedTotal - left.missedTotal
      const leftUptime = sortableUptime(left.uptime_1000?.uptime_percent)
      const rightUptime = sortableUptime(right.uptime_1000?.uptime_percent)
      const uptimeDifference = (Number.isFinite(leftUptime) ? leftUptime : Infinity) - (Number.isFinite(rightUptime) ? rightUptime : Infinity)
      return uptimeDifference || left.address.localeCompare(right.address)
    })
    .slice(0, OVERVIEW_VALIDATOR_ROW_LIMIT), [data.validators])

  useEffect(() => {
    const timers = []
    if (previousLatestHeight.current !== null && latestHeight !== previousLatestHeight.current) {
      setUpdatedLatestHeight(latestHeight)
      timers.push(window.setTimeout(() => setUpdatedLatestHeight(null), 720))
    }
    if (previousFirstBlockHeight.current !== null && firstBlockHeight !== previousFirstBlockHeight.current) {
      setInsertedBlockHeight(firstBlockHeight)
      timers.push(window.setTimeout(() => setInsertedBlockHeight(null), 900))
    }
    previousLatestHeight.current = latestHeight
    previousFirstBlockHeight.current = firstBlockHeight
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [latestHeight, firstBlockHeight])

  return (
    <>
      <section className="status-grid" aria-label="Network summary">
        <Card eyebrow="Latest Block" icon={BlocksIcon} value={data.network ? `#${data.network.latest_block.height.toLocaleString()}` : errors.network ? 'Unavailable' : '—'} meta="Auto-refresh every 5s" updating={updatedLatestHeight === latestHeight} loading={loading} href={latestHeight === null ? undefined : `/blocks/${latestHeight}`} ariaLabel={latestHeight === null ? undefined : `View block ${latestHeight}`} />
        <Card eyebrow="Network Status" icon={NetworkIcon} value={networkLabel} tone={healthState} meta={errors.health ? 'API connection unavailable' : 'API connection status'} loading={loading} />
        <Card eyebrow="Active Validators" icon={ValidatorsIcon} value={data.network?.validators?.active_count?.toLocaleString() ?? (errors.network ? 'Unavailable' : '—')} meta="Current validator set" loading={loading} />
        <Card eyebrow="Chain ID" icon={ChainIcon} value={data.network?.chain_id ?? (errors.network ? 'Unavailable' : '—')} meta={<RpcPoolStatus pool={data.network?.rpc_pool} selectedRpc={data.network?.selected_rpc} />} loading={loading} />
      </section>

      <div className="dashboard-grid">
        <section className="panel dashboard-grid__blocks">
          <div className="panel__heading"><h2>Latest Blocks</h2><span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 5s</span></div>
          <DataTable columns={blockColumns} rows={data.blocks.slice(0, LATEST_BLOCKS_ROW_LIMIT)} rowKey={(row) => row.height} rowClassName={(row, index) => insertedBlockHeight === null ? '' : index === 0 && row.height === insertedBlockHeight ? 'is-new-row' : 'is-settling-row'} loading={loading} emptyMessage={errors.blocks ? 'Blocks are currently unavailable.' : 'No blocks returned.'} />
        </section>
        <section className="panel dashboard-grid__validators">
          <div className="panel__heading"><h2>Validators by Missed Blocks</h2><span className="panel__meta" title={errors.validatorHistory && data.validatorHistory ? 'Showing the last successfully matched signing history.' : undefined}>{errors.validatorHistory ? (data.validatorHistory ? 'Signing history delayed' : 'Signing history unavailable') : 'Latest 50 signing blocks'}</span></div>
          <DataTable columns={validatorColumns} rows={validatorsByMisses} rowKey={(row) => row.address} loading={loading} emptyMessage={errors.validators ? 'Validators are currently unavailable.' : 'No validator misses in the last 1000 blocks.'} />
        </section>
      </div>

      <NetworkDistributionPanel distribution={data.distribution} error={errors.distribution} loading={loading} mascotSrc={mascotSrc} />

      <ResourceStrip />
      <footer className="page-footer">{networkProfile.projectName} Explorer by UTSA</footer>
    </>
  )
}
