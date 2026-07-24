import { useState } from 'react'
import { MapIcon, NetworkIcon } from './Icons'
import { countryFlag } from '../utils/countryFlag'
import { relativeTime } from '../utils/time'

export const DISTRIBUTION_TOP_LIMIT = 10

const formatCount = (value) => {
  const count = Number(value)
  return Number.isFinite(count) && Number.isInteger(count) && count >= 0 ? count.toLocaleString() : '—'
}

const formatPercent = (value) => {
  const percent = Number(value)
  if (!Number.isFinite(percent)) return '—'
  return `${Number(percent.toFixed(2))}%`
}

function Metric({ Icon, label, value }) {
  return <div className="network-preview__metric"><span className="network-preview__metric-label"><Icon /><span>{label}</span></span><strong>{formatCount(value)}</strong></div>
}

function RankingList({ id, items, kind }) {
  return (
    <ol id={id} className="distribution-ranking">
      {items.map((item, index) => {
        const flag = kind === 'country' ? countryFlag(item?.code) : ''
        return <li className="distribution-ranking__row" key={index}>
          <span className="distribution-ranking__position">{index + 1}.</span>
          <span className="distribution-ranking__identity" title={kind === 'provider' && typeof item?.name === 'string' ? item.name : undefined}>
            <span className="distribution-ranking__name">{flag && <span className="distribution-ranking__flag" aria-hidden="true">{flag}</span>}{typeof item?.name === 'string' && item.name ? item.name : '—'}</span>
            {kind === 'provider' && item?.asn !== null && item?.asn !== undefined && item.asn !== '' && <span className="distribution-ranking__asn">AS{formatCount(item.asn)}</span>}
          </span>
          <span className="distribution-ranking__count">{formatCount(item?.count)}</span>
          <span className="distribution-ranking__percent">{formatPercent(item?.share_percent)}</span>
        </li>
      })}
    </ol>
  )
}

export function NetworkDistributionPanel({ distribution, error = false, loading = false, mascotSrc = null }) {
  const [showAllCountries, setShowAllCountries] = useState(false)
  const [showAllProviders, setShowAllProviders] = useState(false)
  const countries = Array.isArray(distribution?.countries) ? distribution.countries : []
  const providers = Array.isArray(distribution?.providers) ? distribution.providers : []
  const regions = Array.isArray(distribution?.regions) ? distribution.regions : []
  const sourcesOk = formatCount(distribution?.rpc_sources?.ok)
  const sourcesTotal = formatCount(distribution?.rpc_sources?.total)
  const hasSnapshot = distribution !== null && typeof distribution === 'object'
  const updatedAt = typeof distribution?.updated_at === 'string' ? distribution.updated_at : ''

  let metadata = 'Network distribution unavailable'
  if (loading && !hasSnapshot && !error) metadata = 'Loading network snapshot…'
  else if (hasSnapshot && error) metadata = <>Data delayed · Updated {updatedAt ? <time dateTime={updatedAt} title={updatedAt}>{relativeTime(updatedAt)}</time> : '—'}</>
  else if (hasSnapshot) metadata = <>Updated {updatedAt ? <time dateTime={updatedAt} title={updatedAt}>{relativeTime(updatedAt)}</time> : '—'} · {sourcesOk}/{sourcesTotal} RPC sources · Geo coverage {formatPercent(distribution.geolocation_coverage_percent)}</>

  return (
    <section className="network-preview" aria-labelledby="network-preview-title">
      <header className="network-preview__header"><h2 id="network-preview-title">Peers &amp; Decentralization Map</h2></header>
      <div className="network-preview__content">
        <div className="network-preview__metrics" aria-label="Observed peer metrics">
          <Metric Icon={NetworkIcon} label="Visible Peers" value={distribution?.visible_node_ids} />
          <Metric Icon={MapIcon} label="Countries" value={distribution?.country_count} />
          <Metric Icon={NetworkIcon} label="Providers" value={distribution?.provider_count} />
        </div>
        <div className="network-preview__map"><img className="network-preview__map-image" src="/assets/network-map.png?v=1" alt="" aria-hidden="true" /></div>
        <div className="network-preview__insight"><h3>Network at a glance</h3><p>{hasSnapshot ? `Observed through ${sourcesOk}/${sourcesTotal} RPC sources. The observed network distribution is calculated from unique public IPs; peer identities and IP addresses are not exposed.` : 'This view summarizes an observed network sample when distribution data is available.'}</p></div>
        <div className="network-preview__mascot" aria-hidden="true">{mascotSrc ? <img src={mascotSrc} alt="" /> : <span>Network mascot</span>}</div>
      </div>
      <section className="distribution" aria-labelledby="distribution-title">
        <div className="distribution__heading"><h3 id="distribution-title">Observed Network Distribution</h3><p className={`distribution__metadata${error ? ' distribution__metadata--delayed' : ''}`}>{metadata}</p></div>
        {!hasSnapshot && error ? <p className="distribution__unavailable">Network distribution is currently unavailable.</p> : hasSnapshot ? <>
          <section className="distribution__regions" aria-labelledby="distribution-regions-title"><h4 id="distribution-regions-title">Regions</h4>{regions.length ? <ul className="distribution-region-list">{regions.map((region, index) => <li key={index}><span>{typeof region?.name === 'string' && region.name ? region.name : '—'}</span><span>{formatCount(region?.count)}</span><span>{formatPercent(region?.share_percent)}</span></li>)}</ul> : <p className="distribution__empty">No regional distribution available.</p>}</section>
          <div className="distribution__rankings">
            <section aria-labelledby="distribution-countries-title"><h4 id="distribution-countries-title">Countries</h4><RankingList id="distribution-countries" kind="country" items={showAllCountries ? countries : countries.slice(0, DISTRIBUTION_TOP_LIMIT)} />{countries.length > DISTRIBUTION_TOP_LIMIT && <button className="distribution__toggle" type="button" aria-expanded={showAllCountries} aria-controls="distribution-countries" onClick={() => setShowAllCountries((value) => !value)}>{showAllCountries ? 'Show top 10' : `Show all (${countries.length})`}</button>}</section>
            <section aria-labelledby="distribution-providers-title"><h4 id="distribution-providers-title">Providers / ASN Organizations</h4><RankingList id="distribution-providers" kind="provider" items={showAllProviders ? providers : providers.slice(0, DISTRIBUTION_TOP_LIMIT)} />{providers.length > DISTRIBUTION_TOP_LIMIT && <button className="distribution__toggle" type="button" aria-expanded={showAllProviders} aria-controls="distribution-providers" onClick={() => setShowAllProviders((value) => !value)}>{showAllProviders ? 'Show top 10' : `Show all (${providers.length})`}</button>}</section>
          </div>
        </> : null}
      </section>
    </section>
  )
}
