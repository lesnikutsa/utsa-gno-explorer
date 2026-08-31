import { useEffect, useRef, useState } from 'react'

export function CosmosRpcStatus({ source, pool = [] }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const selected = pool.find((item) => item.selected) || pool.find((item) => item.host === source)
  useEffect(() => { if (!open) return undefined; const close = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }; document.addEventListener('pointerdown', close); return () => document.removeEventListener('pointerdown', close) }, [open])
  if (!source) return <span className="rpc-pool__compact">RPC status source unavailable</span>
  return <span className="rpc-pool" ref={root}><button type="button" className={`rpc-pool__trigger rpc-pool__trigger--${selected?.state === 'healthy' ? 'success' : 'warning'}`} onClick={() => setOpen((value) => !value)} onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false) }} aria-expanded={open} aria-label="Show RPC status pool"><span className="rpc-pool__compact"><span className="rpc-pool__selected">RPC: {source}</span>{selected && <span>· {selected.latency_ms} ms</span>}</span></button>{open && pool.length > 0 && <span className="rpc-pool__popover"><span className="rpc-pool__heading"><strong>RPC pool</strong><span>Automatic bounded failover</span></span><span className="rpc-pool__list">{pool.map((item) => <span className="rpc-pool__row" key={item.host}><span className="rpc-pool__host">{item.host}</span><span className="rpc-pool__latency">{item.latency_ms} ms</span><span className={`rpc-pool__state rpc-pool__state--${item.state}`}>#{item.height.toLocaleString()}{item.selected ? ' · status source' : ''}</span></span>)}</span></span>}</span>
}
