from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_metadata_ui_is_supplemental_and_source_is_react_escaped():
    page = (ROOT / "frontend/src/pages/RealmDetail.jsx").read_text()
    assert page.index("<Overview") < page.index("<Metadata") < page.index("<RecentCalls")
    for text in ("Files", "Functions", "Dependencies", "Docs", "Partial",
                 "Metadata has not been collected for this path yet."):
        assert text in page
    assert "<pre><code>{metadata.source.data.content}</code></pre>" in page
    assert "dangerouslySetInnerHTML" not in page


def test_metadata_requests_abort_and_paths_wrap_safely():
    hook = (ROOT / "frontend/src/hooks/useRealmMetadata.js").read_text()
    styles = (ROOT / "frontend/src/styles/app.css").read_text()
    assert "AbortController" in hook
    assert ".abort()" in hook
    assert "overflow-wrap: anywhere" in styles
    assert "overflow: auto" in styles


def test_metadata_does_not_add_frontend_dependency():
    package = (ROOT / "frontend/package.json").read_text()
    for dependency in ("monaco", "codemirror", "prism"):
        assert dependency not in package.lower()
