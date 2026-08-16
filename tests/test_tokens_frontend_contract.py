from pathlib import Path
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


def test_tokens_styles_are_scoped():
    css = (ROOT / "frontend/src/styles/app.css").read_text()
    token_rules = "\n".join(line for line in css.splitlines() if "tokens" in line)
    assert "var(--color-card)" in token_rules and "var(--color-text-bright)" in token_rules


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


def test_total_supply_formatting_uses_strings_without_precision_loss():
    script = """import { formatTokenSupply } from './frontend/src/utils/tokenSupply.js';
const values = ['0', '300000000', '102569491.938420', '184467440737095516161844674407370955161', null];
console.log(JSON.stringify(values.map(formatTokenSupply)));"""
    result = subprocess.run(["node", "--input-type=module", "--eval", script], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == '["0","300,000,000","102,569,491.93842","184,467,440,737,095,516,161,844,674,407,370,955,161","—"]'
