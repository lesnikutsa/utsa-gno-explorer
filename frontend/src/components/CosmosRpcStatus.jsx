import { useEffect, useMemo, useRef, useState } from 'react'
import { getCosmosEndpointProvider, setCosmosEndpointProvider, subscribeCosmosEndpointProvider } from '../utils/cosmosEndpointProvider'
import '../styles/cosmos-endpoint-mode.css'

const routeNetworkId = () => {
  if (typeof window === 'undefined') return null
  return window.location.pathname.match(/^\/networks\/([a-z0-9]+(?:-[a-z0-9]+)*)/)?.[1] || null
}

const latency = (value) => Number.isInteger(value) ? `${value} ms` : '—'
const endpointHealthy = (endpoint) => endpoint?.state === 'healthy'

export function CosmosRpcStatus({ source, pool = [] }) {
  const [open, setOpen] = useState(false)
  const [diagnostics, setDiagnostics] = useState(null)
  const [diagnosticsError, setDiagnosticsError] = useState(false)
  const networkId = useMemo(routeNetworkId, [])
  const [providerMode, setProviderMode] = useState(() => networkId ? getCosmosEndpointProvider(networkId) : 'auto')
  const root = useRef(null)
  const closeTimer = useRef(null)
  const selected = pool.find((item) => item.selected) || pool.find((item) => item.host === source)
  const providers = diagnostics?.providers || []
  const preferredRpc = providers.find((item) => item.id === diagnostics?.preferred_rpc_provider_id)
  const preferredApi = providers.find((item) => item.id === diagnostics?.preferred_api_provider_id)
  const manualProvider = providers.find((item) => item.id === providerMode)
  const manualHealthy = manualProvider && endpointHealthy(manualProvider.rpc) && endpointHealthy(manualProvider.api)
  const autoHealthy = preferredRpc && preferredApi && endpointHealthy(preferredRpc.rpc) && endpointHealthy(preferredApi.api)
  const cancelClose = () => { if (closeTimer.current) window.clearTimeout(closeTimer.current) }
  const delayedClose = () => { cancelClose(); closeTimer.current = window.setTimeout(() => setOpen(false), 140) }

  useEffect(() => {
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }
    const escape = (event) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { cancelClose(); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])

  useEffect(() => {
    if (!networkId) return undefined
    let active = true
    let controller = null
    const load = async () => {
      if (document.hidden) return
      controller?.abort()
      controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), 10000)
      try {
        const response = await fetch(`/api/networks/${networkId}/endpoint-status`, {
          signal: controller.signal,
          headers: { Accept: 'application/json' },
        })
        if (!response.ok) throw new Error('endpoint status unavailable')
        const data = await response.json()
        if (active) { setDiagnostics(data); setDiagnosticsError(false) }
      } catch (error) {
        if (active && error?.name !== 'AbortError') setDiagnosticsError(true)
      } finally {
        window.clearTimeout(timeout)
      }
    }
    load()
    const timer = window.setInterval(load, 15000)
    const visible = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', visible)
    const unsubscribe = subscribeCosmosEndpointProvider((changedNetworkId) => {
      if (changedNetworkId !== networkId) return
      setProviderMode(getCosmosEndpointProvider(networkId))
    })
    return () => {
      active = false
      controller?.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', visible)
      unsubscribe()
    }
  }, [networkId])

  const chooseProvider = (providerId) => {
    if (!networkId) return
    setProviderMode(providerId)
    setCosmosEndpointProvider(networkId, providerId)
  }

  if (!source && !diagnostics) return <span className="rpc-pool__compact">RPC status source unavailable</span>

  const compact = providerMode === 'auto'
    ? diagnostics?.mixed_providers && preferredRpc && preferredApi
      ? <>RPC: <span className="rpc-pool__selected">{preferredRpc.label}</span><span>· API:</span><span className="rpc-pool__selected">{preferredApi.label}</span></>
      : <><span>RPC:</span><span className="rpc-pool__selected">{preferredRpc?.label || source}</span>{(preferredRpc?.rpc?.latency_ms ?? selected?.latency_ms) !== undefined && <span className="rpc-pool__latency">· {latency(preferredRpc?.rpc?.latency_ms ?? selected?.latency_ms)}</span>}</>
    : <><span>Manual:</span><span className="rpc-pool__selected">{manualProvider?.label || providerMode}</span><span className="rpc-pool__latency">· RPC + API</span></>

  const triggerHealthy = providerMode === 'auto' ? (diagnostics ? autoHealthy : selected?.state === 'healthy') : manualHealthy

  return <div className="rpc-pool" ref={root} onPointerEnter={(event) => { cancelClose(); if (event.pointerType === 'mouse') setOpen(true) }} onPointerLeave={delayedClose}>
    <button type="button" className={`rpc-pool__trigger rpc-pool__trigger--${triggerHealthy ? 'success' : 'warning'}`} onFocus={() => setOpen(true)} onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="cosmos-rpc-pool" aria-label="RPC and API endpoint mode"><span className="rpc-pool__compact">{compact}</span></button>
    {open && <div className="rpc-pool__popover cosmos-endpoint-mode" id="cosmos-rpc-pool" role="region" aria-label="RPC and API endpoints" onPointerEnter={cancelClose} onPointerLeave={delayedClose}>
      <div className="rpc-pool__heading"><strong>Endpoint mode</strong><span>{providerMode === 'auto' ? 'Automatic capability-aware failover' : 'Manual pair · no cross-provider fallback'}</span></div>
      {providers.length > 0 ? <div className="cosmos-endpoint-mode__choices" role="radiogroup" aria-label="Endpoint provider mode">
        <label className={`cosmos-endpoint-mode__choice ${providerMode === 'auto' ? 'is-selected' : ''}`}><input type="radio" name="cosmos-endpoint-provider" value="auto" checked={providerMode === 'auto'} onChange={() => chooseProvider('auto')} /><span><strong>Auto</strong><small>RPC and API may use different healthy providers</small></span></label>
        {providers.map((provider) => <label className={`cosmos-endpoint-mode__choice ${providerMode === provider.id ? 'is-selected' : ''}`} key={provider.id}><input type="radio" name="cosmos-endpoint-provider" value={provider.id} checked={providerMode === provider.id} onChange={() => chooseProvider(provider.id)} /><span><strong>{provider.label}</strong><small>Pin this RPC + API pair</small></span></label>)}
      </div> : <div className="cosmos-endpoint-mode__notice">Provider diagnostics are loading…</div>}

      {providerMode === 'auto' && preferredRpc && preferredApi && <div className="cosmos-endpoint-mode__routing"><div><span>RPC</span><strong>{preferredRpc.label}</strong><small>{preferredRpc.rpc.host} · {latency(preferredRpc.rpc.latency_ms)}</small></div><div><span>API</span><strong>{preferredApi.label}</strong><small>{preferredApi.api.host} · {latency(preferredApi.api.latency_ms)}</small></div>{diagnostics?.mixed_providers && <p>Mixed providers · selected independently by current health and latency.</p>}</div>}
      {providerMode !== 'auto' && manualProvider && <div className="cosmos-endpoint-mode__routing"><div><span>RPC</span><strong>{manualProvider.label}</strong><small>{manualProvider.rpc.host} · {endpointHealthy(manualProvider.rpc) ? latency(manualProvider.rpc.latency_ms) : 'Unavailable'}</small></div><div><span>API</span><strong>{manualProvider.label}</strong><small>{manualProvider.api.host} · {endpointHealthy(manualProvider.api) ? latency(manualProvider.api.latency_ms) : 'Unavailable'}</small></div>{!manualHealthy && <p>Manual mode does not silently switch to another provider.</p>}</div>}

      {providers.length > 0 && <><div className="rpc-pool__heading cosmos-endpoint-mode__health-heading"><strong>Provider health</strong><span>{providers.length} configured pairs</span></div><div className="rpc-pool__list">{providers.map((provider) => {
        const healthy = endpointHealthy(provider.rpc) && endpointHealthy(provider.api)
        return <div className="rpc-pool__row cosmos-endpoint-mode__health" key={provider.id}><span className="rpc-pool__host">{provider.label}</span><span className="rpc-pool__latency">RPC {latency(provider.rpc.latency_ms)} · API {latency(provider.api.latency_ms)}</span><span className={`rpc-pool__state rpc-pool__state--${healthy ? 'healthy' : 'degraded'}`}>{healthy ? 'Healthy' : 'Degraded'}</span></div>
      })}</div></>}
      {diagnosticsError && <div className="cosmos-endpoint-mode__notice">Endpoint diagnostics are temporarily unavailable. Current Explorer data remains usable.</div>}
    </div>}
  </div>
}
