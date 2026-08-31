import { useEffect, useRef, useState } from 'react'
import { UtsaLogo } from './UtsaLogo'
import { ChainIcon, ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from './Icons'
import { navigationItems } from '../config/navigation'
import { hasNetworkCapability } from '../config/networkRegistry'
import { useSelectedNetwork } from '../context/SelectedNetworkContext'
import { isInterceptableNavigation, navigateInternal, usePathname } from '../utils/navigation'
import { adjacentOptionIndex } from '../utils/networkSelector'

export function Sidebar({ open, onClose, chainId, collapsed, onToggleCollapsed }) {
  const [networkIconFailed, setNetworkIconFailed] = useState(false)
  const [networkMenuOpen, setNetworkMenuOpen] = useState(false)
  const [focusedNetworkIndex, setFocusedNetworkIndex] = useState(0)
  const networkOptions = useRef([])
  const networkSelectorTrigger = useRef(null)
  const networkSelector = useRef(null)
  const previousSidebarOpen = useRef(open)
  const { selectedNetwork, selectNetwork, supportedNetworks } = useSelectedNetwork()
  const networkProfile = selectedNetwork.presentation
  const pathname = usePathname()
  const items = navigationItems.filter(({ capability }) => hasNetworkCapability(selectedNetwork, capability))
  const networkHref = (href) => selectedNetwork.family === 'cosmos'
    ? `/networks/${selectedNetwork.id}${href === '/' ? '' : href}` : href
  const isTransactionDetail = /^\/blocks\/[^/]+\/transactions\/[^/]+\/?$/.test(pathname)
  const chainLabel = chainId ? `${networkProfile.projectName} · ${chainId}` : `${networkProfile.projectName} network`
  useEffect(() => {
    if (networkMenuOpen) networkOptions.current[focusedNetworkIndex]?.focus()
  }, [focusedNetworkIndex, networkMenuOpen])

  useEffect(() => {
    setNetworkIconFailed(false)
  }, [selectedNetwork.id, networkProfile.networkIconSrc])

  useEffect(() => {
    if (!networkMenuOpen) return undefined
    const handleOutsidePointerDown = (event) => {
      if (!networkSelector.current?.contains(event.target)) setNetworkMenuOpen(false)
    }
    document.addEventListener('pointerdown', handleOutsidePointerDown)
    return () => document.removeEventListener('pointerdown', handleOutsidePointerDown)
  }, [networkMenuOpen])

  useEffect(() => {
    if (previousSidebarOpen.current && !open) setNetworkMenuOpen(false)
    previousSidebarOpen.current = open
  }, [open])

  const closeNetworkMenu = ({ restoreFocus = true } = {}) => {
    setNetworkMenuOpen(false)
    if (restoreFocus) networkSelectorTrigger.current?.focus()
  }
  const selectedNetworkIndex = Math.max(0, supportedNetworks.findIndex(({ id }) => id === selectedNetwork.id))
  const openNetworkMenu = () => {
    setFocusedNetworkIndex(selectedNetworkIndex)
    setNetworkMenuOpen(true)
  }
  const handleNetworkTriggerKeyDown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      openNetworkMenu()
    }
  }
  const handleNetworkOptionsKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeNetworkMenu()
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setFocusedNetworkIndex((current) => adjacentOptionIndex(
        current,
        supportedNetworks.length,
        event.key === 'ArrowUp' ? 'previous' : 'next',
      ))
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      const focusedNetwork = supportedNetworks[focusedNetworkIndex]
      if (focusedNetwork) handleNetworkSelection(focusedNetwork.id)
    }
  }
  const handleNetworkSelection = (networkId) => {
    selectNetwork(networkId)
    closeNetworkMenu()
    navigateInternal(networkId === 'gno-pearl' ? '/' : `/networks/${networkId}`)
  }
  const isActive = (href) => {
    if (href === '/') return pathname === '/'
    if (selectedNetwork.family === 'cosmos' && href === `/networks/${selectedNetwork.id}`) {
      return pathname === href || pathname === `${href}/`
    }
    if (href === '/transactions' && isTransactionDetail) return true
    if (href === '/blocks' && isTransactionDetail) return false
    return pathname === href || pathname.startsWith(`${href}/`)
  }
  const handleNavigation = (event, href) => {
    closeNetworkMenu({ restoreFocus: false })
    if (!isInterceptableNavigation(event, href, event.currentTarget.target)) return
    event.preventDefault()
    navigateInternal(href)
    onClose()
  }
  const handleSidebarClose = () => {
    closeNetworkMenu({ restoreFocus: false })
    onClose()
  }

  return (
    <>
      <button className={`sidebar-backdrop ${open ? 'is-visible' : ''}`} onClick={handleSidebarClose} aria-label="Close navigation" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`}>
        <UtsaLogo projectName={networkProfile.projectName} />
        <div className="chain-select" ref={networkSelector}>
          <span className="sidebar__label">Current chain</span>
          <button ref={networkSelectorTrigger} type="button" data-sidebar-tooltip={collapsed ? chainLabel : undefined} aria-label={`Select network. Current network: ${chainLabel}`} aria-haspopup="listbox" aria-expanded={networkMenuOpen} aria-controls="network-selector-options" onClick={() => networkMenuOpen ? closeNetworkMenu() : openNetworkMenu()} onKeyDown={handleNetworkTriggerKeyDown}>
            <span className="chain-select__network-identity">
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
            <div className="chain-select__options" id="network-selector-options" role="listbox" aria-label="Supported networks" onKeyDown={handleNetworkOptionsKeyDown}>
              {supportedNetworks.map((network, index) => {
                const selected = network.id === selectedNetwork.id
                return <button key={network.id} ref={(option) => { networkOptions.current[index] = option }} type="button" role="option" aria-selected={selected} tabIndex={focusedNetworkIndex === index ? 0 : -1} onFocus={() => setFocusedNetworkIndex(index)} onClick={() => handleNetworkSelection(network.id)}>{network.presentation.projectName} · {network.presentation.networkName}</button>
              })}
            </div>
          )}
        </div>
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          {items.map(({ label, Icon, href: itemHref }) => {
            const href = networkHref(itemHref)
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
