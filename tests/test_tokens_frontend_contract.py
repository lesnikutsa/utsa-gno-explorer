from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_tokens_route_navigation_and_page_contract():
    app = (ROOT / "frontend/src/App.jsx").read_text()
    sidebar = (ROOT / "frontend/src/components/Sidebar.jsx").read_text()
    page = (ROOT / "frontend/src/pages/Tokens.jsx").read_text()
    assert "path === '/tokens'" in app
    assert "label: 'Tokens'" in sidebar and "href: '/tokens'" in sidebar
    for heading in ("Token", "App", "Decimals", "Direct Calls", "Last Activity", "Visibility"):
        assert f"label: '{heading}'" in page
    assert "realmDetailHref(item.path)" in page
    assert "item.identity_verified && item.symbol" in page
    assert all(term not in page for term in ("Price", "Market Cap", "TVL", "NFT"))


def test_tokens_styles_are_scoped():
    css = (ROOT / "frontend/src/styles/app.css").read_text()
    token_rules = "\n".join(line for line in css.splitlines() if "tokens" in line)
    assert "var(--color-card)" in token_rules and "var(--color-text-bright)" in token_rules
