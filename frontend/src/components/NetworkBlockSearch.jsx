import { useState } from 'react'
import { SearchIcon } from './Icons'
import { navigateInternal } from '../utils/navigation'
import { request } from '../services/api'

export function NetworkBlockSearch({ network, inputRef, formRef }) {
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')
  const [searching, setSearching] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    const value = query.trim()
    if (/^[1-9]\d{0,18}$/.test(value) && BigInt(value) <= 9223372036854775807n) {
      setMessage('')
      navigateInternal(`/networks/${network.id}/blocks/${value}`)
      return
    }
    if (!/^[0-9A-Fa-f]{64}$/.test(value)) {
      setMessage('Enter a positive block height or a 64-character transaction hash.')
      return
    }
    setSearching(true)
    try {
      const transaction = await request(`/networks/${network.id}/transactions/${encodeURIComponent(value)}`)
      navigateInternal(`/networks/${network.id}/blocks/${transaction.height}/transactions/${transaction.index}`)
    } catch (error) {
      setMessage(error.status === 404 ? 'Transaction not found.' : 'Transaction search is temporarily unavailable.')
    } finally {
      setSearching(false)
    }
  }
  return <form ref={formRef} className="global-search" role="search" onSubmit={submit} aria-busy={searching}>
    <label className="search-box"><SearchIcon /><input ref={inputRef} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setMessage('') }} placeholder="Search blocks or transactions..." aria-label={`Search ${network.presentation.projectName} blocks or transactions`} autoComplete="off" spellCheck={false} disabled={searching} /><kbd>/</kbd></label>
    {message && <div className="global-search__network-feedback global-search__feedback--invalid" aria-live="polite">{message}</div>}
  </form>
}
