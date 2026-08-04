import { useEffect, useRef, useState } from 'react'

export function ChangedValue({ value, children, className = '' }) {
  const previousValue = useRef(value)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (Object.is(previousValue.current, value)) return
    previousValue.current = value
    setRevision((currentRevision) => currentRevision + 1)
  }, [value])

  const classes = [
    'realms-changed-value',
    revision > 0 ? 'realms-changed-value--active' : '',
    className,
  ].filter(Boolean).join(' ')

  return <span className={classes} key={revision}>{children}</span>
}
