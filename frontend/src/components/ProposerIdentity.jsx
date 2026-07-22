import { shortAddress } from '../utils/address'

export function ProposerIdentity({ address, moniker, compact = false, showFullAddress = false }) {
  if (!address) return <span className="proposer-identity__empty">—</span>

  const displayMoniker = typeof moniker === 'string' ? moniker.trim() : ''
  const displayAddress = showFullAddress || !compact ? address : shortAddress(address)

  return (
    <a
      className={`proposer-identity proposer-identity--link${compact ? ' proposer-identity--compact' : ''}${showFullAddress ? ' proposer-identity--full' : ''}`}
      href={`/validators/${encodeURIComponent(address)}`}
      title={address}
    >
      {displayMoniker && <strong className="proposer-identity__moniker">{displayMoniker}</strong>}
      <span className={`proposer-identity__address mono${displayMoniker ? '' : ' proposer-identity__address--fallback'}`}>{displayAddress}</span>
    </a>
  )
}
