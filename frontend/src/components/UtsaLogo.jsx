export function UtsaLogo({ projectName, logoSrc = '/assets/utsa-logo.png' }) {
  return (
    <div className="brand" aria-label={`UTSA ${projectName} Explorer`}>
      <div className="brand__asset" aria-hidden="true">
        <img src={logoSrc} alt="" />
      </div>
      <strong className="brand__product">{projectName} Explorer</strong>
    </div>
  )
}
