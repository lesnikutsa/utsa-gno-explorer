import { useState } from 'react'
import { shortAddress } from '../utils/address'

const initials = (moniker) => (moniker || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || '?'

export function CosmosValidatorIdentity({ moniker, address, imageSrc, showTitles = true, href }) {
  const [failed, setFailed] = useState(false)
  const content = <span className="cosmos-validator-identity">
    <span className="cosmos-validator-avatar" aria-hidden="true">{imageSrc && !failed ? <img src={imageSrc} alt="" onError={() => setFailed(true)} /> : initials(moniker)}</span>
    <span className="cosmos-validator"><strong title={showTitles && !href ? moniker : undefined}>{moniker || 'Unknown proposer'}</strong><span className="mono muted" title={showTitles && !href ? address : undefined}>{shortAddress(address)}</span></span>
  </span>
  return href ? <a className="cosmos-validator-identity-link" href={href}>{content}</a> : content
}
