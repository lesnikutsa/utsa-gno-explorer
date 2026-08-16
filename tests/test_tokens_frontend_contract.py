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
    assert all(term not in page for term in ("Price", "Market Cap", "TVL", "NFT"))


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
    assert activity_render.index("loading ?") < activity_render.index("error ?") < activity_render.index("topActivity === null")
    assert 'id="tokens-directory-title">GRC20 Tokens' in page
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


def test_tokens_auto_refresh_matches_visibility_and_overlap_contract():
    auto = (ROOT / "frontend/src/hooks/useTokensAutoRefresh.js").read_text()
    app = (ROOT / "frontend/src/App.jsx").read_text()
    assert "TOKENS_POLL_MS = 30_000" in auto
    assert "TOKENS_BACKGROUND_REQUEST_TIMEOUT_MS = 15_000" in auto
    assert "document.visibilityState === 'hidden'" in auto
    assert "visibilitychange" in auto and "runCycle()" in auto
    assert "cycleRunning.current" in auto
    assert "tokensPage.pageIndex === 0" in app


def test_total_supply_formatting_uses_strings_without_precision_loss():
    script = """import { formatTokenSupply } from './frontend/src/utils/tokenSupply.js';
const values = ['0', '300000000', '102569491.938420', '184467440737095516161844674407370955161', null];
console.log(JSON.stringify(values.map(formatTokenSupply)));"""
    result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == '["0","300,000,000","102,569,491.93842","184,467,440,737,095,516,161,844,674,407,370,955,161","—"]'
