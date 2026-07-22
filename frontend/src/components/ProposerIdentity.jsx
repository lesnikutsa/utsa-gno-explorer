import { shortAddress } from '../utils/address'

export function ProposerIdentity({ address, moniker, compact = false, showFullAddress = false }) {
  if (!address) return <span className="proposer-identity__empty">—</span>

  const displayMoniker = typeof moniker === 'string' ? moniker.trim() : ''
  const displayAddress = showFullAddress || !compact ? address : shortAddress(address)
  const profilePath = `/validators/${encodeURIComponent(address)}`

  return (
    <div className={`proposer-identity${compact ? ' proposer-identity--compact' : ''}${showFullAddress ? ' proposer-identity--full' : ''}`}>
      {displayMoniker ? (
        <>
          <a className="proposer-identity__moniker-link" href={profilePath} title={address}>
            <strong className="proposer-identity__moniker">{displayMoniker}</strong>
          </a>
          <span className="proposer-identity__address mono" title={address}>{displayAddress}</span>
        </>
      ) : (
        <a className="proposer-identity__fallback-link mono" href={profilePath} title={address}>{displayAddress}</a>
      )}
    </div>
  )
}
