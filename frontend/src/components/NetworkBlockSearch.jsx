import { useEffect, useRef, useState } from 'react'
import { SearchIcon } from './Icons'
import { navigateInternal } from '../utils/navigation'
import { request, searchCosmosValidators } from '../services/api'
import { shortAddress } from '../utils/address'

const TRANSACTION_HASH = /^[0-9A-Fa-f]{64}$/
const BLOCK_HEIGHT = /^[1-9]\d{0,18}$/

export function NetworkBlockSearch({ network, inputRef, formRef }) {
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState('invalid')
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState([])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const requestSequence = useRef(0)
  const currentNetworkId = useRef(network.id)
  currentNetworkId.current = network.id
  const operatorPrefix = `${network.addressPrefixes.validator_operator}1`

  const clear = (blur = false) => {
    requestSequence.current += 1
    setQuery('')
    setMessage('')
    setResults([])
    setDropdownOpen(false)
    setHighlightedIndex(-1)
    if (blur) inputRef.current?.blur()
  }

  useEffect(() => clear(), [network.id])

  useEffect(() => {
    const value = query.trim()
    if (!value || BLOCK_HEIGHT.test(value) || TRANSACTION_HASH.test(value) || value.length > 128) {
      setResults([])
      setDropdownOpen(false)
      setHighlightedIndex(-1)
      return undefined
    }
    const controller = new AbortController()
    const sequence = ++requestSequence.current
    const timer = window.setTimeout(async () => {
      try {
        const response = await searchCosmosValidators({ networkId: network.id, query: value, limit: 6, signal: controller.signal })
        if (sequence !== requestSequence.current) return
        const items = Array.isArray(response?.items) ? response.items.slice(0, 6) : []
        setResults(items)
        setDropdownOpen(true)
        setHighlightedIndex(items.length ? 0 : -1)
        setStatus('invalid')
        setMessage(items.length ? '' : 'No matching validator found.')
      } catch (error) {
        if (error.name === 'AbortError' || sequence !== requestSequence.current) return
        setResults([])
        setDropdownOpen(false)
        setHighlightedIndex(-1)
        setStatus('error')
        setMessage('Search is temporarily unavailable.')
      }
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [network.id, query])

  useEffect(() => {
    const closeOnOutsideClick = (event) => {
      if (!formRef.current?.contains(event.target)) setDropdownOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [formRef])

  const selectValidator = (validator) => {
    clear()
    navigateInternal(`/networks/${network.id}/validators/${encodeURIComponent(validator.operator_address)}`)
  }

  const submit = async (event) => {
    event.preventDefault()
    const value = query.trim()
    if (highlightedIndex >= 0 && dropdownOpen && results[highlightedIndex]) {
      selectValidator(results[highlightedIndex])
      return
    }
    if (BLOCK_HEIGHT.test(value) && BigInt(value) <= 9223372036854775807n) {
      setMessage('')
      navigateInternal(`/networks/${network.id}/blocks/${value}`)
      return
    }
    const networkId = network.id
    setSearching(true)
    try {
      if (TRANSACTION_HASH.test(value)) {
        const transaction = await request(`/networks/${networkId}/transactions/${encodeURIComponent(value)}`)
        if (currentNetworkId.current !== networkId) return
        navigateInternal(`/networks/${networkId}/blocks/${transaction.height}/transactions/${transaction.index}`)
      } else if (value.startsWith(operatorPrefix)) {
        const response = await searchCosmosValidators({ networkId, query: value, limit: 6 })
        if (currentNetworkId.current !== networkId) return
        const validator = response.items.find((item) => item.operator_address === value)
        if (validator) selectValidator(validator)
        else { setStatus('invalid'); setMessage('Validator not found.') }
      } else {
        setStatus('invalid')
        setMessage('Enter a positive block height, transaction hash, or validator.')
      }
    } catch (error) {
      if (currentNetworkId.current !== networkId) return
      setStatus(error.status === 404 ? 'invalid' : 'error')
      setMessage(TRANSACTION_HASH.test(value)
        ? (error.status === 404 ? 'Transaction not found.' : 'Search is temporarily unavailable.')
        : 'Search is temporarily unavailable.')
    } finally {
      if (currentNetworkId.current === networkId) setSearching(false)
    }
  }

  const keyDown = (event) => {
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && results.length) {
      event.preventDefault()
      setDropdownOpen(true)
      setHighlightedIndex((current) => {
        if (current < 0) return event.key === 'ArrowDown' ? 0 : results.length - 1
        return (current + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length
      })
    } else if (event.key === 'Escape') {
      event.preventDefault()
      clear(true)
    }
  }

  return <form ref={formRef} className="global-search" role="search" onSubmit={submit} aria-busy={searching}>
    <label className="search-box"><SearchIcon /><input ref={inputRef} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setMessage('') }} onKeyDown={keyDown} placeholder="Search blocks, transactions, or validators..." aria-label={`Search ${network.presentation.projectName} blocks, transactions, or validators`} aria-expanded={dropdownOpen} aria-controls="cosmos-search-results" aria-activedescendant={highlightedIndex >= 0 ? `cosmos-search-result-${highlightedIndex}` : undefined} autoComplete="off" spellCheck={false} maxLength={128} /><kbd>/</kbd></label>
    {dropdownOpen && results.length > 0 && <div id="cosmos-search-results" className="global-search__results" role="listbox" aria-label="Validator results">
      {results.map((validator, index) => <a id={`cosmos-search-result-${index}`} key={validator.operator_address} className={`global-search__result${highlightedIndex === index ? ' global-search__result--highlighted' : ''}`} href={`/networks/${network.id}/validators/${encodeURIComponent(validator.operator_address)}`} role="option" aria-selected={highlightedIndex === index} onClick={(event) => { event.preventDefault(); selectValidator(validator) }}>
        <strong className="global-search__moniker">{validator.moniker}</strong>
        <span className="global-search__address" title={validator.operator_address}>{shortAddress(validator.operator_address)}</span>
      </a>)}
    </div>}
    {message && <div className={`global-search__network-feedback global-search__feedback--${status}`} aria-live="polite">{message}</div>}
  </form>
}
