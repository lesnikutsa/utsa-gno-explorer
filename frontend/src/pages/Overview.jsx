import { Card } from '../components/Card'
import { DataTable } from '../components/DataTable'
import { ResourceStrip } from '../components/ResourceStrip'
import { StatusBadge } from '../components/StatusBadge'
import { BlocksIcon, ChainIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import { relativeTime } from '../utils/time'

const shortAddress = (value) => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '—'
const missedBlocks = (uptime = {}) => (uptime.nil_blocks ?? 0) + (uptime.absent_blocks ?? 0) + (uptime.invalid_blocks ?? 0)

const blockColumns = [
  { key: 'height', label: 'Height', render: (row) => <span className="accent-value mono">#{row.height.toLocaleString()}</span> },
  { key: 'time', label: 'Time', render: (row) => relativeTime(row.time) },
  { key: 'proposer_address', label: 'Proposer', render: (row) => <span className="mono muted" title={row.proposer_address}>{shortAddress(row.proposer_address)}</span> },
  { key: 'tx_count', label: 'Txs' },
  { key: 'block_hash', label: 'Block Hash', render: (row) => <span className="mono muted" title={row.block_hash}>{shortAddress(row.block_hash)}</span> },
]

const validatorColumns = [
  { key: 'address', label: 'Validator', render: (row) => <span className="mono" title={row.address}>{shortAddress(row.address)}</span> },
  { key: 'voting_power', label: 'Voting Power', render: (row) => <span className="mono" title={`Raw voting power: ${row.voting_power}`}>{Number(row.percent).toFixed(2)}%</span> },
  { key: 'missed', label: 'Missed (100)', render: (row) => missedBlocks(row.uptime_100) },
  { key: 'status', label: 'Status', render: () => <StatusBadge tone="success">Active</StatusBadge> },
]

export function Overview({ explorerData, mascotSrc = null }) {
  const { data, errors, loading, healthState } = explorerData
  const networkLabel = { loading: '—', healthy: 'Healthy', degraded: 'Degraded', error: 'Error' }[healthState]

  return (
    <>
      <section className="status-grid" aria-label="Network summary">
        <Card eyebrow="Latest Block" icon={BlocksIcon} value={data.network ? `#${data.network.latest_block.height.toLocaleString()}` : errors.network ? 'Unavailable' : '—'} meta={data.network ? relativeTime(data.network.latest_block.time) : 'Waiting for network data'} loading={loading} />
        <Card eyebrow="Network Status" icon={NetworkIcon} value={networkLabel} tone={healthState} meta={errors.health ? 'API connection unavailable' : 'API connection status'} loading={loading} />
        <Card eyebrow="Active Validators" icon={ValidatorsIcon} value={data.network?.validators?.active_count?.toLocaleString() ?? (errors.network ? 'Unavailable' : '—')} meta="Current validator set" loading={loading} />
        <Card eyebrow="Chain ID" icon={ChainIcon} value={data.network?.chain_id ?? (errors.network ? 'Unavailable' : '—')} meta="Connected network" loading={loading} />
      </section>

      <div className="dashboard-grid">
        <section className="panel dashboard-grid__blocks">
          <div className="panel__heading"><div><span className="eyebrow">Live feed</span><h2>Latest Blocks</h2></div><span className="panel__meta">Auto-updated</span></div>
          <DataTable columns={blockColumns} rows={data.blocks.slice(0, 5)} rowKey={(row) => row.height} loading={loading} emptyMessage={errors.blocks ? 'Blocks are currently unavailable.' : 'No blocks returned.'} />
        </section>
        <section className="panel dashboard-grid__validators">
          <div className="panel__heading"><div><span className="eyebrow">Validator set</span><h2>Validator Overview</h2></div><span className="panel__meta">Top voting power</span></div>
          <DataTable columns={validatorColumns} rows={data.validators.slice(0, 5)} rowKey={(row) => row.address} loading={loading} emptyMessage={errors.validators ? 'Validators are currently unavailable.' : 'No validators returned.'} />
        </section>
      </div>

      <section className="map-placeholder">
        <div className="map-placeholder__summary">
          <span className="eyebrow">Coming soon</span><h2>Peers & Decentralization Map</h2>
          <div className="map-placeholder__stats" aria-label="Future peer metrics">
            <div><span>Total Peers</span><strong>—</strong></div>
            <div><span>Countries</span><strong>—</strong></div>
            <div><span>Decentralization</span><strong>—</strong></div>
          </div>
        </div>
        <div className="map-placeholder__canvas"><span>Future network map</span></div>
        <div className="map-placeholder__asset" aria-hidden="true">{mascotSrc ? <img src={mascotSrc} alt="" /> : <span>Network mascot</span>}</div>
      </section>

      <ResourceStrip />
      <footer className="page-footer">Gno.land Explorer by UTSA</footer>
    </>
  )
}
