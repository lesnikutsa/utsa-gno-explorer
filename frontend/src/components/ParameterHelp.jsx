import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export function ParameterHelp({ label, children }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState(null)
  const root = useRef(null)
  const button = useRef(null)
  const pointerType = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const place = () => {
      const rect = button.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.min(240, window.innerWidth - 20)
      const left = Math.max(10, Math.min(window.innerWidth - width - 10, rect.left + rect.width / 2 - width / 2))
      const above = rect.top >= 100
      setPosition({ left, top: above ? rect.top - 8 : rect.bottom + 8, width, transform: above ? 'translateY(-100%)' : 'none' })
    }
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }
    place(); document.addEventListener('pointerdown', outside); window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open])
  const popover = open && position ? createPortal(<span className="parameter-help__popover" style={position} role="tooltip">{children}</span>, document.body) : null
  return <span className="parameter-help" ref={root} onPointerEnter={(event) => { if (event.pointerType === 'mouse') setOpen(true) }} onPointerLeave={(event) => { if (event.pointerType === 'mouse') setOpen(false) }}>
    <button ref={button} type="button" aria-label={`About ${label}`} aria-expanded={open} onPointerDown={(event) => { pointerType.current = event.pointerType }} onFocus={() => { if (pointerType.current !== 'touch') setOpen(true) }} onBlur={() => setOpen(false)} onClick={() => { if (pointerType.current === 'touch') setOpen((value) => !value); else setOpen(true); pointerType.current = null }} onKeyDown={(event) => { if (event.key === 'Escape') { setOpen(false); event.currentTarget.blur() } }}>?</button>{popover}
  </span>
}
