import { StatusBadge } from './StatusBadge'

const executionStatusPresentation = (status) => {
  if (status === 'success') return { label: 'Success', tone: 'success' }
  if (status === 'failed') return { label: 'Failed', tone: 'error' }
  return { label: 'Unavailable', tone: 'neutral' }
}

export function TransactionExecutionBadge({ status }) {
  const { label, tone } = executionStatusPresentation(status)
  return <StatusBadge tone={tone}>{label}</StatusBadge>
}
