import { useEffect, useRef, useState } from 'react'
import { UtsaLogo } from './UtsaLogo'
import { ChainIcon, ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from './Icons'
import { navigationItems } from '../config/navigation'
import { hasNetworkCapability, supportedNetworks } from '../config/networkRegistry'
import { useSelectedNetwork } from '../context/SelectedNetworkContext'
import { isInterceptableNavigation, navigateInternal, usePathname } from '../utils/navigation'

export function Sidebar({ open, onClose, chainId, collapsed, onToggleCollapsed }) {
  const [networkIconFailed, setNetworkIconFailed] = useState(false)
  const [networkMenuOpen, setNetworkMenuOpen] = useState(false)
  const activeNetworkOption = useRef(null)
  const networkSelectorTrigger = useRef(null)
  const { selectedNetwork, selectNetwork } = useSelectedNetwork()
  const networkProfile = selectedNetwork.presentation
  const pathname = usePathname()
  const items = navigationItems.filter(({ capability }) => hasNetworkCapability(selectedNetwork, capability))
  const isTransactionDetail = /^\/blocks\/[^/]+\/transactions\/[^/]+\/?$/.test(pathname)
  const chainLabel = chainId ? `${networkProfile.projectName} · ${chainId}` : `${networkProfile.projectName} network`
  useEffect(() => {
    if (networkMenuOpen) activeNetworkOption.current?.focus()
  }, [networkMenuOpen])

  const closeNetworkMenu = () => {
    setNetworkMenuOpen(false)
    networkSelectorTrigger.current?.focus()
  }
  const handleNetworkKeyDown = (event) => {
    if (event.key === 'Escape') closeNetworkMenu()
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setNetworkMenuOpen(true)
    }
  }
  const handleNetworkSelection = (networkId) => {
    selectNetwork(networkId)
    closeNetworkMenu()
  }
  const isActive = (href) => {
    if (href === '/') return pathname === '/'
    if (href === '/transactions' && isTransactionDetail) return true
    if (href === '/blocks' && isTransactionDetail) return false
    return pathname === href || pathname.startsWith(`${href}/`)
  }
  const handleNavigation = (event, href) => {
    if (!isInterceptableNavigation(event, href, event.currentTarget.target)) return
    event.preventDefault()
    navigateInternal(href)
    onClose()
  }

  return (
    <>
      <button className={`sidebar-backdrop ${open ? 'is-visible' : ''}`} onClick={onClose} aria-label="Close navigation" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`}>
        <UtsaLogo />
        <div className="chain-select">
          <span className="sidebar__label">Current chain</span>
          <button ref={networkSelectorTrigger} type="button" data-sidebar-tooltip={collapsed ? chainLabel : undefined} aria-label={`Select network. Current network: ${chainLabel}`} aria-haspopup="listbox" aria-expanded={networkMenuOpen} aria-controls="network-selector-options" onClick={() => setNetworkMenuOpen((value) => !value)} onKeyDown={handleNetworkKeyDown}>
            <span className="chain-select__compact-icon">
              {networkIconFailed ? (
                <span className="chain-select__network-icon-fallback"><ChainIcon /></span>
              ) : (
                <img
                  className="chain-select__network-icon"
                  src={networkProfile.networkIconSrc}
                  alt=""
                  onError={() => setNetworkIconFailed(true)}
                />
              )}
            </span>
            <span className="chain-select__label">{chainLabel}</span>
            <span className="chain-select__chevron"><ChevronDownIcon /></span>
          </button>
          {networkMenuOpen && (
            <div className="chain-select__options" id="network-selector-options" role="listbox" aria-label="Supported networks" onKeyDown={handleNetworkKeyDown}>
              {supportedNetworks.map((network) => {
                const selected = network.id === selectedNetwork.id
                return <button key={network.id} ref={selected ? activeNetworkOption : undefined} type="button" role="option" aria-selected={selected} onClick={() => handleNetworkSelection(network.id)}>{network.presentation.projectName} · {network.presentation.networkName}</button>
              })}
            </div>
          )}
        </div>
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          {items.map(({ label, Icon, href }) => {
            const active = isActive(href)
            return <a key={label} className={`nav-item ${active ? 'is-active' : ''}`} href={href} onClick={(event) => handleNavigation(event, href)} aria-current={active ? 'page' : undefined} data-sidebar-tooltip={collapsed && !active ? label : undefined}><Icon /><span className="nav-item__label">{label}</span></a>
          })}
        </nav>
        <button
          className="sidebar__toggle"
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          data-sidebar-tooltip={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </button>
      </aside>
    </>
  )
}
