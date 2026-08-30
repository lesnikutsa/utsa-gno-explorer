import { networkProfile } from '../config/networkProfile'

export function UtsaLogo({ logoSrc = '/assets/utsa-logo.png' }) {
  return (
    <div className="brand" aria-label={`UTSA ${networkProfile.projectName} Explorer`}>
      <div className="brand__asset" aria-hidden="true">
        <img src={logoSrc} alt="" />
      </div>
      <strong className="brand__product">{networkProfile.projectName} Explorer</strong>
    </div>
  )
}
