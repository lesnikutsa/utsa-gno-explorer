import { useEffect, useRef, useState } from 'react'
import { MenuIcon, SearchIcon } from './Icons'
import { useGlobalBlockSearch } from '../hooks/useGlobalBlockSearch'

const labels = { loading: 'Connecting', healthy: 'Healthy', degraded: 'Degraded', error: 'Unavailable' }

export function TopBar({ onMenuClick, healthState, nextFastRefreshAt, showRefreshCountdown = true }) {
  const [clock, setClock] = useState(Date.now())
  const searchInputRef = useRef(null)
  const { query, status, message, searching, submitSearch, updateQuery, clearSearch } = useGlobalBlockSearch()

  useEffect(() => {
    if (!showRefreshCountdown) return undefined
    const intervalId = window.setInterval(() => setClock(Date.now()), 1_000)
    return () => window.clearInterval(intervalId)
  }, [showRefreshCountdown])

  useEffect(() => {
    const focusGlobalSearch = (event) => {
      const target = event.target
      const tagName = target?.tagName?.toLowerCase()
      const isEditing = ['input', 'textarea', 'select'].includes(tagName)
        || target?.isContentEditable
        || target?.closest?.('[contenteditable="true"]')

      if (event.key !== '/' || event.ctrlKey || event.altKey || event.metaKey || isEditing) return
      event.preventDefault()
      searchInputRef.current?.focus()
      searchInputRef.current?.select()
    }

    window.addEventListener('keydown', focusGlobalSearch)
    return () => window.removeEventListener('keydown', focusGlobalSearch)
  }, [])

  const handleSearchKeyDown = (event) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    clearSearch()
    event.currentTarget.blur()
  }

  const secondsUntilRefresh = nextFastRefreshAt
    ? Math.min(5, Math.max(0, Math.ceil((nextFastRefreshAt - clock) / 1_000)))
    : 0

  return (
    <header className="topbar">
      <button className="menu-button" onClick={onMenuClick} aria-label="Open navigation"><MenuIcon /></button>
      <form className="global-search" role="search" onSubmit={submitSearch} aria-busy={searching}>
        <label className="search-box">
          <SearchIcon />
          <input
            ref={searchInputRef}
            type="search"
            value={query}
            onChange={(event) => updateQuery(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search by block height or hash..."
            aria-label="Search blocks by height or hash"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>/</kbd>
        </label>
        {message && (
          <div className={`global-search__feedback global-search__feedback--${status}`} aria-live="polite">
            {message}
          </div>
        )}
      </form>
      <div className="network-update">
        <span className={`pulse pulse--${healthState}`} />
        <div><strong>{labels[healthState]}</strong>{showRefreshCountdown && <span>Next refresh: {secondsUntilRefresh}s</span>}</div>
      </div>
    </header>
  )
}
