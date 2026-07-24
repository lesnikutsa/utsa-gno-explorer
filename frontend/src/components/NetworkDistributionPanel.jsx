import { useState } from 'react'
import { MapIcon, NetworkIcon } from './Icons'
import { countryFlag } from '../utils/countryFlag'
import { formatDistributionAsn, formatDistributionCount, formatDistributionPercent, validDistributionTimestamp } from '../utils/networkDistributionFormat'
import { relativeTime } from '../utils/time'

export const DISTRIBUTION_TOP_LIMIT = 10

function Metric({ Icon, label, value }) {
  return <div className="network-preview__metric"><span className="network-preview__metric-label"><Icon /><span>{label}</span></span><strong>{formatDistributionCount(value)}</strong></div>
}

const aggregateKey = (item, index, kind) => {
  if (kind === 'country' && typeof item?.code === 'string' && item.code) return `country-${item.code}`
  if (kind === 'provider') {
    const asn = formatDistributionAsn(item?.asn)
    if (asn) return `provider-${asn}`
    if (typeof item?.name === 'string' && item.name.trim()) return `provider-name-${item.name.trim().toLocaleLowerCase()}`
  }
  return `${kind}-invalid-${index}`
}

function RankingList({ id, items, kind }) {
  return (
    <ol id={id} className="distribution-ranking">
      {items.map((item, index) => {
        const flag = kind === 'country' ? countryFlag(item?.code) : ''
        const asn = kind === 'provider' ? formatDistributionAsn(item?.asn) : ''
        const key = aggregateKey(item, index, kind)
        const duplicateKey = items.findIndex((candidate, candidateIndex) => aggregateKey(candidate, candidateIndex, kind) === key) !== index
        return <li className="distribution-ranking__row" key={duplicateKey ? `${key}-${index}` : key}>
          <span className="distribution-ranking__position power-rank">#{index + 1}</span>
          <span className="distribution-ranking__identity" title={kind === 'provider' && typeof item?.name === 'string' ? item.name : undefined}>
            <span className="distribution-ranking__name">{flag && <span className={`distribution-ranking__flag ${flag}`} aria-hidden="true" />}{typeof item?.name === 'string' && item.name ? item.name : '—'}</span>
            {asn && <span className="distribution-ranking__asn">{asn}</span>}
          </span>
          <span className="distribution-ranking__count">{formatDistributionCount(item?.count)}</span>
          <span className="distribution-ranking__percent">{formatDistributionPercent(item?.share_percent)}</span>
        </li>
      })}
    </ol>
  )
}

