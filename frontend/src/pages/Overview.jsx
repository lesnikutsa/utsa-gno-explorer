import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { DataTable } from '../components/DataTable'
import { ResourceStrip } from '../components/ResourceStrip'
import { StatusBadge } from '../components/StatusBadge'
import { ValidatorSigningStrip } from '../components/ValidatorSigningStrip'
import { BlocksIcon, ChainIcon, MapIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import { relativeTime } from '../utils/time'
import { shortAddress } from '../utils/address'
import { getMissedBlocks, getValidatorHealth, getValidatorMissedBreakdown } from '../utils/validatorHealth'

const missedSeverity = (missed) => missed >= 10 ? 'high' : missed >= 2 ? 'medium' : 'low'
const OVERVIEW_ROW_LIMIT = 6

const formatUptime = (value) => {
  if (value === null || value === undefined || value === '') return '—'
  const uptime = Number(value)
  return Number.isFinite(uptime) ? `${uptime.toFixed(2)}%` : '—'
}

const sortableUptime = (value) => value === null || value === undefined || value === '' ? Infinity : Number(value)

function RpcStatus({ rpc }) {
  if (!rpc) return <span className="rpc-meta">RPC unavailable</span>

  let hostname = rpc.url
  try { hostname = new URL(rpc.url).hostname } catch { /* Preserve the API value when the URL cannot be parsed. */ }
  const tone = rpc.healthy === true ? 'success' : 'error'

  return <span className="rpc-meta" title={rpc.url}><span className={`rpc-meta__dot rpc-meta__dot--${tone}`} />RPC: {hostname}</span>
}

const blockColumns = [
  { key: 'height', label: 'Height', render: (row) => <a className="table-link" href={`/blocks/${row.height}`}><span className="accent-value mono">#{row.height.toLocaleString()}</span></a> },
  { key: 'time', label: 'Time', render: (row) => relativeTime(row.time) },
  { key: 'proposer_address', label: 'Proposer', render: (row) => <span className="mono muted" title={row.proposer_address}>{shortAddress(row.proposer_address)}</span> },
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
    { key: 'address', label: 'Signing Address', render: (row) => <span className="mono" title={row.address}>{shortAddress(row.address)}</span> },
    { key: 'signing', label: 'Signing (last 100)', render: (row) => {
      const history = row.address ? historyMap.get(row.address) : null
      return <span className="validator-signing-cell"><span title={getValidatorMissedBreakdown(row.uptime_100)}><strong className={`missed-value missed-value--${missedSeverity(row.missedTotal)}`}>{row.missedTotal} missed</strong><span className="muted"> · {formatUptime(row.uptime_100?.uptime_percent)} uptime</span></span><ValidatorSigningStrip blocks={historyBlocks} statuses={history?.statuses} compact address={row.address} /></span>
    } },
    { key: 'health', label: 'Health', render: (row) => {
      const health = getValidatorHealth(row.uptime_100)
      return <span title={`Active set\n${getValidatorMissedBreakdown(row.uptime_100)}`}><StatusBadge tone={health.tone}>{health.label}</StatusBadge></span>
    } },
  ], [historyBlocks, historyMap])
  const validatorsByMisses = useMemo(() => data.validators
    .map((validator) => ({ ...validator, missedTotal: getMissedBlocks(validator.uptime_100) }))
    .filter((validator) => validator.missedTotal > 0)
    .sort((left, right) => {
      if (right.missedTotal !== left.missedTotal) return right.missedTotal - left.missedTotal
      const leftUptime = sortableUptime(left.uptime_100?.uptime_percent)
      const rightUptime = sortableUptime(right.uptime_100?.uptime_percent)
      const uptimeDifference = (Number.isFinite(leftUptime) ? leftUptime : Infinity) - (Number.isFinite(rightUptime) ? rightUptime : Infinity)
      return uptimeDifference || left.address.localeCompare(right.address)
    })
    .slice(0, OVERVIEW_ROW_LIMIT), [data.validators])

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
        <Card eyebrow="Chain ID" icon={ChainIcon} value={data.network?.chain_id ?? (errors.network ? 'Unavailable' : '—')} meta={<RpcStatus rpc={data.network?.selected_rpc} />} loading={loading} />
      </section>

      <div className="dashboard-grid">
        <section className="panel dashboard-grid__blocks">
          <div className="panel__heading"><h2>Latest Blocks</h2><span className="panel__meta panel__meta--live"><span className="live-dot" />Live · every 5s</span></div>
          <DataTable columns={blockColumns} rows={data.blocks.slice(0, OVERVIEW_ROW_LIMIT)} rowKey={(row) => row.height} rowClassName={(row, index) => insertedBlockHeight === null ? '' : index === 0 && row.height === insertedBlockHeight ? 'is-new-row' : 'is-settling-row'} loading={loading} emptyMessage={errors.blocks ? 'Blocks are currently unavailable.' : 'No blocks returned.'} />
        </section>
        <section className="panel dashboard-grid__validators">
          <div className="panel__heading"><h2>Validators by Missed Blocks</h2><span className="panel__meta" title={errors.validatorHistory && data.validatorHistory ? 'Showing the last successfully matched signing history.' : undefined}>{errors.validatorHistory ? (data.validatorHistory ? 'Signing history delayed' : 'Signing history unavailable') : 'Latest 100 network blocks'}</span></div>
          <DataTable columns={validatorColumns} rows={validatorsByMisses} rowKey={(row) => row.address} loading={loading} emptyMessage={errors.validators ? 'Validators are currently unavailable.' : 'No validator misses in the last 100 blocks.'} />
        </section>
      </div>

      <section className="network-preview" aria-labelledby="network-preview-title">
        <header className="network-preview__header">
          <h2 id="network-preview-title">Peers & Decentralization Map</h2>
          <span className="eyebrow">Coming soon</span>
        </header>

        <div className="network-preview__content">
          <div className="network-preview__metrics" aria-label="Future peer metrics">
            <div className="network-preview__metric">
              <span className="network-preview__metric-label">
                <NetworkIcon />
                <span>Total Peers</span>
              </span>
              <strong>—</strong>
            </div>
            <div className="network-preview__metric">
              <span className="network-preview__metric-label">
                <MapIcon />
                <span>Countries</span>
              </span>
              <strong>—</strong>
            </div>
            <div className="network-preview__metric">
              <span className="network-preview__metric-label">
                <ChainIcon />
                <span>Decentralization</span>
              </span>
              <strong>—</strong>
            </div>
          </div>
          <div className="network-preview__map"><img className="network-preview__map-image" src="/assets/network-map.png?v=1" alt="" aria-hidden="true" /></div>
          <div className="network-preview__insight">
            <h3>Network at a glance</h3>
            <p>Peer locations, country coverage, and network distribution—all in one view.</p>
          </div>
          <div className="network-preview__mascot" aria-hidden="true">
            {mascotSrc ? <img src={mascotSrc} alt="" /> : <span>Network mascot</span>}
          </div>
        </div>
      </section>

      <ResourceStrip />
      <footer className="page-footer">Gno.land Explorer by UTSA</footer>
    </>
  )
}
