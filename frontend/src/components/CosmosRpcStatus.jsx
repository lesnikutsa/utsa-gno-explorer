import { useEffect, useRef, useState } from 'react'

export function CosmosRpcStatus({ source, pool = [] }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const closeTimer = useRef(null)
  const selected = pool.find((item) => item.selected) || pool.find((item) => item.host === source)
  const cancelClose = () => { if (closeTimer.current) window.clearTimeout(closeTimer.current) }
  const delayedClose = () => { cancelClose(); closeTimer.current = window.setTimeout(() => setOpen(false), 140) }
  useEffect(() => {
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }
    const escape = (event) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { cancelClose(); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])
  if (!source) return <span className="rpc-pool__compact">RPC status source unavailable</span>
  return <div className="rpc-pool" ref={root} onPointerEnter={(event) => { cancelClose(); if (event.pointerType === 'mouse') setOpen(true) }} onPointerLeave={delayedClose}>
    <button type="button" className={`rpc-pool__trigger rpc-pool__trigger--${selected?.state === 'healthy' ? 'success' : 'warning'}`} onFocus={() => setOpen(true)} onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="cosmos-rpc-pool" aria-label="RPC status source and validated pool"><span className="rpc-pool__compact"><span>RPC:</span><span className="rpc-pool__selected">{source}</span>{selected && <span className="rpc-pool__latency">· {selected.latency_ms} ms</span>}</span></button>
    {open && pool.length > 0 && <div className="rpc-pool__popover" id="cosmos-rpc-pool" role="region" aria-label="RPC endpoints" onPointerEnter={cancelClose} onPointerLeave={delayedClose}><div className="rpc-pool__heading"><strong>RPC endpoints</strong><span>{pool.length} validated · Automatic bounded failover</span></div><div className="rpc-pool__list">{pool.map((item) => <div className="rpc-pool__row" key={item.host}><span className="rpc-pool__host">{item.host}</span><span className="rpc-pool__latency">{item.latency_ms} ms · #{item.height.toLocaleString()}</span><span className={`rpc-pool__state rpc-pool__state--${item.state}`}>{item.selected ? 'Selected · ' : ''}{item.state === 'healthy' ? 'Healthy' : 'Degraded'}</span></div>)}</div></div>}
  </div>
}
