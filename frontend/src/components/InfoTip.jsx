import { useState } from 'react'

export function InfoTip({ children }) {
  const [open, setOpen] = useState(false)
  return <span className="info-tip"><button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} onBlur={() => setOpen(false)} onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false) }}>?</button><span role="tooltip" className={open ? 'is-open' : ''}>{children}</span></span>
}
