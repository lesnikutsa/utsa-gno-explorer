import { useState } from 'react'
import { SearchIcon } from './Icons'
import { navigateInternal } from '../utils/navigation'

export function NetworkBlockSearch({ network, inputRef, formRef }) {
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')
  const submit = (event) => {
    event.preventDefault()
    const value = query.trim()
    if (!/^[1-9]\d{0,18}$/.test(value) || BigInt(value) > 9223372036854775807n) {
      setMessage('Enter a valid positive block height.')
      return
    }
    setMessage('')
    navigateInternal(`/networks/${network.id}/blocks/${value}`)
  }
  return <form ref={formRef} className="global-search" role="search" onSubmit={submit}>
    <label className="search-box"><SearchIcon /><input ref={inputRef} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setMessage('') }} placeholder="Search blocks by height..." aria-label={`Search ${network.presentation.projectName} blocks by height`} inputMode="numeric" autoComplete="off" spellCheck={false} /><kbd>/</kbd></label>
    {message && <div className="global-search__network-feedback global-search__feedback--invalid" aria-live="polite">{message}</div>}
  </form>
}
