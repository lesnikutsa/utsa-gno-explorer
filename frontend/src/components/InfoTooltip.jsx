import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export function InfoTooltip({ label, children, content }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState(null)
  const trigger = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.min(320, window.innerWidth - 20)
      setPosition({ left: Math.max(10, Math.min(window.innerWidth - width - 10, rect.left + rect.width / 2 - width / 2)), top: rect.top - 8, width, transform: 'translateY(-100%)' })
    }
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open])
  const events = { onMouseEnter: () => setOpen(true), onMouseLeave: () => setOpen(false), onFocus: () => setOpen(true), onBlur: () => setOpen(false), onKeyDown: (event) => { if (event.key === 'Escape') { setOpen(false); event.currentTarget.blur() } } }
  const popup = open && position ? createPortal(<span className="info-tooltip__popover" role="tooltip" style={position}>{content}</span>, document.body) : null
  if (children) return <span className="info-tooltip info-tooltip--target"><span ref={trigger} className="info-tooltip__target" tabIndex="0" aria-label={label} {...events}>{children}</span>{popup}</span>
  return <span className="info-tooltip"><button ref={trigger} type="button" aria-label={label} {...events}><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6"/><path d="M8 7v4M8 5h.01"/></svg></button>{popup}</span>
}
