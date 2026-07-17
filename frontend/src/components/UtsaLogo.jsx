export function UtsaLogo({ logoSrc = '/assets/utsa-logo.png' }) {
  return (
    <div className="brand" aria-label="UTSA Gno.land Explorer">
      <div className="brand__asset" aria-hidden="true">
        <img src={logoSrc} alt="" />
      </div>
      <strong className="brand__product">Gno.land Explorer</strong>
    </div>
  )
}
