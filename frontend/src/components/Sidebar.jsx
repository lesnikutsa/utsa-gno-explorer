import { UtsaLogo } from './UtsaLogo'
import { BlocksIcon, ChainIcon, ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, GovernanceIcon, HomeIcon, TransactionsIcon, ValidatorsIcon } from './Icons'
import { networkProfile } from '../config/networkProfile'

const items = [
  { label: 'Overview', Icon: HomeIcon, href: '/' },
  { label: 'Blocks', Icon: BlocksIcon, href: '/blocks' },
  { label: 'Transactions', Icon: TransactionsIcon, href: '/transactions' },
  { label: 'Validators', Icon: ValidatorsIcon, href: '/validators' },
  { label: 'Governance', Icon: GovernanceIcon, href: '/governance' },
]

export function Sidebar({ open, onClose, chainId, collapsed, onToggleCollapsed }) {
  const pathname = window.location.pathname
  const isTransactionDetail = /^\/blocks\/[^/]+\/transactions\/[^/]+\/?$/.test(pathname)
  const chainLabel = chainId ? `${networkProfile.projectName} · ${chainId}` : `${networkProfile.projectName} network`
  const isActive = (href) => {
    if (href === '/') return pathname === '/'
    if (href === '/transactions' && isTransactionDetail) return true
    if (href === '/blocks' && isTransactionDetail) return false
    return pathname === href || pathname.startsWith(`${href}/`)
  }

  return (
    <>
      <button className={`sidebar-backdrop ${open ? 'is-visible' : ''}`} onClick={onClose} aria-label="Close navigation" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`}>
        <UtsaLogo />
        <div className="chain-select">
          <span className="sidebar__label">Current chain</span>
          <button type="button" title={chainLabel} aria-label={`Current chain: ${chainLabel}`}>
            <span className="chain-select__compact-icon"><ChainIcon /></span>
            <span className="chain-select__label">{chainLabel}</span>
            <span className="chain-select__chevron"><ChevronDownIcon /></span>
          </button>
        </div>
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          {items.map(({ label, Icon, href }) => {
            const active = isActive(href)
            return <a key={label} className={`nav-item ${active ? 'is-active' : ''}`} href={href} onClick={onClose} aria-current={active ? 'page' : undefined} title={collapsed ? label : undefined}><Icon /><span className="nav-item__label">{label}</span></a>
          })}
        </nav>
        <button
          className="sidebar__toggle"
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </button>
      </aside>
    </>
  )
}
