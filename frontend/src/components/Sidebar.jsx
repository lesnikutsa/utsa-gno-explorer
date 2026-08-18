import { useState } from 'react'
import { UtsaLogo } from './UtsaLogo'
import { BlocksIcon, ChainIcon, ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, GovernanceIcon, HomeIcon, RealmsIcon, TokensIcon, TransactionsIcon, ValidatorsIcon } from './Icons'
import { networkProfile } from '../config/networkProfile'
import { isInterceptableNavigation, navigateInternal, usePathname } from '../utils/navigation'

const items = [
  { label: 'Overview', Icon: HomeIcon, href: '/' },
  { label: 'Blocks', Icon: BlocksIcon, href: '/blocks' },
  { label: 'Transactions', Icon: TransactionsIcon, href: '/transactions' },
  { label: 'Realms', Icon: RealmsIcon, href: '/realms' },
  { label: 'Tokens', Icon: TokensIcon, href: '/tokens' },
  { label: 'Validators', Icon: ValidatorsIcon, href: '/validators' },
  { label: 'Governance', Icon: GovernanceIcon, href: '/governance' },
]

export function Sidebar({ open, onClose, chainId, collapsed, onToggleCollapsed }) {
  const [networkIconFailed, setNetworkIconFailed] = useState(false)
  const pathname = usePathname()
  const isTransactionDetail = /^\/blocks\/[^/]+\/transactions\/[^/]+\/?$/.test(pathname)
  const chainLabel = chainId ? `${networkProfile.projectName} · ${chainId}` : `${networkProfile.projectName} network`
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
          <button type="button" data-sidebar-tooltip={collapsed ? chainLabel : undefined} aria-label={`Current chain: ${chainLabel}`}>
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
