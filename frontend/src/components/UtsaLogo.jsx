export function UtsaLogo({ logoSrc = null }) {
  return (
    <div className="brand" aria-label="UTSA Gno.land Explorer">
      <div className="brand__asset" aria-hidden="true">
        {logoSrc ? <img src={logoSrc} alt="" /> : <span>Logo</span>}
      </div>
      <div>
        <strong className="brand__name">UTSA</strong>
        <span className="brand__product">Gno.land Explorer</span>
      </div>
    </div>
  )
}
