export const governanceStatusTone = (status) => ({ ACCEPTED: 'success', ACTIVE: 'warning', REJECTED: 'error' })[status] ?? 'neutral'
export const governanceVoteTone = (option) => ({ YES: 'success', NO: 'error', ABSTAIN: 'warning' })[option] ?? 'neutral'

export function formatGovernancePercent(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : '—'
}

export function normalizeVoteWidth(value) {
  const number = Number(value)
  return value === null || value === '' || !Number.isFinite(number) ? 0 : Math.min(100, Math.max(0, number))
}

export function parseProposalRouteId(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 20) return null
  let decoded
  try { decoded = decodeURIComponent(value) } catch { return null }
  if (!/^\d+$/.test(decoded)) return null
  const proposalId = Number(decoded)
  return Number.isSafeInteger(proposalId) && proposalId >= 0 ? proposalId : null
}

export const governanceAuthorValue = (item) => item?.author_address || item?.author_display || ''
