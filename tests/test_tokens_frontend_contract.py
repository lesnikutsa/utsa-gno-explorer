from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).parents[1]


def test_tokens_route_navigation_and_page_contract():
    app = (ROOT / "frontend/src/App.jsx").read_text()
    sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    assert "path === '/tokens'" in app
    assert "label: 'Tokens'" in sidebar and "href: '/tokens'" in sidebar
    for heading in ("Token", "App", "Decimals", "Total Supply", "Direct Calls", "Last Activity", "Visibility"):
        assert f"label: '{heading}'" in page
    assert page.index("label: 'Decimals'") < page.index("label: 'Total Supply'") < page.index("label: 'Direct Calls'")
    assert "realmDetailHref(item.path)" in page
    assert "item.identity_verified && item.symbol" in page
    assert all(term not in page for term in ("Price", "Market Cap", "TVL"))


def test_native_and_top_24h_are_separate_api_driven_sections():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    profile = (ROOT / "frontend/src/config/networkProfile.js").read_text()
    for value in ("Native Token", "GNOT", "Native", "ugnot", "decimals: 6"):
        assert value in page + profile
    assert "realmDetailHref(networkProfile.nativeToken" not in page
    assert "getTokenSupply(networkProfile.nativeToken" not in hook
    assert '>Top Tokens</h2>' in page and "Direct Calls ({TOKEN_WINDOW_LABELS[activityWindow]})" in page
    assert "Success ({TOKEN_WINDOW_LABELS[activityWindow]})" in page and "Last activity" in page
    assert "tokens-top__rank" not in page and "#{index + 1}" not in page
    assert "topActivity.slice(0, 3)" in page and "realmDetailHref(token.path)" in page
    assert "response.top_activity" in hook and "response.items" not in hook.split("setTopActivity", 1)[1].split("\n", 1)[0]
    assert "Complete token activity is not available" in page and "No verified token calls" in page
    assert "Loading token activity…" in page
    assert "Token activity is currently unavailable." in page
    activity_render = page.split('<section className="tokens-top"', 1)[1]
    assert activity_render.index("loading || activityLoading") < activity_render.index("error || activityError") < activity_render.index("topActivity === null")
    assert 'id="tokens-directory-title">Contract Assets' in page
    assert "Total Supply" in page and "networkProfile.networkName" in page
    assert "src={networkProfile.networkIconSrc}" in page
    assert "'/assets/utsa-logo.png'" not in page
    assert set(("24h", "7d", "30d")) == set(re.findall(r"'((?:24h|7d|30d))': '[^']+'", page))
    assert "availableActivityWindows.includes(value)" in page
    for forbidden in ("Price", "Market Cap", "TVL", "Holders", "Volume"):
        assert forbidden not in page


def test_tokens_styles_are_scoped():
    css = (ROOT / "frontend/src/styles/app.css").read_text()
    token_rules = "\n".join(line for line in css.splitlines() if "tokens" in line)
    assert "var(--color-card)" in token_rules and "var(--color-text-bright)" in token_rules
    assert "linear-gradient(135deg, var(--color-accent-soft), var(--color-card))" in token_rules
    assert ".tokens-native__card { width: 100%" in css
    assert "max-width: 430px" not in token_rules
    assert ".tokens-top__metrics > div:last-child { margin-left: auto; text-align: right; }" in css


def test_tokens_cursor_pagination_and_request_safety_contract():
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    service = (ROOT / "frontend/src/services/api.js").read_text()
    assert "export const PAGE_SIZE = 50" in hook
    for state in ("pageIndex", "nextCursor", "cursorHistory"):
        assert f"const [{state}" in hook
    assert "beforeActivityHeight: request.cursor?.activityHeight" in hook
    assert "beforePath: request.cursor?.path" in hook
    assert "search: appliedSearch" in hook
    assert "resetAndLoad(search)" in hook
    assert "id !== requestId.current" in hook
    assert "id === requestId.current" in hook
    assert "mounted.current" in hook and "AbortController" in hook
    assert "setSummary(null)" in hook
    assert "getTokenSupply(item.path" in hook
    assert "Math.min(4, pending.length)" in hook
    assert "supplyCache.current" in hook
    assert "supplies[item.path]?.available" in page and ": '—'" in page
    assert "Newer entries" in page and "Older entries" in page
    assert "disabled={loading || !canLoadOlder}" in page
    assert "refreshInBackground" in hook and "q: appliedSearch" in hook
    assert "activityWindow: currentActivityWindow.current" in hook
    assert "selectActivityWindow" in hook
    assert "setItems([])" not in hook.split("const refreshInBackground", 1)[1].split("const resetAndLoad", 1)[0]
    assert "ChangedValue" in page


def test_activity_window_refresh_is_scoped_to_top_tokens():
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    activity = hook.split("const loadActivityWindow", 1)[1].split("const selectActivityWindow", 1)[0]
    for forbidden in ("setItems(", "setSummary(", "setNativeToken(", "setSupplies(",
                      "setPageIndex(", "setAppliedSearch(", "setLoading("):
        assert forbidden not in activity
    assert "setActivityLoading(true)" in activity and "setActivityError(true)" in activity
    assert "activityRequestId.current" in activity and "currentActivityWindow.current !== nextWindow" in activity
    assert "activityController.current?.abort()" in activity
    assert "retryActivity" in hook


