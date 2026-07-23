import { UtsaLogo } from './UtsaLogo'
import { BlocksIcon, ChevronDownIcon, HomeIcon, ValidatorsIcon } from './Icons'
import { networkProfile } from '../config/networkProfile'

const items = [
  { label: 'Overview', Icon: HomeIcon, href: '/' },
  { label: 'Blocks', Icon: BlocksIcon, href: '/blocks' },
  { label: 'Validators', Icon: ValidatorsIcon, href: '/validators' },
]

export function Sidebar({ open, onClose, chainId }) {
  const pathname = window.location.pathname
  const chainLabel = chainId ? `${networkProfile.projectName} · ${chainId}` : `${networkProfile.projectName} network`
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
          <button type="button" title={chainLabel}>{chainLabel} <ChevronDownIcon /></button>
        </div>
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          {items.map(({ label, Icon, href }) => {
            const active = isActive(href)
            return <a key={label} className={`nav-item ${active ? 'is-active' : ''}`} href={href} onClick={onClose} aria-current={active ? 'page' : undefined}><Icon />{label}</a>
          })}
        </nav>
      </aside>
    </>
  )
}
