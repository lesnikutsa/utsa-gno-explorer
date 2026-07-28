const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

export const governanceStatusTone = (status) => ({
  ACCEPTED: 'success',
  ACTIVE: 'warning',
  REJECTED: 'error',
})[status] ?? 'neutral'

export const governanceVoteTone = (option) => ({
  YES: 'success',
  NO: 'error',
  ABSTAIN: 'warning',
})[option] ?? 'neutral'

export function formatGovernancePercent(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : '—'
}

export function normalizeVoteWidth(value) {
  if (value === null || value === undefined || value === '') return 0
  const number = Number(value)
  return Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : 0
}

export function parseProposalRouteId(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 20) return null

  let decoded
  try {
    decoded = decodeURIComponent(value)
  } catch {
    return null
  }

  if (!/^\d+$/.test(decoded)) return null
  const proposalId = Number(decoded)
  return Number.isSafeInteger(proposalId) && proposalId >= 0 ? proposalId : null
}

export const governanceAuthorValue = (item) => item?.author_address || item?.author_display || ''

export function isValidGovernanceListResponse(response) {
  if (!isObject(response)
    || !isObject(response.source)
    || !isObject(response.status_counts)
    || !Array.isArray(response.items)
    || !isObject(response.pagination)) return false

  const cursor = response.pagination.next_before_proposal_id
  if (cursor !== null && (!Number.isSafeInteger(cursor) || cursor < 0)) return false

  const ids = response.items.map((item) => item?.proposal_id)
  if (ids.some((id) => !Number.isSafeInteger(id) || id < 0)) return false
  if (new Set(ids).size !== ids.length) return false
  return ids.every((id, index) => index === 0 || ids[index - 1] > id)
}

export function isValidGovernanceDetailResponse(response, proposalId) {
  return isObject(response)
    && isObject(response.source)
    && isObject(response.proposal)
    && response.proposal.proposal_id === proposalId
}
