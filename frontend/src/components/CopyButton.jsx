import { useEffect, useRef, useState } from 'react'

import { CheckIcon, CopyIcon } from './Icons'

const RESET_DELAY = 1800

export function CopyButton({ value, label }) {
  const [status, setStatus] = useState('idle')
  const resetTimer = useRef(null)
  const copyRequest = useRef(0)
  const mounted = useRef(false)
  const displayLabel = `${label.charAt(0).toUpperCase()}${label.slice(1)}`

  const clearResetTimer = () => {
    if (resetTimer.current !== null) {
      window.clearTimeout(resetTimer.current)
      resetTimer.current = null
    }
  }

  useEffect(() => {
    mounted.current = true

    return () => {
      mounted.current = false
      copyRequest.current += 1
      clearResetTimer()
    }
  }, [])

  const handleCopy = async () => {
    const requestId = ++copyRequest.current
    clearResetTimer()
    let nextStatus = 'copied'

    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(value)
    } catch {
      nextStatus = 'error'
    }

    if (!mounted.current || requestId !== copyRequest.current) return

    setStatus(nextStatus)
    resetTimer.current = window.setTimeout(() => {
      setStatus('idle')
      resetTimer.current = null
    }, RESET_DELAY)
  }

  const ariaLabel = status === 'copied'
    ? `${displayLabel} copied`
    : status === 'error'
      ? `Failed to copy ${label}`
      : `Copy ${label}`

  return (
    <button
      className={`copy-button${status === 'idle' ? '' : ` copy-button--${status}`}`}
      type="button"
      onClick={handleCopy}
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      {status === 'copied' ? <CheckIcon /> : <CopyIcon />}
      {status === 'error' && <span className="copy-button__error-mark" aria-hidden="true">!</span>}
      <span className="copy-button__feedback sr-only" aria-live="polite">
        {status === 'copied' ? `${displayLabel} copied` : status === 'error' ? `Failed to copy ${label}` : ''}
      </span>
    </button>
  )
}
