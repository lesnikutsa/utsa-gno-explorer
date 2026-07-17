import { useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { DataTable } from '../components/DataTable'
import { ResourceStrip } from '../components/ResourceStrip'
import { StatusBadge } from '../components/StatusBadge'
import { getBlocks, getHealth, getNetwork, getValidators } from '../services/api'

const shortAddress = (value) => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '—'
const formatTime = (value) => value ? new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value)) : '—'
const formatInteger = (value) => {
  try { return BigInt(value).toLocaleString() } catch { return value ?? '—' }
}

const blockColumns = [
  { key: 'height', label: 'Height', render: (row) => <span className="accent-value mono">#{row.height.toLocaleString()}</span> },
  { key: 'time', label: 'Time', render: (row) => formatTime(row.time) },
  { key: 'proposer_address', label: 'Proposer', render: (row) => <span className="mono muted" title={row.proposer_address}>{shortAddress(row.proposer_address)}</span> },
  { key: 'tx_count', label: 'Txs' },
  { key: 'size', label: 'Size', render: () => <span className="muted">—</span> },
]

const validatorColumns = [
  { key: 'address', label: 'Validator', render: (row) => <span className="mono" title={row.address}>{shortAddress(row.address)}</span> },
  { key: 'voting_power', label: 'Voting Power', render: (row) => <span className="mono">{formatInteger(row.voting_power)}</span> },
  { key: 'missed', label: 'Missed (100)', render: (row) => row.uptime_100?.absent_blocks ?? '—' },
  { key: 'status', label: 'Status', render: () => <StatusBadge tone="success">Active</StatusBadge> },
]

export function Overview() {
  const [data, setData] = useState({ health: null, network: null, blocks: [], validators: [] })
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    let active = true
    const load = async () => {
      const requests = await Promise.allSettled([getHealth(), getNetwork(), getBlocks(), getValidators()])
      if (!active) return
      const [health, network, blocks, validators] = requests
      setData({
        health: health.status === 'fulfilled' ? health.value : null,
        network: network.status === 'fulfilled' ? network.value : null,
        blocks: blocks.status === 'fulfilled' ? blocks.value.items ?? [] : [],
        validators: validators.status === 'fulfilled' ? validators.value.items ?? [] : [],
      })
      setErrors({
        health: health.status === 'rejected', network: network.status === 'rejected',
        blocks: blocks.status === 'rejected', validators: validators.status === 'rejected',
      })
      setLoading(false)
    }
    load()
    return () => { active = false }
  }, [])

  const healthy = data.health?.status === 'ok'

  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow eyebrow--accent">Network intelligence</span><h1>Overview</h1><p>Real-time activity across the Gno.land network.</p></div>
        <div className="page-heading__sync"><span className="pulse" /><div><span>Explorer sync</span><strong>{data.health ? `Block ${data.health.indexed_height.toLocaleString()}` : 'Awaiting data'}</strong></div></div>
      </div>

      <section className="status-grid" aria-label="Network summary">
        <Card eyebrow="Latest Block" icon="▦" value={data.network ? `#${data.network.latest_block.height.toLocaleString()}` : errors.network ? 'Unavailable' : '—'} meta={data.network ? `Indexed ${formatTime(data.network.latest_block.time)}` : 'Waiting for network data'} loading={loading} />
        <Card eyebrow="Network Status" icon="⌁" value={errors.health ? 'Error' : healthy ? 'Healthy' : data.health ? 'Degraded' : '—'} meta={errors.health ? 'API connection unavailable' : 'API connection status'} loading={loading} />
        <Card eyebrow="Active Validators" icon="◇" value={data.network?.validators?.active_count?.toLocaleString() ?? (errors.network ? 'Unavailable' : '—')} meta="Current validator set" loading={loading} />
        <Card eyebrow="Chain ID" icon="◎" value={data.network?.chain_id ?? (errors.network ? 'Unavailable' : '—')} meta="Connected network" loading={loading} />
      </section>

      <div className="dashboard-grid">
        <section className="panel dashboard-grid__blocks">
          <div className="panel__heading"><div><span className="eyebrow">Live feed</span><h2>Latest Blocks</h2></div><span className="panel__meta">Auto-updated</span></div>
          <DataTable columns={blockColumns} rows={data.blocks.slice(0, 8)} rowKey={(row) => row.height} loading={loading} emptyMessage={errors.blocks ? 'Blocks are currently unavailable.' : 'No blocks returned.'} />
        </section>
        <section className="panel dashboard-grid__validators">
          <div className="panel__heading"><div><span className="eyebrow">Validator set</span><h2>Validator Overview</h2></div><span className="panel__meta">Top voting power</span></div>
          <DataTable columns={validatorColumns} rows={data.validators.slice(0, 8)} rowKey={(row) => row.address} loading={loading} emptyMessage={errors.validators ? 'Validators are currently unavailable.' : 'No validators returned.'} />
        </section>
      </div>

      <section className="map-placeholder">
        <div className="map-placeholder__visual" aria-hidden="true"><span className="map-dot map-dot--one" /><span className="map-dot map-dot--two" /><span className="map-dot map-dot--three" /></div>
        <div><span className="eyebrow">Coming soon</span><h2>Peers & Decentralization Map</h2><p>Peers data and network map coming soon.</p></div>
        <StatusBadge>Future module</StatusBadge>
      </section>

      <ResourceStrip />
      <footer className="page-footer"><span>UTSA Gno.land Explorer</span><span className="mono">Built for the builders.</span></footer>
    </>
  )
}
