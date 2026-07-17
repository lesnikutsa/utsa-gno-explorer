import { UtsaLogo } from './UtsaLogo'
import { StatusBadge } from './StatusBadge'

const items = [
  ['Overview', '⌂'], ['Blocks', '▦'], ['Validators', '◇'], ['Network', '⌁'], ['Peers & Map', '◎'],
]

export function Sidebar({ open, onClose, networkHealthy }) {
  return (
    <>
      <button className={`sidebar-backdrop ${open ? 'is-visible' : ''}`} onClick={onClose} aria-label="Close navigation" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`}>
        <UtsaLogo />
        <nav className="sidebar__nav" aria-label="Explorer navigation">
          <span className="sidebar__label">Explore</span>
          {items.map(([label, icon], index) => (
            <a key={label} className={`nav-item ${index === 0 ? 'is-active' : ''}`} href={index === 0 ? '/' : `#${label.toLowerCase().replaceAll(' ', '-')}`} onClick={onClose}>
              <span className="nav-item__icon" aria-hidden="true">{icon}</span>{label}
            </a>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="chain-select">
            <span className="sidebar__label">Current chain</span>
            <button type="button">Gno.land Testnet 13 <span aria-hidden="true">⌄</span></button>
          </div>
          <div className="rpc-status">
            <div><span className="sidebar__label">RPC Status</span><strong>{networkHealthy === false ? 'Unavailable' : 'Healthy'}</strong></div>
            <StatusBadge tone={networkHealthy === false ? 'error' : 'success'}>{networkHealthy === false ? 'Error' : 'Live'}</StatusBadge>
          </div>
        </div>
      </aside>
    </>
  )
}
