import { UtsaLogo } from './UtsaLogo'
import { BlocksIcon, ChevronDownIcon, HomeIcon, MapIcon, NetworkIcon, ValidatorsIcon } from './Icons'

const items = [
  { label: 'Overview', Icon: HomeIcon, href: '/' },
  { label: 'Blocks', Icon: BlocksIcon, href: '/blocks' },
  { label: 'Validators', Icon: ValidatorsIcon },
  { label: 'Network', Icon: NetworkIcon },
  { label: 'Peers & Map', Icon: MapIcon },
]

export function Sidebar({ open, onClose }) {
  const pathname = window.location.pathname
  const isActive = (href) => {
    if (href === '/') return pathname === '/'
    return pathname === href || pathname.startsWith(`${href}/`)
  }

  return (
    <>
      <button className={`sidebar-backdrop ${open ? 'is-visible' : ''}`} onClick={onClose} aria-label="Close navigation" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`}>
        <UtsaLogo />
        <div className="chain-select">
          <span className="sidebar__label">Current chain</span>
          <button type="button">Gno.land Testnet 13 <ChevronDownIcon /></button>
        </div>
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          {items.map(({ label, Icon, href }) => {
            if (!href) return <span key={label} className="nav-item is-disabled" aria-disabled="true"><Icon />{label}</span>

            const active = isActive(href)
            return <a key={label} className={`nav-item ${active ? 'is-active' : ''}`} href={href} onClick={onClose} aria-current={active ? 'page' : undefined}><Icon />{label}</a>
          })}
        </nav>
      </aside>
    </>
  )
}
