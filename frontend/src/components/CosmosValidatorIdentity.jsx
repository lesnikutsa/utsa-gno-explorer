import { useState } from 'react'
import { shortAddress } from '../utils/address'

const initials = (moniker) => (moniker || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || '?'

export function CosmosValidatorIdentity({ moniker, address, imageSrc, showTitles = true }) {
  const [failed, setFailed] = useState(false)
  return <span className="cosmos-validator-identity">
    <span className="cosmos-validator-avatar" aria-hidden="true">{imageSrc && !failed ? <img src={imageSrc} alt="" onError={() => setFailed(true)} /> : initials(moniker)}</span>
    <span className="cosmos-validator"><strong title={showTitles ? moniker : undefined}>{moniker || 'Unknown proposer'}</strong><span className="mono muted" title={showTitles ? address : undefined}>{shortAddress(address)}</span></span>
  </span>
}
