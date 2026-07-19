const safeCount = (value) => {
  const count = Number(value)
  return Number.isFinite(count) ? count : 0
}

export const getMissedBlocks = (uptime = {}) => safeCount(uptime.nil_blocks)
  + safeCount(uptime.absent_blocks)
  + safeCount(uptime.invalid_blocks)

export function getValidatorHealth(uptime = {}) {
  const activeBlocks = safeCount(uptime.active_blocks)
  const missedBlocks = getMissedBlocks(uptime)
  const unknownBlocks = safeCount(uptime.unknown_blocks)

  if (activeBlocks <= 0) return { key: 'no-data', label: 'No data', tone: 'neutral' }
  if (unknownBlocks > 0) return { key: 'unknown', label: 'Unknown', tone: 'neutral' }
  if (missedBlocks === activeBlocks) return { key: 'no-signatures', label: 'No signatures', tone: 'error' }

  const missedRate = missedBlocks / activeBlocks
  if (missedRate >= 0.5) return { key: 'critical', label: 'Critical', tone: 'error' }
  if (missedRate >= 0.1) return { key: 'degraded', label: 'Degraded', tone: 'warning' }
  return { key: 'healthy', label: 'Healthy', tone: 'success' }
}

export function getValidatorMissedBreakdown(uptime = {}) {
  const activeBlocks = safeCount(uptime.active_blocks)
  const signedBlocks = safeCount(uptime.signed_blocks)
  const missedBlocks = getMissedBlocks(uptime)
  const nilBlocks = safeCount(uptime.nil_blocks)
  const absentBlocks = safeCount(uptime.absent_blocks)
  const invalidBlocks = safeCount(uptime.invalid_blocks)
  const unknownBlocks = safeCount(uptime.unknown_blocks)

  return `Active blocks: ${activeBlocks}\nSigned: ${signedBlocks}\nMissed: ${missedBlocks}\nNil: ${nilBlocks}\nAbsent: ${absentBlocks}\nInvalid: ${invalidBlocks}\nUnknown: ${unknownBlocks}`
}

export function formatIntegerString(value) {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  const match = text.match(/^(-?)(\d+)$/)
  if (!match) return text
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`
}
