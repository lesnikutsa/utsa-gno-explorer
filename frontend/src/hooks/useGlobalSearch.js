import { useCallback, useEffect, useRef, useState } from 'react'

import { getBlocks, searchValidators } from '../services/api'
import {
  chooseValidatorResult,
  isExactBlockHash,
  isPositiveBlockHeight,
  shouldSearchValidators,
} from '../utils/globalSearch'

const messages = {
  searching: 'Searching…',
  invalid: 'Enter a block height, block hash, validator moniker, or validator address.',
  blockNotFound: 'No matching block found.',
  validatorNotFound: 'No matching validator found.',
  error: 'Search is currently unavailable.',
  select: 'Select a validator from the results.',
}

export function useGlobalSearch() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('idle')
  const [validatorResults, setValidatorResults] = useState([])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const mounted = useRef(false)
  const requestId = useRef(0)
  const resultsQuery = useRef(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      requestId.current += 1
    }
  }, [])

  const applyValidatorResults = useCallback((trimmedQuery, response, id) => {
    if (!mounted.current || id !== requestId.current) return null
    if (!Array.isArray(response?.items)) throw new Error('Unexpected validator search response')
    const items = response.items.slice(0, 6)
    resultsQuery.current = trimmedQuery
    setValidatorResults(items)
    setDropdownOpen(items.length > 0)
    setStatus(items.length ? 'idle' : 'validatorNotFound')
    return items
  }, [])

  useEffect(() => {
    const trimmed = query.trim()
    if (!shouldSearchValidators(trimmed)) return undefined
    const id = ++requestId.current
    const timer = window.setTimeout(async () => {
      setStatus('searching')
      try {
        const response = await searchValidators({ query: trimmed, limit: 6 })
        applyValidatorResults(trimmed, response, id)
      } catch {
        if (mounted.current && id === requestId.current) setStatus('error')
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [applyValidatorResults, query])

  const updateQuery = useCallback((value) => {
    requestId.current += 1
    resultsQuery.current = null
    setQuery(value)
    setStatus('idle')
    setValidatorResults([])
    setDropdownOpen(false)
    setHighlightedIndex(-1)
  }, [])

  const clearSearch = useCallback(() => {
    requestId.current += 1
    resultsQuery.current = null
    setQuery('')
    setStatus('idle')
    setValidatorResults([])
    setDropdownOpen(false)
    setHighlightedIndex(-1)
  }, [])

  const selectValidator = useCallback((validator) => {
    if (!validator?.address) return
    requestId.current += 1
    setDropdownOpen(false)
    window.location.assign(`/validators/${encodeURIComponent(validator.address)}`)
  }, [])

  const closeDropdown = useCallback(() => {
    setDropdownOpen(false)
    setHighlightedIndex(-1)
  }, [])

  const moveHighlight = useCallback((direction) => {
    if (!validatorResults.length) return
    setDropdownOpen(true)
    setHighlightedIndex((current) => {
      if (direction > 0) return current >= validatorResults.length - 1 ? 0 : current + 1
      return current <= 0 ? validatorResults.length - 1 : current - 1
    })
  }, [validatorResults.length])

  const submitSearch = useCallback(async (event) => {
    event?.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return
    if (isPositiveBlockHeight(trimmed)) {
      requestId.current += 1
      window.location.assign(`/blocks/${trimmed}`)
      return
    }
    if (isExactBlockHash(trimmed)) {
      const id = ++requestId.current
      setStatus('searching')
      try {
        const response = await getBlocks({ limit: 1, hash: trimmed })
        if (!mounted.current || id !== requestId.current) return
        if (!Array.isArray(response?.items)) throw new Error('Unexpected block search response')
        const block = response.items[0]
        if (!block) setStatus('blockNotFound')
        else window.location.assign(`/blocks/${block.height}`)
      } catch {
        if (mounted.current && id === requestId.current) setStatus('error')
      }
      return
    }
    if (!shouldSearchValidators(trimmed)) {
      setStatus('invalid')
      return
    }

    let items = resultsQuery.current === trimmed ? validatorResults : null
    if (!items) {
      const id = ++requestId.current
      setStatus('searching')
      try {
        const response = await searchValidators({ query: trimmed, limit: 6 })
        items = applyValidatorResults(trimmed, response, id)
      } catch {
        if (mounted.current && id === requestId.current) setStatus('error')
        return
      }
    }
    if (!items) return
    const selected = chooseValidatorResult(trimmed, items, dropdownOpen ? highlightedIndex : -1)
    if (selected) selectValidator(selected)
    else if (items.length) {
      setDropdownOpen(true)
      setStatus('select')
    } else setStatus('validatorNotFound')
  }, [applyValidatorResults, dropdownOpen, highlightedIndex, query, selectValidator, validatorResults])

  return {
    query, status, message: messages[status] ?? '', searching: status === 'searching',
    validatorResults, dropdownOpen, highlightedIndex, submitSearch, updateQuery,
    clearSearch, selectValidator, closeDropdown, moveHighlight,
  }
}
