import { useCallback, useEffect, useRef, useState } from 'react'
import { getTokens } from '../services/api'

export function useTokensPage() {
  const [items, setItems] = useState([])
  const [summary, setSummary] = useState(null)
  const [searchInput, setSearchInput] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [healthState, setHealthState] = useState('loading')
  const controller = useRef(null)
  const load = useCallback(async (q = '') => {
    controller.current?.abort()
    controller.current = new AbortController()
    setLoading(true); setError(false)
    try {
      const response = await getTokens({ q, signal: controller.current.signal })
      setItems(response.items ?? []); setSummary(response.summary ?? null); setHealthState('healthy')
    } catch (requestError) {
      if (requestError?.name !== 'AbortError') { setItems([]); setError(true); setHealthState('error') }
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load(); return () => controller.current?.abort() }, [load])
  const submitSearch = useCallback((event) => {
    event.preventDefault(); const query = searchInput.trim(); setSearchInput(query); setAppliedSearch(query); load(query)
  }, [load, searchInput])
  const clearSearch = useCallback(() => { setSearchInput(''); setAppliedSearch(''); load() }, [load])
  return { items, summary, searchInput, appliedSearch, loading, error, healthState,
    setSearchInput, submitSearch, clearSearch, retry: () => load(appliedSearch) }
}
