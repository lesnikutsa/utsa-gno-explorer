import { useEffect, useRef, useState } from 'react'
import { BlocksIcon, MenuIcon, MoonIcon, SearchIcon, SunIcon } from './Icons'
import { useGlobalSearch } from '../hooks/useGlobalSearch'
import { shortAddress } from '../utils/address'
import { formatAverageBlockTime, normalizeBlockTimeIntervals } from '../utils/blockTime'

const labels = { loading: 'Connecting', healthy: 'Healthy', degraded: 'Degraded', error: 'Unavailable' }

export function TopBar({ onMenuClick, healthState, nextFastRefreshAt, showRefreshCountdown = true, averageBlockTimeSeconds, averageBlockTimeSampleSize, averageBlockTimeIntervalsSeconds, theme, onToggleTheme }) {
  const [clock, setClock] = useState(Date.now())
  const searchInputRef = useRef(null)
  const searchFormRef = useRef(null)
  const previousAverageBlockTime = useRef(null)
  const averageBlockTimeTimer = useRef(null)
  const blockTimeControlRef = useRef(null)
  const blockTimePointerType = useRef(null)
  const [averageBlockTimeUpdating, setAverageBlockTimeUpdating] = useState(false)
  const [blockTimeHistoryOpen, setBlockTimeHistoryOpen] = useState(false)
  const {
    query, status, message, searching, validatorResults, dropdownOpen, highlightedIndex,
    submitSearch, updateQuery, clearSearch, selectValidator, closeDropdown, moveHighlight,
  } = useGlobalSearch()
  const formattedAverageBlockTime = formatAverageBlockTime(averageBlockTimeSeconds)
  const sampleSize = Number(averageBlockTimeSampleSize)
  const showAverageBlockTime = formattedAverageBlockTime !== '—' && Number.isInteger(sampleSize) && sampleSize >= 2
  const intervals = normalizeBlockTimeIntervals(averageBlockTimeIntervalsSeconds)

  useEffect(() => {
    const closeOnOutsideClick = (event) => {
      if (!blockTimeControlRef.current?.contains(event.target)) setBlockTimeHistoryOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [])

  useEffect(() => {
    if (!showAverageBlockTime) {
      previousAverageBlockTime.current = null
      setAverageBlockTimeUpdating(false)
      return undefined
    }
    if (previousAverageBlockTime.current !== null && previousAverageBlockTime.current !== formattedAverageBlockTime) {
      if (averageBlockTimeTimer.current !== null) window.clearTimeout(averageBlockTimeTimer.current)
      setAverageBlockTimeUpdating(true)
      averageBlockTimeTimer.current = window.setTimeout(() => {
        setAverageBlockTimeUpdating(false)
        averageBlockTimeTimer.current = null
      }, 800)
    }
    previousAverageBlockTime.current = formattedAverageBlockTime
    return () => {
      if (averageBlockTimeTimer.current !== null) window.clearTimeout(averageBlockTimeTimer.current)
    }
  }, [formattedAverageBlockTime, showAverageBlockTime])

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
  const hasOpenResults = dropdownOpen && validatorResults.length > 0
  const chartMaximum = intervals.length ? Math.max(...intervals) * 1.1 : 1
  const chartAverage = Number(averageBlockTimeSeconds)
  const averageLineY = 58 - Math.min(chartAverage / chartMaximum, 1) * 48

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
            placeholder="Search blocks, transactions, accounts, or validators..."
            aria-label="Search by block height, block hash, transaction hash, account address, validator moniker, signing address, or operator address"
            aria-expanded={dropdownOpen}
            aria-controls="global-search-results"
            aria-activedescendant={highlightedIndex >= 0 ? `global-search-result-${highlightedIndex}` : undefined}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd>/</kbd>
        </label>
        {hasOpenResults && (
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
        {message && hasOpenResults && (
          <div className="global-search__announcement" aria-live="polite">{message}</div>
        )}
        {message && !hasOpenResults && (
          <div className={`global-search__feedback global-search__feedback--${status}`} aria-live="polite">
            {message}
          </div>
        )}
      </form>
      {showAverageBlockTime && (
        <div
          ref={blockTimeControlRef}
          className="topbar-block-time-control"
          onPointerEnter={(event) => { if (event.pointerType === 'mouse') setBlockTimeHistoryOpen(true) }}
          onPointerLeave={(event) => { if (event.pointerType === 'mouse') setBlockTimeHistoryOpen(false) }}
        >
          <button
            type="button"
            className="topbar-block-time"
            aria-label={`Average block time ${chartAverage} seconds. Show recent block time history.`}
            aria-expanded={blockTimeHistoryOpen}
            aria-controls="block-time-history"
            onPointerDown={(event) => { blockTimePointerType.current = event.pointerType }}
            onClick={() => {
              if (blockTimePointerType.current === 'touch') setBlockTimeHistoryOpen((open) => !open)
              else setBlockTimeHistoryOpen(true)
              blockTimePointerType.current = null
            }}
            onFocus={() => {
              if (blockTimePointerType.current !== 'touch') setBlockTimeHistoryOpen(true)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                setBlockTimeHistoryOpen(false)
                event.currentTarget.blur()
              }
            }}
          >
            <BlocksIcon />
            <span className="topbar-block-time__label">Avg Block Time</span>
            <strong className={averageBlockTimeUpdating ? 'topbar-block-time__value topbar-block-time__value--updating' : 'topbar-block-time__value'}>{formattedAverageBlockTime}</strong>
          </button>
          {blockTimeHistoryOpen && (
            <div id="block-time-history" className="block-time-popover" role="status">
              <strong className="block-time-popover__title">Block time</strong>
              <span className="block-time-popover__subtitle">Last {sampleSize} blocks · {intervals.length} intervals</span>
              {intervals.length ? (
                <>
                  <svg className="block-time-chart" viewBox="0 0 216 64" role="img" aria-label={`Recent block intervals, oldest to newest: ${intervals.join(', ')} seconds`}>
                    {intervals.map((value, index) => {
                      const slotWidth = 216 / intervals.length
                      const height = Math.max(2, (value / chartMaximum) * 48)
                      return <rect key={`${index}-${value}`} x={index * slotWidth + slotWidth * 0.2} y={58 - height} width={slotWidth * 0.6} height={height} rx="1" />
                    })}
                    <line className="block-time-chart__average" x1="0" x2="216" y1={averageLineY} y2={averageLineY} />
                    <text x="214" y={Math.max(8, averageLineY - 3)} textAnchor="end">avg</text>
                  </svg>
                  <div className="block-time-summary">
                    <span>Min <strong>{formatAverageBlockTime(Math.min(...intervals))}</strong></span>
                    <span>Avg <strong>{formattedAverageBlockTime}</strong></span>
                    <span>Max <strong>{formatAverageBlockTime(Math.max(...intervals))}</strong></span>
                  </div>
                </>
              ) : <span className="block-time-popover__empty">Recent interval history unavailable</span>}
            </div>
          )}
        </div>
      )}
      <button
        className="theme-toggle"
        type="button"
        onClick={onToggleTheme}
        aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
        aria-pressed={theme === 'light'}
        title={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
      >
        {theme === 'light' ? <MoonIcon /> : <SunIcon />}
      </button>
      <div className="network-update">
        <span className={`pulse pulse--${healthState}`} />
        <div><strong>{labels[healthState]}</strong>{showRefreshCountdown && <span>Next refresh: {secondsUntilRefresh}s</span>}</div>
      </div>
    </header>
  )
}