export function NetworkDistributionPanel({ distribution, error = false, loading = false, mascotSrc = null }) {
  const [showAllCountries, setShowAllCountries] = useState(false)
  const [showAllProviders, setShowAllProviders] = useState(false)
  const updatedAt = !Array.isArray(distribution) && distribution !== null && typeof distribution === 'object'
    ? validDistributionTimestamp(distribution.updated_at)
    : ''
  const hasUsableSnapshot = updatedAt !== ''
  const snapshot = hasUsableSnapshot ? distribution : null
  const countries = Array.isArray(snapshot?.countries) ? snapshot.countries : []
  const providers = Array.isArray(snapshot?.providers) ? snapshot.providers : []
  const regions = Array.isArray(snapshot?.regions) ? snapshot.regions : []
  const sourcesOk = formatDistributionCount(snapshot?.rpc_sources?.ok)
  const sourcesTotal = formatDistributionCount(snapshot?.rpc_sources?.total)
  const rpcSourceLabel = snapshot?.rpc_sources?.total === 1 ? 'RPC source' : 'RPC sources'

  let metadata = 'Network distribution unavailable'
  if (!hasUsableSnapshot && loading) metadata = 'Loading network snapshot…'
  else if (hasUsableSnapshot && error) metadata = <>Data delayed · Updated <time dateTime={updatedAt} title={updatedAt}>{relativeTime(updatedAt)}</time></>
  else if (hasUsableSnapshot) metadata = <>Updated <time dateTime={updatedAt} title={updatedAt}>{relativeTime(updatedAt)}</time> · {sourcesOk}/{sourcesTotal} {rpcSourceLabel} · Geo coverage {formatDistributionPercent(snapshot.geolocation_coverage_percent)}</>

  return (
    <section className="network-preview" aria-labelledby="network-preview-title">
      <header className="network-preview__header"><h2 id="network-preview-title">Peers &amp; Decentralization Map</h2></header>
      <div className="network-preview__content">
        <div className="network-preview__metrics" aria-label="Observed peer metrics">
          <Metric Icon={NetworkIcon} label="Visible Peers" value={snapshot?.visible_node_ids} />
          <Metric Icon={MapIcon} label="Countries" value={snapshot?.country_count} />
          <Metric Icon={NetworkIcon} label="Providers" value={snapshot?.provider_count} />
        </div>
        <div className="network-preview__map"><img className="network-preview__map-image" src="/assets/network-map.png?v=1" alt="" aria-hidden="true" /></div>
        <div className="network-preview__insight"><h3>Network at a glance</h3><p>{hasUsableSnapshot ? `Observed through ${sourcesOk}/${sourcesTotal} ${rpcSourceLabel} · Based on unique public IPs` : 'Observed network distribution will appear when snapshot data is available.'}</p></div>
        <div className="network-preview__mascot" aria-hidden="true">{mascotSrc ? <img src={mascotSrc} alt="" /> : <span>Network mascot</span>}</div>
      </div>
      <section className="distribution" aria-labelledby="distribution-title">
        <div className="distribution__heading"><h3 id="distribution-title">Observed Network Distribution</h3><p className={`distribution__metadata${error && hasUsableSnapshot ? ' distribution__metadata--delayed' : ''}`}>{metadata}</p></div>
        {!hasUsableSnapshot && !loading ? <p className="distribution__unavailable">Network distribution is currently unavailable.</p> : hasUsableSnapshot ? <>
          <section className="distribution__regions" aria-labelledby="distribution-regions-title"><h4 id="distribution-regions-title">Regions</h4>{regions.length ? <ul className="distribution-region-list">{regions.map((region, index) => <li key={typeof region?.name === 'string' && region.name ? `region-${region.name}` : `region-invalid-${index}`}><span>{typeof region?.name === 'string' && region.name ? region.name : '—'}</span><span>{formatDistributionCount(region?.count)}</span><span>{formatDistributionPercent(region?.share_percent)}</span></li>)}</ul> : <p className="distribution__empty">No regional distribution available.</p>}</section>
          <div className="distribution__rankings">
            <section aria-labelledby="distribution-countries-title"><h4 id="distribution-countries-title">Countries</h4>{countries.length ? <RankingList id="distribution-countries" kind="country" items={showAllCountries ? countries : countries.slice(0, DISTRIBUTION_TOP_LIMIT)} /> : <p id="distribution-countries" className="distribution__empty">No country distribution available.</p>}{countries.length > DISTRIBUTION_TOP_LIMIT && <button className="distribution__toggle" type="button" aria-expanded={showAllCountries} aria-controls="distribution-countries" onClick={() => setShowAllCountries((value) => !value)}>{showAllCountries ? 'Show top 10' : `Show all (${countries.length})`}</button>}</section>
            <section aria-labelledby="distribution-providers-title"><h4 id="distribution-providers-title">Providers / ASN Organizations</h4>{providers.length ? <RankingList id="distribution-providers" kind="provider" items={showAllProviders ? providers : providers.slice(0, DISTRIBUTION_TOP_LIMIT)} /> : <p id="distribution-providers" className="distribution__empty">No provider distribution available.</p>}{providers.length > DISTRIBUTION_TOP_LIMIT && <button className="distribution__toggle" type="button" aria-expanded={showAllProviders} aria-controls="distribution-providers" onClick={() => setShowAllProviders((value) => !value)}>{showAllProviders ? 'Show top 10' : `Show all (${providers.length})`}</button>}</section>
          </div>
        </> : null}
      </section>
    </section>
  )
}
