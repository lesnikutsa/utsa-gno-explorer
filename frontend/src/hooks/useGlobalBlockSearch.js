import { useCallback, useEffect, useRef, useState } from 'react'

import { getBlocks } from '../services/api'

const HEIGHT_PATTERN = /^[1-9]\d*$/
const HEX_HASH_PATTERN = /^(?:0[xX])?[0-9a-fA-F]{64}$/
const BASE64_HASH_PATTERN = /^[A-Za-z0-9+/]{43}=$/

const messages = {
  searching: 'Searching blocks…',
  invalid: 'Enter a block height or exact block hash.',
  notFound: 'No matching block found.',
  error: 'Block search is currently unavailable.',
}

export function useGlobalBlockSearch() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('idle')
  const mounted = useRef(false)
  const requestId = useRef(0)
  const activeQuery = useRef(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      requestId.current += 1
      activeQuery.current = null
    }
  }, [])

  const updateQuery = useCallback((value) => {
    requestId.current += 1
    activeQuery.current = null
    setQuery(value)
    setStatus('idle')
  }, [])

  const clearSearch = useCallback(() => {
    requestId.current += 1
    activeQuery.current = null
    setQuery('')
    setStatus('idle')
  }, [])

  const submitSearch = useCallback(async (event) => {
    event?.preventDefault()
    const trimmedQuery = query.trim()

    if (!trimmedQuery) {
      setStatus('idle')
      return
    }

    if (HEIGHT_PATTERN.test(trimmedQuery)) {
      requestId.current += 1
      activeQuery.current = null
      window.location.assign(`/blocks/${trimmedQuery}`)
      return
    }

    if (!HEX_HASH_PATTERN.test(trimmedQuery) && !BASE64_HASH_PATTERN.test(trimmedQuery)) {
      setStatus('invalid')
      return
    }

    if (activeQuery.current === trimmedQuery) return

    const id = ++requestId.current
    activeQuery.current = trimmedQuery
    setStatus('searching')

    try {
      const response = await getBlocks({ limit: 1, hash: trimmedQuery })
      if (!mounted.current || id !== requestId.current) return
      if (!Array.isArray(response?.items)) throw new Error('Unexpected block search response')

      const block = response.items[0]
      if (!block) {
        setStatus('notFound')
        return
      }

      window.location.assign(`/blocks/${block.height}`)
    } catch {
      if (mounted.current && id === requestId.current) setStatus('error')
    } finally {
      if (mounted.current && id === requestId.current) activeQuery.current = null
    }
  }, [query])

  return {
    query,
    status,
    message: messages[status] ?? '',
    searching: status === 'searching',
    submitSearch,
    updateQuery,
    clearSearch,
  }
}
