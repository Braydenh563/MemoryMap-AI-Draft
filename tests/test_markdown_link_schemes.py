"""A note's own text must not become a live `javascript:` link.

`renderInlineMarkdown` turns `[text](url)` into an anchor. Without a scheme
allow-list, a note pasted from anywhere could carry a click-to-run script;
the CSP blocks it today, and this pins the second lock so a loosened CSP
never quietly reopens it. Static, because the suite cannot run the DOM.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


def test_markdown_links_go_through_the_scheme_allow_list():
    src = APP.read_text(encoding="utf-8")
    assert "function safeHref(" in src
    body = src[src.index("function renderInlineMarkdown(") :]
    body = body[: body.index("\nfunction ", 1)]
    assert "a.href = safeHref(linkUrl)" in body, "the markdown link anchor must use safeHref"
    assert "a.href = linkUrl" not in body


def test_the_allow_list_is_what_it_says():
    src = APP.read_text(encoding="utf-8")
    fn = src[src.index("function safeHref(") :]
    fn = fn[: fn.index("\n}\n") + 3]
    assert "https?:" in fn and "mailto:" in fn
    assert 'return "#"' in fn
