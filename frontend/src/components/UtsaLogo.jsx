export function UtsaLogo({ logoSrc = null }) {
  return (
    <div className="brand" aria-label="UTSA Gno.land Explorer">
      <div className="brand__asset" aria-hidden="true">
        {logoSrc ? <img src={logoSrc} alt="" /> : <span>Official UTSA logo</span>}
      </div>
      <strong className="brand__product">Gno.land Explorer</strong>
    </div>
  )
}
