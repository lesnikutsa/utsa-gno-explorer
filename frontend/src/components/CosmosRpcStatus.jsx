import { useEffect, useRef, useState } from 'react'
import { getCosmosEndpointProvider, setCosmosEndpointProvider, subscribeCosmosEndpointProvider } from '../utils/cosmosEndpointProvider'
import '../styles/cosmos-endpoint-mode.css'

const routeNetworkId = () => {
  if (typeof window === 'undefined') return null
  return window.location.pathname.match(/^\/networks\/([a-z0-9]+(?:-[a-z0-9]+)*)/)?.[1] || null
}

const latency = (value) => Number.isInteger(value) ? `${value} ms` : '—'
const height = (value) => Number.isInteger(value) ? `#${value.toLocaleString()}` : '—'
const endpointHealthy = (endpoint) => endpoint?.state === 'healthy'

export function CosmosRpcStatus({ source, pool = [], onDiagnostics, onProviderMode }) {
  const [open, setOpen] = useState(false)
  const [diagnostics, setDiagnostics] = useState(null)
  const [diagnosticsError, setDiagnosticsError] = useState(false)
  const networkId = routeNetworkId()
  const [providerMode, setProviderMode] = useState(() => networkId ? getCosmosEndpointProvider(networkId) : 'auto')
  const root = useRef(null)
  const closeTimer = useRef(null)
  const selected = pool.find((item) => item.selected) || pool.find((item) => item.host === source)
  const providers = diagnostics?.network_id === networkId ? (diagnostics.providers || []) : []
  const preferredRpc = providers.find((item) => item.id === diagnostics?.preferred_rpc_provider_id)
  const preferredApi = providers.find((item) => item.id === diagnostics?.preferred_api_provider_id)
  const statusRpc = providers.find((item) => item.rpc?.host === source) || preferredRpc
  const manualProvider = providers.find((item) => item.id === providerMode)
  const manualHealthy = manualProvider && endpointHealthy(manualProvider.rpc) && endpointHealthy(manualProvider.api)
  const autoHealthy = statusRpc && preferredApi && endpointHealthy(statusRpc.rpc) && endpointHealthy(preferredApi.api)
  const mixedAuto = statusRpc && preferredApi
    ? statusRpc.id !== preferredApi.id
    : Boolean(diagnostics?.mixed_providers)
  const cancelClose = () => { if (closeTimer.current) window.clearTimeout(closeTimer.current) }
  const delayedClose = () => { cancelClose(); closeTimer.current = window.setTimeout(() => setOpen(false), 140) }

  useEffect(() => {
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false) }
    const escape = (event) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { cancelClose(); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])

  useEffect(() => {
    onProviderMode?.(providerMode)
  }, [providerMode, onProviderMode])

  useEffect(() => {
    if (!networkId) return undefined
    const storedMode = getCosmosEndpointProvider(networkId)
    setProviderMode(storedMode)
    setDiagnostics(null)
    onDiagnostics?.(null)
    setDiagnosticsError(false)
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
        if (active) {
          setDiagnostics(data)
          onDiagnostics?.(data)
          setDiagnosticsError(false)
        }
      } catch (error) {
        if (active && error?.name !== 'AbortError') setDiagnosticsError(true)
      } finally {
        window.clearTimeout(timeout)
      }
    }
    load()
    const timer = window.setInterval(load, 30000)
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
  }, [networkId, onDiagnostics])

  useEffect(() => {
    if (!networkId || providerMode === 'auto' || providers.length === 0) return
    if (providers.some((provider) => provider.id === providerMode)) return
    setProviderMode('auto')
    setCosmosEndpointProvider(networkId, 'auto')
  }, [networkId, providerMode, providers])

  const chooseProvider = (providerId) => {
    if (!networkId) return
    setProviderMode(providerId)
    setCosmosEndpointProvider(networkId, providerId)
  }

  if (!source && !diagnostics) return <span className="rpc-pool__compact">RPC status source unavailable</span>

  const compact = providerMode === 'auto'
    ? mixedAuto && statusRpc && preferredApi
      ? <>RPC: <span className="rpc-pool__selected">{statusRpc.label}</span><span>· API:</span><span className="rpc-pool__selected">{preferredApi.label}</span></>
      : <><span>RPC:</span><span className="rpc-pool__selected">{statusRpc?.label || source}</span>{(statusRpc?.rpc?.latency_ms ?? selected?.latency_ms) !== undefined && <span className="rpc-pool__latency">· {latency(statusRpc?.rpc?.latency_ms ?? selected?.latency_ms)}</span>}</>
    : <><span>Manual:</span><span className="rpc-pool__selected">{manualProvider?.label || providerMode}</span><span className="rpc-pool__latency">· RPC + API</span></>

  const triggerHealthy = providerMode === 'auto' ? (diagnostics ? autoHealthy : selected?.state === 'healthy') : manualHealthy

  return <div className="rpc-pool" ref={root} onPointerEnter={(event) => { cancelClose(); if (event.pointerType === 'mouse') setOpen(true) }} onPointerLeave={delayedClose}>
    <button type="button" className={`rpc-pool__trigger rpc-pool__trigger--${triggerHealthy ? 'success' : 'warning'}`} onFocus={() => setOpen(true)} onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="cosmos-rpc-pool" aria-label="RPC and API endpoint mode"><span className="rpc-pool__compact">{compact}</span></button>
    {open && <div className="rpc-pool__popover cosmos-endpoint-mode" id="cosmos-rpc-pool" role="region" aria-label="RPC and API endpoints" onPointerEnter={cancelClose} onPointerLeave={delayedClose}>
      <div className="rpc-pool__heading"><strong>Endpoint mode</strong><span>{providerMode === 'auto' ? 'Automatic bounded failover' : 'Manual RPC + API pair'}</span></div>
      {providers.length > 0 ? <div className="cosmos-endpoint-mode__choices" role="radiogroup" aria-label="Endpoint provider mode">
        <label className={`cosmos-endpoint-mode__choice ${providerMode === 'auto' ? 'is-selected' : ''}`}><input type="radio" name="cosmos-endpoint-provider" value="auto" checked={providerMode === 'auto'} onChange={() => chooseProvider('auto')} /><span><strong>Auto</strong><small>RPC and API may use different providers</small></span></label>
        {providers.map((provider) => <label className={`cosmos-endpoint-mode__choice ${providerMode === provider.id ? 'is-selected' : ''}`} key={provider.id}><input type="radio" name="cosmos-endpoint-provider" value={provider.id} checked={providerMode === provider.id} onChange={() => chooseProvider(provider.id)} /><span><strong>{provider.label}</strong><small>Pin this RPC + API pair</small></span></label>)}
      </div> : <div className="cosmos-endpoint-mode__notice">Provider diagnostics are loading…</div>}

      {providerMode === 'auto' && statusRpc && preferredApi && <div className="cosmos-endpoint-mode__routing"><div><span>RPC</span><strong>{statusRpc.label}</strong><small>{statusRpc.rpc.host} · {latency(statusRpc.rpc.latency_ms)}</small></div><div><span>API</span><strong>{preferredApi.label}</strong><small>{preferredApi.api.host} · {latency(preferredApi.api.latency_ms)}</small></div>{mixedAuto && <p>Auto is currently using different RPC and API providers.</p>}</div>}
      {providerMode !== 'auto' && manualProvider && <div className="cosmos-endpoint-mode__routing"><div><span>RPC</span><strong>{manualProvider.label}</strong><small>{manualProvider.rpc.host} · {endpointHealthy(manualProvider.rpc) ? latency(manualProvider.rpc.latency_ms) : 'Unavailable'}</small></div><div><span>API</span><strong>{manualProvider.label}</strong><small>{manualProvider.api.host} · {endpointHealthy(manualProvider.api) ? latency(manualProvider.api.latency_ms) : 'Unavailable'}</small></div></div>}

      {providers.length > 0 && <><div className="rpc-pool__heading cosmos-endpoint-mode__health-heading"><strong>Provider health</strong><span>{providers.length} configured pairs</span></div><div className="rpc-pool__list">{providers.map((provider) => {
        const reachable = endpointHealthy(provider.rpc) && endpointHealthy(provider.api)
        let marker = ''
        if (providerMode === 'auto') {
          const usesRpc = provider.id === statusRpc?.id
          const usesApi = provider.id === preferredApi?.id
          if (usesRpc && usesApi) marker = 'RPC + API · '
          else if (usesRpc) marker = 'RPC · '
          else if (usesApi) marker = 'API · '
        } else if (provider.id === manualProvider?.id) {
          marker = 'Manual · '
        }
        return <div className="rpc-pool__row cosmos-endpoint-mode__health" key={provider.id}><span className="rpc-pool__host">{provider.label}</span><span className="cosmos-endpoint-mode__height">Height {height(provider.rpc.height)}</span><span className="rpc-pool__latency">RPC {latency(provider.rpc.latency_ms)} · API {latency(provider.api.latency_ms)}</span><span className={`rpc-pool__state rpc-pool__state--${reachable ? 'healthy' : 'degraded'}`}>{marker}{reachable ? 'Healthy' : 'Unavailable'}</span></div>
      })}</div></>}
      {diagnosticsError && <div className="cosmos-endpoint-mode__notice">Endpoint diagnostics are temporarily unavailable.</div>}
    </div>}
  </div>
}
