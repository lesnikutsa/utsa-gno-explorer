export function UtsaLogo() {
  return (
    <div className="brand" aria-label="UTSA Gno.land Explorer">
      <svg className="brand__mark" viewBox="0 0 48 48" aria-hidden="true">
        <path d="M24 3 43 14v20L24 45 5 34V14L24 3Z" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M14 17v9c0 6 4 9 10 9s10-3 10-9v-9M18 17v9c0 3 2 5 6 5s6-2 6-5v-9" fill="none" stroke="currentColor" strokeWidth="2.5" />
        <circle cx="24" cy="11" r="2.5" fill="currentColor" />
      </svg>
      <div>
        <strong className="brand__name">UTSA</strong>
        <span className="brand__product">Gno.land Explorer</span>
      </div>
    </div>
  )
}
