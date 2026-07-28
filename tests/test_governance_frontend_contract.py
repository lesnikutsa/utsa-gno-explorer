from pathlib import Path
ROOT = Path(__file__).parents[1]
def read(path): return (ROOT / path).read_text()
def test_navigation_and_routes():
    sidebar=read('frontend/src/components/Sidebar.jsx'); app=read('frontend/src/App.jsx')
    assert sidebar.index("label: 'Governance'") > sidebar.index("label: 'Validators'")
    assert 'GovernanceIcon' in sidebar and "href: '/governance'" in sidebar
    assert "path === '/governance'" in app and r'^\/governance\/([^/]+)\/?$' in app
    assert 'isTransactionDetail' in sidebar and "pathname.startsWith(`${href}/`)" in sidebar
def test_api_and_cursor_contract():
    api=read('frontend/src/services/api.js'); hook=read('frontend/src/hooks/useGovernancePage.js')
    assert 'before_proposal_id' in api and 'beforeProposalId !== null' in api
    assert 'export const PAGE_SIZE = 25' in hook and 'next_before_proposal_id' in hook
    assert 'value !== null && value !== undefined' in hook and 'cursorHistory' in hook
def test_list_and_detail_contract():
    page=read('frontend/src/pages/Governance.jsx'); detail=read('frontend/src/pages/GovernanceDetail.jsx')
    for value in ['Total Proposals','Active','Accepted','Rejected','unknown stored status','Proposal','Title','Author','Status','Eligible Tiers','Vote Split','YES','NO','ABSTAIN','Newer proposals','Older proposals']: assert value in page
    for value in ['Back to Governance','Proposal Details','Vote Results','Votes','Voting Power','Stored Snapshot']: assert value in detail
    assert 'CopyButton' in page and 'StatusBadge' in page and 'dangerouslySetInnerHTML' not in detail
    assert "vote.voting_power ?? '—'" in detail
def test_governance_css_geometry_and_responsive_rules():
    css=read('frontend/src/styles/app.css')
    assert 'min-width:1050px;table-layout:fixed' in css
    for width in ['8%','31%','20%','12%','13%','16%']: assert width in css
    assert '@media(max-width:1100px)' in css and '@media(max-width:760px)' in css
    assert 'var(--color-success)' in css and 'var(--color-warning)' in css and 'var(--color-error)' in css
