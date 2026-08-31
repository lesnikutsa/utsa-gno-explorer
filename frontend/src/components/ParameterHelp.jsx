import { useEffect, useRef, useState } from 'react'

export function ParameterHelp({ label, children }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  return <span className="parameter-help" ref={root} onPointerEnter={(event) => { if (event.pointerType === 'mouse') setOpen(true) }} onPointerLeave={(event) => { if (event.pointerType === 'mouse') setOpen(false) }}>
    <button type="button" aria-label={`About ${label}`} aria-expanded={open} onFocus={() => setOpen(true)} onClick={() => setOpen((value) => !value)} onKeyDown={(event) => { if (event.key === 'Escape') { setOpen(false); event.currentTarget.blur() } }}>?</button>
    {open && <span className="parameter-help__popover" role="status">{children}</span>}
  </span>
}
