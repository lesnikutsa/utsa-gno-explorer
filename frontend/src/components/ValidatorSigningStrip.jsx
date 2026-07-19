import { memo } from 'react'

export const SIGNING_STATUSES = ['commit', 'nil', 'absent', 'invalid', 'unknown', 'not_active']

const STATUS_LABELS = {
  commit: 'Commit',
  nil: 'Nil',
  absent: 'Absent',
  invalid: 'Invalid',
  unknown: 'Unknown',
  not_active: 'Not active',
}

export const getSigningStatusLabel = (status) => STATUS_LABELS[status] ?? STATUS_LABELS.unknown
export const normalizeSigningStatus = (status) => Object.hasOwn(STATUS_LABELS, status) ? status : 'unknown'

const COUNT_LABELS = {
  commit: ['commit', 'commits'],
  nil: ['nil', 'nil'],
  absent: ['absent', 'absent'],
  invalid: ['invalid', 'invalid'],
  unknown: ['unknown', 'unknown'],
  not_active: ['not active', 'not active'],
}

const countLabel = (status, count) => `${count} ${COUNT_LABELS[status][count === 1 ? 0 : 1]}`

function ValidatorSigningStripComponent({ blocks, statuses, compact = false, address }) {
  if (!Array.isArray(blocks) || !Array.isArray(statuses) || blocks.length === 0 || blocks.length !== statuses.length) {
    return <span className="signing-strip__unavailable">History unavailable</span>
  }

  const normalizedStatuses = statuses.map(normalizeSigningStatus)
  const counts = Object.fromEntries(SIGNING_STATUSES.map((status) => [status, 0]))
  normalizedStatuses.forEach((status) => { counts[status] += 1 })
  const summary = SIGNING_STATUSES.filter((status) => counts[status] > 0).map((status) => countLabel(status, counts[status])).join(', ')
  const context = address ? ` for validator ${address}` : ''

  return (
    <span className={`signing-strip ${compact ? 'signing-strip--compact' : ''}`} style={{ '--signing-count': blocks.length }} role="img" aria-label={`Last ${blocks.length} network blocks${context}: ${summary}.`}>
      {normalizedStatuses.map((status, index) => {
        const block = blocks[index]
        const height = block?.height
        const time = block?.time
        const titleParts = [`Block #${height ?? 'unknown'}`, getSigningStatusLabel(status)]
        if (time) titleParts.push(time)
        return <span className={`signing-strip__segment signing-strip__segment--${status}`} title={titleParts.join(' · ')} key={`${height ?? 'unknown'}-${index}`} aria-hidden="true" />
      })}
    </span>
  )
}

export const ValidatorSigningStrip = memo(ValidatorSigningStripComponent)
