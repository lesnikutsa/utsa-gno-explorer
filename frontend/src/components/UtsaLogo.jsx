import { networkProfile } from '../config/networkProfile'

export function UtsaLogo({ logoSrc = '/assets/utsa-logo.png', profile = networkProfile }) {
  return (
    <div className="brand" aria-label={`UTSA ${profile.projectName} Explorer`}>
      <div className="brand__asset" aria-hidden="true">
        <img src={logoSrc} alt="" />
      </div>
      <strong className="brand__product">{profile.projectName} Explorer</strong>
    </div>
  )
}
