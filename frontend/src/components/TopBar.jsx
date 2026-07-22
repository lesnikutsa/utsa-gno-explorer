import { useEffect, useRef, useState } from 'react'
import { MenuIcon, SearchIcon } from './Icons'
import { useGlobalSearch } from '../hooks/useGlobalSearch'
import { shortAddress } from '../utils/address'

const labels = { loading: 'Connecting', healthy: 'Healthy', degraded: 'Degraded', error: 'Unavailable' }

export function TopBar({ onMenuClick, healthState, nextFastRefreshAt, showRefreshCountdown = true }) {
  const [clock, setClock] = useState(Date.now())
  const searchInputRef = useRef(null)
  const searchFormRef = useRef(null)
  const {
    query, status, message, searching, validatorResults, dropdownOpen, highlightedIndex,
    submitSearch, updateQuery, clearSearch, selectValidator, closeDropdown, moveHighlight,
  } = useGlobalSearch()

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

  useEffect(() => {
    const closeOnOutsideClick = (event) => {
      if (!searchFormRef.current?.contains(event.target)) closeDropdown()
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [closeDropdown])

  const handleSearchKeyDown = (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!validatorResults.length) return
      event.preventDefault()
      moveHighlight(event.key === 'ArrowDown' ? 1 : -1)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      clearSearch()
      event.currentTarget.blur()
    }
  }

  const secondsUntilRefresh = nextFastRefreshAt
    ? Math.min(5, Math.max(0, Math.ceil((nextFastRefreshAt - clock) / 1_000)))
    : 0

  return (
    <header className="topbar">
      <button className="menu-button" onClick={onMenuClick} aria-label="Open navigation"><MenuIcon /></button>
      <form ref={searchFormRef} className="global-search" role="search" onSubmit={submitSearch} aria-busy={searching}>
        <label className="search-box">
          <SearchIcon />
          <input
            ref={searchInputRef}
            type="search"
            value={query}
            onChange={(event) => updateQuery(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search blocks or validators..."
            aria-label="Search by block height, block hash, validator moniker, signing address, or operator address"
            aria-expanded={dropdownOpen}
            aria-controls="global-search-results"
            aria-activedescendant={highlightedIndex >= 0 ? `global-search-result-${highlightedIndex}` : undefined}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>/</kbd>
        </label>
        {dropdownOpen && validatorResults.length > 0 && (
          <div id="global-search-results" className="global-search__results" role="listbox" aria-label="Validator results">
            {validatorResults.map((validator, index) => (
              <a
                id={`global-search-result-${index}`}
                key={validator.address}
                className={`global-search__result${highlightedIndex === index ? ' global-search__result--highlighted' : ''}`}
                href={`/validators/${encodeURIComponent(validator.address)}`}
                role="option"
                aria-selected={highlightedIndex === index}
                onClick={(event) => { event.preventDefault(); selectValidator(validator) }}
              >
                {validator.moniker && <strong className="global-search__moniker">{validator.moniker}</strong>}
                <span className="global-search__address" title={validator.address}>{shortAddress(validator.address)}</span>
                {validator.operator_address && (
                  <span className="global-search__operator" title={validator.operator_address}>
                    Operator: {shortAddress(validator.operator_address)}
                  </span>
                )}
              </a>
            ))}
          </div>
        )}
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
