import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const page = read('../src/pages/CosmosGovernance.jsx')
const detail = read('../src/pages/CosmosGovernanceDetail.jsx')
const styles = read('../src/styles/cosmos-governance.css')
const detailStyles = read('../src/styles/cosmos-governance-detail.css')
const app = read('../src/App.jsx')

test('Cosmos governance reuses validator summary, tabs and search structure', () => {
  assert.match(page, /cosmos-validator-summary cosmos-governance__summary/)
  assert.match(page, /cosmos-validator-toolbar cosmos-governance__toolbar/)
  assert.match(page, /cosmos-validator-tabs cosmos-governance__tabs/)
  assert.match(page, /Search proposal id, title or type/)
  assert.match(page, /Total proposals/)
  assert.match(page, /Rejected \/ failed/)
})

test('Cosmos governance keeps search compact when the viewport narrows', () => {
  assert.match(styles, /@media \(max-width: 900px\)/)
  const mobileToolbarRule = styles.match(/@media \(max-width: 900px\) \{[\s\S]*?\.cosmos-governance__toolbar \{([^}]*)\}/)?.[1] || ''
  assert.match(mobileToolbarRule, /flex-direction:\s*column;/)
  assert.match(mobileToolbarRule, /align-items:\s*stretch;/)

  const mobileSearchRule = styles.match(/@media \(max-width: 900px\) \{[\s\S]*?\.cosmos-governance__toolbar \.cosmos-validator-search \{([^}]*)\}/)?.[1] || ''
  assert.match(mobileSearchRule, /width:\s*100%;/)
  assert.match(mobileSearchRule, /min-width:\s*0;/)
  assert.match(mobileSearchRule, /height:\s*34px;/)
  assert.match(mobileSearchRule, /flex:\s*0 0 34px;/)
})

test('Cosmos governance table mirrors validator numbering, bounds titles, and links both to proposal detail', () => {
  assert.match(page, /<th>#<\/th><th>Title<\/th><th>Type<\/th><th>Status<\/th><th>Voting end<\/th><th>Vote split<\/th>/)
  assert.match(page, /className="cosmos-governance__proposal-id">\{proposal\.proposal_id\}/)
  assert.match(page, /const detailHref = `\/networks\/\$\{network\.id\}\/governance\/\$\{proposal\.proposal_id\}`/)
  assert.match(page, /className="cosmos-governance__proposal-link" href=\{detailHref\}/)
  assert.match(page, /className="cosmos-governance__title-link" href=\{detailHref\}/)
  assert.match(page, /cosmos-governance__title-tooltip/)
  assert.match(page, /data-tooltip=\{titleTooltip \|\| undefined\}/)
  assert.doesNotMatch(page, /title=\{proposal\.title\}/)
  assert.match(styles, /\.cosmos-governance__proposal-id \{[^}]*min-width: 23px;[^}]*height: 19px;/)

  const titleRule = styles.match(/\.cosmos-governance__title \{([^}]*)\}/)?.[1] || ''
  assert.match(titleRule, /font-size:\s*12px;/)
  assert.match(titleRule, /font-weight:\s*600;/)
  assert.match(titleRule, /overflow:\s*hidden;/)
  assert.match(titleRule, /text-overflow:\s*ellipsis;/)
  assert.match(titleRule, /white-space:\s*nowrap;/)
})

test('Cosmos governance dates are deterministic English UTC rather than browser locale', () => {
  assert.match(page, /const MONTHS = \['Jan', 'Feb', 'Mar'/)
  assert.match(page, /getUTCDate\(\)/)
  assert.match(page, /getUTCHours\(\)/)
  assert.match(page, /UTC`/)
  assert.doesNotMatch(page, /toLocaleDateString\(undefined/)
  assert.match(detail, /const MONTHS = \['Jan', 'Feb', 'Mar'/)
  assert.match(detail, /getUTCSeconds\(\)/)
})

test('Cosmos governance keeps proposal status and readable centered Gno-inspired vote split visualisation', () => {
  assert.match(page, /cosmos-gov-type/)
  assert.match(page, /cosmos-gov-status/)
  assert.match(page, /cosmos-governance-votes__labels/)
  assert.match(page, /cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-governance__table th:nth-child\(6\) \{ text-align: center; \}/)

  const voteLabelsRule = styles.match(/\.cosmos-governance-votes__labels \{([^}]*)\}/)?.[1] || ''
  assert.match(voteLabelsRule, /width:\s*100%;/)
  assert.match(voteLabelsRule, /justify-content:\s*center;/)
  assert.match(voteLabelsRule, /font-size:\s*10px;/)
  assert.match(voteLabelsRule, /font-weight:\s*700;/)
  assert.match(voteLabelsRule, /text-align:\s*center;/)

  assert.match(styles, /\.cosmos-governance-votes__bar/)
  assert.match(styles, /\.cosmos-gov-status--passed/)
})

test('Cosmos governance detail makes vote percentages prominent and the split bar full width', () => {
  assert.match(detail, /<VoteHero tally=\{proposal\.tally\}/)
  assert.match(detail, /cosmos-governance-detail__vote-metrics/)
  assert.match(detail, /result\.percentages\[key\]\.toFixed\(2\)/)
  assert.match(detail, /cosmos-governance-detail__vote-bar/)
  assert.match(detailStyles, /\.cosmos-governance-detail__vote-metric > strong \{[^}]*font-size:\s*clamp\(24px, 2\.5vw, 36px\)/)
  assert.match(detailStyles, /\.cosmos-governance-detail__vote-bar \{[^}]*width:\s*calc\(100% - 32px\);[^}]*height:\s*12px;/)
  assert.match(detailStyles, /\.cosmos-governance-detail__vote-bar \.is-yes \{ background: var\(--color-success\); \}/)
})

test('Cosmos governance detail loads voters only when expanded and never uses native white title tooltips', () => {
  assert.match(detail, /showVoters && <VotersList network=\{network\} proposalId=\{proposal\.proposal_id\}/)
  assert.match(detail, /useCosmosResource\(`\/api\/networks\/\$\{network\.id\}\/governance\/\$\{proposalId\}\/votes`, 0\)/)
  assert.match(detail, /CopyButton value=\{vote\.voter\} label="voter address" showTitle=\{false\}/)
  assert.match(detail, /cosmos-governance-detail__vote-choice/)
  assert.doesNotMatch(detail, /\stitle=/)
})

test('Cosmos governance detail exposes description and collapsible technical data without touching Gno detail', () => {
  assert.match(detail, /Proposal Details/)
  assert.match(detail, /<h2>Description<\/h2>/)
  assert.match(detail, /Technical details/)
  assert.match(detail, /<pre>\{message\.content\}<\/pre>/)
  assert.match(detail, /showTitle=\{false\}/)
})

test('Cosmos governance has list and proposal routes while legacy Gno governance routes stay intact', () => {
  assert.match(app, /blocks\|transactions\|validators\|governance/)
  assert.match(app, /<CosmosGovernance network=\{network\}/)
  assert.match(app, /<CosmosGovernanceDetail network=\{network\} proposalId=\{rawProposalId\}/)
  assert.match(app, /rawProposalId && \(!\/\^\[1-9\]/)
  assert.match(app, /if \(path === '\/governance'/)
  assert.match(app, /<Governance governancePage=\{governancePage\}/)
  assert.match(app, /<GovernanceDetail governanceDetail=\{governanceDetail\}/)
})
