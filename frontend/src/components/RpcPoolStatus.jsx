import { useEffect, useRef, useState } from 'react'
import { relativeTime } from '../utils/time'
import { endpointHostname, endpointStatus, normalizeRpcPool, poolSummary } from '../utils/rpcPool'

export function RpcPoolStatus({ pool: rawPool, selectedRpc }) {
  const pool = normalizeRpcPool(rawPool)
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const closeTimer = useRef(null)
  const id = 'rpc-pool-popover'
  const summary = poolSummary(pool)
  const selected = pool?.endpoints.find((endpoint) => endpoint.selected) || selectedRpc
  const selectedLatency = selected?.latency_ms == null ? '—' : `${selected.latency_ms} ms`
  const selectedName = selected ? endpointHostname(selected.url) : null

  const cancelClose = () => { if (closeTimer.current) window.clearTimeout(closeTimer.current) }
  const delayedClose = () => { cancelClose(); closeTimer.current = window.setTimeout(() => setOpen(false), 140) }

  useEffect(() => {
    const onPointerDown = (event) => { if (!rootRef.current?.contains(event.target)) setOpen(false) }
    const onKeyDown = (event) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => { cancelClose(); document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKeyDown) }
  }, [])

  if (!pool) {
    if (!selectedRpc) return <span className="rpc-meta">RPC unavailable</span>
    return <span className="rpc-meta" title={selectedRpc.url}>RPC: {endpointHostname(selectedRpc.url)}{selectedRpc.latency_ms == null ? '' : ` · ${selectedRpc.latency_ms} ms`}</span>
  }

  return <div className="rpc-pool" ref={rootRef} onPointerEnter={() => { cancelClose(); setOpen(true) }} onPointerLeave={delayedClose}>
    <button className={`rpc-pool__trigger rpc-pool__trigger--${summary.tone}`} type="button" aria-expanded={open} aria-controls={id} aria-label={`RPC pool: ${pool.available} of ${pool.total} available`} onFocus={() => setOpen(true)} onClick={() => setOpen((value) => !value)}>
      <span>RPC pool: {pool.available}/{pool.total} available</span>
      <span className="rpc-pool__selected">{selectedName ? `Selected: ${selectedName} · ${selectedLatency}` : summary.label}</span>
    </button>
    {open && <div className="rpc-pool__popover" id={id} role="region" aria-label="RPC endpoints" onPointerEnter={cancelClose} onPointerLeave={delayedClose}>
      <div className="rpc-pool__heading"><strong>RPC endpoints</strong><span>{pool.available}/{pool.total} available{pool.last_checked_at ? ` · Checked ${relativeTime(pool.last_checked_at)}` : ''}</span></div>
      <div className="rpc-pool__list">{pool.endpoints.map((endpoint) => <div className="rpc-pool__row" key={endpoint.url}>
        <span className="rpc-pool__host" title={endpoint.url}>{endpointHostname(endpoint.url)}</span>
        <span className="rpc-pool__latency">{endpoint.latency_ms == null ? '—' : `${endpoint.latency_ms} ms`}</span>
        <span className={`rpc-pool__state rpc-pool__state--${endpoint.state}`}>{endpoint.selected ? 'Selected · ' : ''}{endpointStatus(endpoint)}</span>
      </div>)}</div>
    </div>}
  </div>
}