def test_token_table_uses_existing_sorting_contract_only_for_requested_columns():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    assert "useMemo" in page and "sortTokenDirectoryItems" in page
    assert "useState({ key: 'last_activity_at', direction: 'descending' })" in page
    assert "sortKey={sort.key}" in page and "sortDirection={sort.direction}" in page and "onSort=" in page
    direct = page.split("key: 'direct_call_count'", 1)[1].split("},", 1)[0]
    activity = page.split("key: 'last_activity_at'", 1)[1].split("},", 1)[0]
    supply = page.split("key: 'total_supply'", 1)[1].split("},", 1)[0]
    assert "sortable: true" in direct and "defaultSortDirection: 'descending'" in direct
    assert "sortable: true" in activity and "defaultSortDirection: 'descending'" in activity
    assert "sortable: true" in supply and "defaultSortDirection: 'descending'" in supply
    assert "sortDisabled: !suppliesSettled" in supply


def test_total_supply_sort_waits_for_terminal_visible_supply_states():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    table = (ROOT / "frontend/src/components/DataTable.jsx").read_text()
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    sorter = (ROOT / "frontend/src/utils/tokenDirectory.js").read_text()
    assert "items.filter((item) => item.standard === 'grc20').every((item) => Object.hasOwn(supplies, item.path))" in page
    assert "sort.key === 'total_supply' && !suppliesSettled ? null : sort.key" in page
    assert "disabled={column.sortDisabled === true}" in table
    assert "BigInt(supply.raw_total_supply)" in sorter and "10n **" in sorter
    total_sort = sorter.split("const exactSupply", 1)[1]
    assert "parseFloat(" not in total_sort and "Number(" not in total_sort
    assert "getTokenSupply" not in sorter
    assert "Math.min(4, pending.length)" in hook


def test_tokens_auto_refresh_matches_visibility_and_overlap_contract():
    auto = (ROOT / "frontend/src/hooks/useTokensAutoRefresh.js").read_text()
    app = (ROOT / "frontend/src/App.jsx").read_text()
    assert "TOKENS_POLL_MS = 30_000" in auto
    assert "TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS = 15_000" in auto
    assert "document.visibilityState === 'hidden'" in auto
    assert "visibilitychange" in auto and "runCycle()" in auto
    assert "cycleRunning.current" in auto
    assert "tokensPage.pageIndex === 0" in app


def test_directory_metrics_use_existing_changed_value_feedback():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    direct = page.split("key: 'direct_call_count'", 1)[1].split("},", 1)[0]
    activity = page.split("key: 'last_activity_at'", 1)[1].split("},", 1)[0]
    assert "<ChangedValue value={item.direct_call_count}>" in direct
    assert "<LastActivityValue timestamp={item.last_activity_at} />" in activity
    helper = page.split("const lastActivityChangeValue", 1)[1].split("const TOKEN_WINDOW_LABELS", 1)[0]
    assert "`${timestamp ?? 'never'}|${label}`" in helper
    assert "timestamp ? relativeTime(timestamp) : 'Never'" in helper
    assert "value={lastActivityChangeValue(timestamp, label)}" in helper
    for existing_value in ("summary?.grc20_count", "summary?.grc721_count", "native.available ? native.total_supply : null",
                           "token.direct_call_count", "token.success_rate"):
        assert f"value={{{existing_value}}}" in page


def test_directory_feedback_does_not_change_polling_supply_or_sorting():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    auto = (ROOT / "frontend/src/hooks/useTokensAutoRefresh.js").read_text()
    assert "export const TOKENS_POLL_MS = 30_000" in auto
    assert "setTimeout(runCycle, TOKENS_POLL_MS)" in auto
    assert "setInterval" not in auto
    background = hook.split("const refreshInBackground", 1)[1].split("const resetAndLoad", 1)[0]
    assert "getTokenSupply" not in background
    assert "useState({ key: 'last_activity_at', direction: 'descending' })" in page
    assert "sortTokenDirectoryItems(items, effectiveSortKey, sort.direction, supplies)" in page
    total_supply = page.split("key: 'total_supply'", 1)[1].split("},", 1)[0]
    assert "ChangedValue" not in total_supply


def test_total_supply_formatting_uses_strings_without_precision_loss():
    script = """import { formatTokenSupply } from './frontend/src/utils/tokenSupply.js';
const values = ['0', '300000000', '102569491.938420', '184467440737095516161844674407370955161', null];
console.log(JSON.stringify(values.map(formatTokenSupply)));"""
    result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == '["0","300,000,000","102,569,491.93842","184,467,440,737,095,516,161,844,674,407,370,955,161","—"]'


def test_unified_asset_tabs_and_tables_preserve_navigation_contract():
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
    hook = (ROOT / "frontend/src/hooks/useTokensPage.js").read_text()
    assert "realms-page__filters" in page and "realms-page__filter" in page
    for label in ("All", "GRC20 Tokens", "NFTs"):
        assert f"'{label}'" in page
    assert "item.standard.toUpperCase()" in page
    assert "key: 'token_count', label: 'NFTs'" in page
    assert "token_count', label: 'Total Supply'" not in page
    assert "standard: currentAssetFilter.current" in hook
    assert sidebar.count("label: 'Tokens'") == 1 and "label: 'NFTs'" not in sidebar
