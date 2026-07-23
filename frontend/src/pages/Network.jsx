import { Card } from '../components/Card'
import { StatusBadge } from '../components/StatusBadge'
import { BlocksIcon, ChainIcon, ExternalLinkIcon, NetworkIcon, ValidatorsIcon } from '../components/Icons'
import networkProfile from '../config/networkProfile'

const healthLabels = { loading: '—', healthy: 'Healthy', degraded: 'Degraded', error: 'Error' }
const healthTones = { loading: 'neutral', healthy: 'success', degraded: 'warning', error: 'error' }

function rpcHostname(rpc) {
  if (!rpc) return null
  const value = typeof rpc === 'string' ? rpc : rpc.url
  if (!value) return null
  try { return new URL(value).hostname } catch { return value }
}

function ExternalLink({ href, children }) {
  if (!href) return null
  return <a className="network-page__external-link" href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLinkIcon /></a>
}

export function Network({ networkPage }) {
  const { data, errors, loading, healthState } = networkPage
  const network = data.network
  const latestHeight = network?.latest_block?.height ?? null
  const rpc = rpcHostname(network?.selected_rpc)

  return (
    <div className="network-page">
      <header className="network-page__header">
        <div>
          <span className="eyebrow">{networkProfile.networkName}{network?.chain_id ? ` · ${network.chain_id}` : ''}</span>
          <h1>{networkProfile.projectName}</h1>
          <p className="network-page__description">{networkProfile.description}</p>
        </div>
        <div className="network-page__links" aria-label="Project links">
          <ExternalLink href={networkProfile.links.website}>Website</ExternalLink>
          <ExternalLink href={networkProfile.links.documentation}>Documentation</ExternalLink>
          <ExternalLink href={networkProfile.links.github}>GitHub</ExternalLink>
        </div>
      </header>

      <section aria-labelledby="network-summary-title">
        <h2 className="network-page__section-title" id="network-summary-title">Network Summary</h2>
        <div className="network-summary-grid">
          <Card eyebrow="Network Status" icon={NetworkIcon} value={healthLabels[healthState]} tone={healthState} meta={<StatusBadge tone={healthTones[healthState]}>{healthLabels[healthState]}</StatusBadge>} loading={loading} />
          <Card eyebrow="Latest Block" icon={BlocksIcon} value={latestHeight === null ? (errors.network ? 'Unavailable' : '—') : `#${latestHeight.toLocaleString()}`} meta="Latest API observation" loading={loading} href={latestHeight === null ? undefined : `/blocks/${latestHeight}`} ariaLabel={latestHeight === null ? undefined : `View block ${latestHeight}`} />
          <Card eyebrow="Active Validators" icon={ValidatorsIcon} value={network?.validators?.active_count?.toLocaleString() ?? (errors.network ? 'Unavailable' : '—')} meta="Current validator set" loading={loading} />
          <Card eyebrow="Chain ID" icon={ChainIcon} value={network?.chain_id ?? (errors.network ? 'Unavailable' : '—')} meta={rpc ? `RPC: ${rpc}` : 'RPC unavailable'} loading={loading} />
        </div>
      </section>

      <section className="panel network-page__panel" aria-labelledby="development-title">
        <div className="panel__heading"><h2 id="development-title">Development Activity</h2></div>
        <div className="network-page__empty-state">
          <p>GitHub activity metrics are not connected yet. The next stage will add recent commits, releases, pull requests, issues, and contribution trends.</p>
          <ExternalLink href={networkProfile.links.github}>View repository</ExternalLink>
        </div>
      </section>

      <section className="panel network-page__panel" aria-labelledby="peers-title">
        <div className="panel__heading"><h2 id="peers-title">Peers &amp; Distribution</h2></div>
        <div className="network-map-foundation">
          <div className="network-map-foundation__visual"><img src="/assets/network-map.png?v=1" alt="" aria-hidden="true" /></div>
          <div className="network-page__empty-state">
            <p>Peer collection is not connected yet. Future data will include visible peers, countries, providers, ASN distribution, and scan coverage.</p>
            <p>Visible peers will represent observations from configured RPC sources, not necessarily every node in the network.</p>
          </div>
        </div>
      </section>
    </div>
  )
}
