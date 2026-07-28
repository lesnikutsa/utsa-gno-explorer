import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path):
    return (ROOT / path).read_text()


class TestGovernanceNavigation:
    sidebar = read('frontend/src/components/Sidebar.jsx')
    app = read('frontend/src/App.jsx')

    def test_navigation_order_and_icon(self):
        assert self.sidebar.index("label: 'Governance'") > self.sidebar.index("label: 'Validators'")
        assert 'GovernanceIcon' in self.sidebar

    def test_list_and_detail_routes(self):
        assert "path === '/governance'" in self.app
        assert r'^\/governance\/([^/]+)\/?$' in self.app

    def test_nested_active_and_transaction_special_case_remain(self):
        assert "pathname.startsWith(`${href}/`)" in self.sidebar
        assert 'isTransactionDetail' in self.sidebar
        assert "href === '/transactions' && isTransactionDetail" in self.sidebar

    def test_existing_routes_remain(self):
        for route in ['/blocks', '/transactions', '/validators']:
            assert f"path === '{route}'" in self.app


class TestGovernanceApiAndHooks:
    api = read('frontend/src/services/api.js')
    listing = read('frontend/src/hooks/useGovernancePage.js')
    detail = read('frontend/src/hooks/useGovernanceDetail.js')

    def test_polling_intervals_use_timeouts_only(self):
        assert 'GOVERNANCE_LIST_POLL_MS = 30_000' in self.listing
        assert 'GOVERNANCE_DETAIL_POLL_MS = 15_000' in self.detail
        assert 'window.setTimeout' in self.listing
        assert 'window.setTimeout' in self.detail
        assert 'setInterval' not in self.listing + self.detail

    def test_list_polling_is_latest_page_only_and_non_overlapping(self):
        assert 'pageIndexRef.current !== 0' in self.listing
        assert 'hasLoadedData.current' in self.listing
        assert 'inFlight.current' in self.listing
        background = self.listing[self.listing.index('const refreshInBackground'):]
        assert 'clearPublicData()' not in background.split('const retry', 1)[0]
        for update in ['setProposals(', 'setSource(', 'setStatusCounts(', 'setNextCursor(']:
            assert update in background
        assert "setHealthState('degraded')" in background

    def test_detail_polling_preserves_data_and_stops_for_terminal_status(self):
        assert 'isMutableGovernanceStatus(storedProposal.current.status)' in self.detail
        assert 'inFlight.current' in self.detail
        background = self.detail[self.detail.index('const refreshInBackground'):]
        assert 'setState((current) => ({ ...current, healthState: \'degraded\' }))' in background
        assert 'storedProposal.current = response.proposal' in background

    def test_visibility_and_unmount_cleanup(self):
        for hook in [self.listing, self.detail]:
            assert "document.addEventListener('visibilitychange', handleVisibilityChange)" in hook
            assert "document.removeEventListener('visibilitychange', handleVisibilityChange)" in hook
            assert "document.visibilityState === 'hidden'" in hook
            assert 'clearPollTimeout()' in hook

    def test_api_methods_and_encoded_detail_id(self):
        assert 'getGovernanceProposals' in self.api
        assert 'getGovernanceProposal' in self.api
        assert 'encodeURIComponent(proposalId)' in self.api

    def test_cursor_zero_and_page_size(self):
        assert 'beforeProposalId !== null' in self.api
        assert 'export const PAGE_SIZE = 25' in self.listing
        assert 'value !== null && value !== undefined' in self.listing

    def test_cursor_history_is_unbounded_and_retry_is_exact(self):
        assert 'const history = [...cursorHistory.slice(0, pageIndex + 1), nextCursor]' in self.listing
        assert 'loadPage(request.cursor, request.targetIndex, request.history)' in self.listing
        assert not re.search(r'cursorHistory[^\n]*(slice\(-|MAX)', self.listing)

    def test_404_resets_public_pagination_state(self):
        branch = self.listing[self.listing.index('if (cause.status === 404)'):]
        for contract in ['setPageIndex(0)', 'setCursorHistory([null])', 'setSnapshotMissing(true)', 'failedRequest.current = null']:
            assert contract in branch

    def test_errors_clear_stale_data_and_disable_older(self):
        assert 'clearPublicData()' in self.listing
        assert 'canLoadOlder: !error && !snapshotMissing && hasCursor(nextCursor)' in self.listing
        assert 'failedRequest.current = attemptedRequest' in self.listing

    def test_success_responses_are_validated(self):
        assert 'isValidGovernanceListResponse(response)' in self.listing
        assert 'isValidGovernanceDetailResponse(response, proposalId)' in self.detail

    def test_invalid_detail_id_skips_api(self):
        assert 'if (proposalId === null) return' in self.detail
        assert "invalidProposalId: proposalId === null" in self.detail

    def test_detail_distinguishes_snapshot_and_proposal_404_responses(self):
        assert "cause.detail === 'Governance snapshot not found'" in self.detail
        assert "cause.detail === 'Governance proposal not found'" in self.detail
        assert 'const error = !snapshotMissing && !notFound' in self.detail
        assert 'snapshotMissing,' in self.detail

    def test_unknown_detail_404_remains_a_recoverable_error(self):
        assert "const notFound = cause.status === 404\n        && cause.detail === 'Governance proposal not found'" in self.detail
        assert "healthState: error ? 'error' : 'healthy'" in self.detail


