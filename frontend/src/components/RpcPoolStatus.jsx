import { useEffect, useRef, useState } from 'react'
import { relativeTime } from '../utils/time'
import { endpointHostname, endpointStatus, hoverPopoverState, normalizeRpcPool, poolSummary, togglePopoverState } from '../utils/rpcPool'

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
  const selectedAria = selectedName
    ? ` Selected endpoint ${selectedName}, ${selected?.latency_ms == null ? 'latency unavailable' : `${selected.latency_ms} milliseconds`}.`
    : ''

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
    return <span className="rpc-meta">RPC: {endpointHostname(selectedRpc.url)}{selectedRpc.latency_ms == null ? '' : ` · ${selectedRpc.latency_ms} ms`}</span>
  }

  return <div className="rpc-pool" ref={rootRef} onPointerEnter={(event) => { cancelClose(); setOpen((value) => hoverPopoverState(value, event.pointerType)) }} onPointerLeave={delayedClose}>
    <button className={`rpc-pool__trigger rpc-pool__trigger--${summary.tone}`} type="button" aria-expanded={open} aria-controls={id} aria-label={`RPC pool: ${pool.available} of ${pool.total} available.${selectedAria}`} onFocus={() => setOpen(true)} onClick={() => setOpen(togglePopoverState)}>
      {selectedName ? <span className="rpc-pool__compact"><span>RPC:</span><span className="rpc-pool__selected">{selectedName}</span><span className="rpc-pool__latency">· {selectedLatency}</span></span> : <span>RPC unavailable</span>}
    </button>
    {open && <div className="rpc-pool__popover" id={id} role="region" aria-label="RPC endpoints" onPointerEnter={cancelClose} onPointerLeave={delayedClose}>
      <div className="rpc-pool__heading"><strong>RPC endpoints</strong><span>{pool.available}/{pool.total} available{pool.last_checked_at ? ` · Checked ${relativeTime(pool.last_checked_at)}` : ''}</span></div>
      <div className="rpc-pool__list">{pool.endpoints.map((endpoint) => <div className="rpc-pool__row" key={endpoint.url}>
        <span className="rpc-pool__host">{endpointHostname(endpoint.url)}</span>
        <span className="rpc-pool__latency">{endpoint.latency_ms == null ? '—' : `${endpoint.latency_ms} ms`}</span>
        <span className={`rpc-pool__state rpc-pool__state--${endpoint.state}`}>{endpoint.selected ? 'Selected · ' : ''}{endpointStatus(endpoint)}</span>
      </div>)}</div>
    </div>}
  </div>
}
