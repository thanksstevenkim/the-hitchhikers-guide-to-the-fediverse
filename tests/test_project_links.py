from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = (
    "https://github.com/thanksstevenkim/"
    "the-hitchhikers-guide-to-the-fediverse"
)


def test_page_links_to_repository_and_issue_reporter() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert html.count(f'href="{REPOSITORY_URL}"') == 2
    assert f'href="{REPOSITORY_URL}/issues/new"' in html
    assert 'id="repository-link-label"' in html
    assert 'id="footer-source-link"' in html
    assert 'id="footer-issue-link"' in html


def test_page_exposes_persistent_theme_toggle() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "js" / "render.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="theme-toggle"' in html
    assert 'id="theme-light-icon"' in html
    assert 'id="theme-dark-icon"' in html
    assert 'localStorage.getItem("hitchhiker-theme")' in html
    assert 'localStorage.setItem(THEME_STORAGE_KEY, nextTheme)' in script
    assert ':root[data-theme="light"]' in styles
    assert ':root[data-theme="dark"]' in styles