class TestGovernanceListPage:
    page = read('frontend/src/pages/Governance.jsx')
    presentation = read('frontend/src/components/GovernancePresentation.jsx')

    def test_summary_and_unknown_notice(self):
        for label in ['Total Proposals', 'Active', 'Accepted', 'Rejected', 'unknown stored status']:
            assert label in self.page

    def test_six_columns_are_in_contract_order(self):
        labels = re.findall(r"label: '([^']+)'", self.page)
        assert labels[:6] == ['Proposal', 'Title', 'Author', 'Status', 'Eligible Tiers', 'Vote Split']

    def test_links_copy_status_and_vote_text(self):
        assert self.page.count('proposalHref(item.proposal_id)') >= 2
        assert 'CopyButton' in self.page and 'StatusBadge' in self.page
        for option in ['YES', 'NO', 'ABSTAIN']:
            assert option in self.presentation

    def test_vote_split_uses_semantic_text_classes(self):
        for option in ['yes', 'no', 'abstain']:
            assert f'className="governance-vote-split__{option}"' in self.presentation

    def test_pagination_buttons_have_explicit_type(self):
        for label in ['Newer proposals', 'Older proposals']:
            assert re.search(rf'<button[^>]*type="button"[^>]*>\s*{label}', self.page)

    def test_list_header_omits_snapshot_context(self):
        assert 'governance-page__context' not in self.page
        assert 'source.chain_id' not in self.page
        assert 'source.realm_path' not in self.page
        assert 'source.source_height' not in self.page
        assert 'source.last_success_at' not in self.page
        assert '<time' not in self.page


class TestGovernanceDetailPage:
    detail = read('frontend/src/pages/GovernanceDetail.jsx')

    def test_states_and_sections(self):
        for text in ['Back to Governance', 'Loading proposal…', 'Invalid proposal ID', 'Governance proposal not found', 'currently unavailable', 'Proposal Details', 'Vote Results', 'Votes']:
            assert text in self.detail

    def test_snapshot_missing_state_is_distinct_and_retryable(self):
        assert 'if (notFound) return <StatePanel title="Governance proposal not found" />' in self.detail
        assert 'if (snapshotMissing) return <StatePanel title="Governance snapshot is not available yet" retry={retry} />' in self.detail
        assert self.detail.index('if (snapshotMissing)') < self.detail.index('if (error || !proposal)')

    def test_snapshot_footer_is_not_rendered(self):
        for footer_content in ['Governance data snapshot', 'governance-detail__snapshot-meta',
                               'source.source_height', 'Saved <time', 'href={`/blocks/${height}`}']:
            assert footer_content not in self.detail

    def test_extended_snapshot_fields_remain_omitted(self):
        for field in ['Source Chain', 'Realm', 'First Observed Height', 'Last Observed Height']:
            assert f'<Field label="{field}">' not in self.detail

    def test_copy_and_string_voting_power(self):
        assert 'CopyButton' in self.detail
        assert "vote.voting_power ?? '—'" in self.detail
        assert 'Number(vote.voting_power)' not in self.detail

    def test_stable_vote_key_does_not_use_index(self):
        key = re.search(r'const voteRowKey = ([^\n]+)', self.detail).group(1)
        assert 'index' not in key
        assert 'voter_address' in key and 'voter_display' in key

    def test_safe_rendering_and_string_safe_heights(self):
        assert 'dangerouslySetInnerHTML' not in self.detail
        assert 'Number(height)' not in self.detail


class TestGovernanceScopeAndCss:
    files = '\n'.join(read(path) for path in [
        'frontend/src/hooks/useGovernancePage.js',
        'frontend/src/hooks/useGovernanceDetail.js',
        'frontend/src/pages/Governance.jsx',
        'frontend/src/pages/GovernanceDetail.jsx',
    ])
    css = read('frontend/src/styles/app.css').split('/* Governance */', 1)[1]

    def test_scope_has_no_rpc_raw_wallet_search_or_assets(self):
        lowered = self.files.lower()
        for forbidden in ['rpc', 'raw_detail_render', 'raw_votes_render', 'wallet', 'adena', 'global search', '<img']:
            assert forbidden not in lowered

    def test_css_uses_existing_palette_only(self):
        for variable in ['--color-border', '--color-border-soft', '--color-text', '--color-text-bright', '--color-text-secondary', '--color-accent', '--color-success', '--color-warning', '--color-error']:
            assert f'var({variable})' in self.css
        literals = re.findall(r'#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\(', self.css)
        assert set(literals) <= {'#dc795e'}

    def test_table_geometry_and_responsive_rules(self):
        widths = [int(value) for value in re.findall(r'th:nth-child\(\d\) \{ width: (\d+)%', self.css)]
        assert widths == [8, 31, 20, 12, 13, 16]
        assert sum(widths) == 100
        assert 'min-width: 1050px' in self.css
        assert '@media (max-width: 1100px)' in self.css
        assert '@media (max-width: 760px)' in self.css

    def test_vote_segments_do_not_shrink(self):
        assert '.governance-vote-bar i { display: block; flex: 0 0 auto; }' in self.css

    def test_vote_text_uses_semantic_colors_and_readable_type(self):
        text_rule = re.search(r'\.governance-vote-split__text \{([^}]+)\}', self.css).group(1)
        assert 'font-size: 9px' in text_rule
        assert 'font-weight: 600' in text_rule
        tones = {
            'yes': '--color-success',
            'no': '--color-error',
            'abstain': '--color-warning',
        }
        for option, variable in tones.items():
            assert re.search(rf'\.governance-vote-split__{option} \{{[^}}]*color: var\({variable}\)', self.css)
