import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatGovernancePercent,
  governanceAuthorValue,
  governanceStatusTone,
  governanceVoteTone,
  isValidGovernanceDetailResponse,
  isValidGovernanceListResponse,
  normalizeVoteWidth,
  parseProposalRouteId,
} from '../src/utils/governance.js'

const listResponse = (ids = [2, 1, 0], cursor = null) => ({
  source: {},
  status_counts: {},
  items: ids.map((proposal_id) => ({ proposal_id })),
  pagination: { next_before_proposal_id: cursor },
})

test('route ID accepts proposal zero', () => assert.equal(parseProposalRouteId('0'), 0))
test('route ID accepts a positive integer', () => assert.equal(parseProposalRouteId('20'), 20))
test('route ID rejects a negative integer', () => assert.equal(parseProposalRouteId('-1'), null))
test('route ID rejects a fraction', () => assert.equal(parseProposalRouteId('1.2'), null))
test('route ID rejects an empty string', () => assert.equal(parseProposalRouteId(''), null))
test('route ID rejects an encoded slash', () => assert.equal(parseProposalRouteId('%2F'), null))
test('route ID rejects malformed percent encoding', () => assert.equal(parseProposalRouteId('%E0%A4%A'), null))
test('route ID rejects an unsafe integer', () => assert.equal(parseProposalRouteId('9007199254740992'), null))

test('ACCEPTED uses success tone', () => assert.equal(governanceStatusTone('ACCEPTED'), 'success'))
test('ACTIVE uses warning tone', () => assert.equal(governanceStatusTone('ACTIVE'), 'warning'))
test('REJECTED uses error tone', () => assert.equal(governanceStatusTone('REJECTED'), 'error'))
test('UNKNOWN uses neutral tone', () => assert.equal(governanceStatusTone('UNKNOWN'), 'neutral'))
test('YES uses success tone', () => assert.equal(governanceVoteTone('YES'), 'success'))
test('NO uses error tone', () => assert.equal(governanceVoteTone('NO'), 'error'))
test('ABSTAIN uses warning tone', () => assert.equal(governanceVoteTone('ABSTAIN'), 'warning'))

test('formats 100 as one-decimal percent', () => assert.equal(formatGovernancePercent(100), '100.0%'))
test('formats null percent as unavailable', () => assert.equal(formatGovernancePercent(null), '—'))
test('formats NaN percent as unavailable', () => assert.equal(formatGovernancePercent(NaN), '—'))
test('formats Infinity percent as unavailable', () => assert.equal(formatGovernancePercent(Infinity), '—'))
test('clamps width below zero', () => assert.equal(normalizeVoteWidth(-1), 0))
test('clamps width above 100', () => assert.equal(normalizeVoteWidth(101), 100))
test('normalizes null width to zero', () => assert.equal(normalizeVoteWidth(null), 0))

test('author address is preferred', () => assert.equal(governanceAuthorValue({ author_address: 'address', author_display: 'display' }), 'address'))
test('author display is the fallback', () => assert.equal(governanceAuthorValue({ author_display: 'display' }), 'display'))
test('list response accepts proposal zero', () => assert.equal(isValidGovernanceListResponse(listResponse()), true))
test('list response rejects duplicate IDs', () => assert.equal(isValidGovernanceListResponse(listResponse([2, 2])), false))
test('list response rejects ascending IDs', () => assert.equal(isValidGovernanceListResponse(listResponse([1, 2])), false))
test('list response accepts cursor zero', () => assert.equal(isValidGovernanceListResponse(listResponse([2, 1], 0)), true))
test('detail response accepts a matching ID', () => assert.equal(isValidGovernanceDetailResponse({ source: {}, proposal: { proposal_id: 0 } }, 0), true))
test('detail response rejects a missing proposal', () => assert.equal(isValidGovernanceDetailResponse({ source: {} }, 0), false))
test('detail response rejects a mismatched proposal', () => assert.equal(isValidGovernanceDetailResponse({ source: {}, proposal: { proposal_id: 1 } }, 0), false))
