import { StatusBadge } from './StatusBadge'

const decodeStatusPresentation = (status) => {
  if (status === 'decoded') return { label: 'Decoded', tone: 'neutral' }
  if (status === 'invalid_base64') return { label: 'Invalid Base64', tone: 'error' }
  if (status === 'not_attempted') return { label: 'Not Attempted', tone: 'neutral' }
  return { label: String(status), tone: 'neutral' }
}

export function TransactionDecodeBadge({ status }) {
  const { label, tone } = decodeStatusPresentation(status)

  return (
    <span aria-label={`Base64 decode status: ${label}. This is not transaction execution status.`}>
      <StatusBadge tone={tone}>{label}</StatusBadge>
    </span>
  )
}
