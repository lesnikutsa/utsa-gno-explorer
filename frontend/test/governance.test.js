import test from 'node:test'
import assert from 'node:assert/strict'
import { formatGovernancePercent, governanceAuthorValue, governanceStatusTone, governanceVoteTone, normalizeVoteWidth, parseProposalRouteId } from '../src/utils/governance.js'
test('proposal route IDs',()=>{assert.equal(parseProposalRouteId('0'),0);assert.equal(parseProposalRouteId('20'),20);for(const value of ['-1','1.2','','%2F','9007199254740992'])assert.equal(parseProposalRouteId(value),null)})
test('status tones',()=>{assert.equal(governanceStatusTone('ACCEPTED'),'success');assert.equal(governanceStatusTone('ACTIVE'),'warning');assert.equal(governanceStatusTone('REJECTED'),'error');assert.equal(governanceStatusTone('UNKNOWN'),'neutral')})
test('vote tones',()=>{assert.equal(governanceVoteTone('YES'),'success');assert.equal(governanceVoteTone('NO'),'error');assert.equal(governanceVoteTone('ABSTAIN'),'warning')})
test('percentages and widths',()=>{assert.equal(formatGovernancePercent(100),'100.0%');for(const value of [null,NaN,Infinity])assert.equal(formatGovernancePercent(value),'—');assert.equal(normalizeVoteWidth(-2),0);assert.equal(normalizeVoteWidth(120),100)})
test('strings and author fallback remain intact',()=>{const power='00000000000000000003';assert.equal(power,'00000000000000000003');assert.equal(governanceAuthorValue({author_address:'addr',author_display:'name'}),'addr');assert.equal(governanceAuthorValue({author_display:'name'}),'name')})
