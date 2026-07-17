import { useEffect, useState } from 'react'
import { MenuIcon, SearchIcon } from './Icons'

const labels = { loading: 'Connecting', healthy: 'Healthy', degraded: 'Degraded', error: 'Unavailable' }

export function TopBar({ onMenuClick, healthState, nextFastRefreshAt }) {
  const [clock, setClock] = useState(Date.now())

  useEffect(() => {
    const intervalId = window.setInterval(() => setClock(Date.now()), 1_000)
    return () => window.clearInterval(intervalId)
  }, [])

  const secondsUntilRefresh = nextFastRefreshAt
    ? Math.min(5, Math.max(0, Math.ceil((nextFastRefreshAt - clock) / 1_000)))
    : 0

  return (
    <header className="topbar">
      <button className="menu-button" onClick={onMenuClick} aria-label="Open navigation"><MenuIcon /></button>
      <label className="search-box">
        <SearchIcon />
        <input type="search" placeholder="Search by height, tx hash, address, validator..." aria-label="Search explorer" />
        <kbd>/</kbd>
      </label>
      <div className="network-update">
        <span className={`pulse pulse--${healthState}`} />
        <div><strong>{labels[healthState]}</strong><span>Next refresh: {secondsUntilRefresh}s</span></div>
      </div>
    </header>
  )
}
