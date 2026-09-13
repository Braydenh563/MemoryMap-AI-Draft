"""The lock screen is this app's only privacy boundary.

ROADMAP.md ranks auditing it first, and says why: shortcuts once ran behind
the lock screen and were found by a user pressing keys, not by a test.

The audit that produced this file drove the running app locked and checked
each avenue the roadmap named. **The server side already held**, `/entries`,
`/media`, `/documents` and `/reminders` all answer 401 while locked, and the
keyboard gate gave nothing away (the command palette, the agent palette, `/`
to focus search and the `g`-then-letter tab jumps were all refused, and a
`#hash` route did not unlock anything).

**The client side did not.** The overlay was a visual cover, not a purge:
with the notebook locked, `#entry-list` still held 61 notes and 3,431
characters of their text, `#library-grid` 5,089, and the documents list
6,422: one devtools click, one screen reader or one browser extension away
from being read. `purgeLockedContent()` closes that, and unlocking restores
everything because `startApp()` re-renders it.
"""

from __future__ import annotations

from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "frontend" / "app.js"

#: Containers that hold the user's own words rather than the app's chrome.
USER_CONTENT_IDS = [
    "entry-list",
    "chat-messages",
    "library-grid",
    "library-docs-list",
    "timeline-scroll",
    "reminder-list-card",
    "graph-svg",
    "palette-list",
]


def test_locking_purges_the_rendered_content():
    """`lockNow` must clear the DOM, not merely cover it."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("async function lockNow(")
    body = source[start : source.index("\n}", start)]
    assert "purgeLockedContent()" in body, (
        "lockNow must purge rendered content, the overlay alone is a cover, not a boundary"
    )


def test_every_user_content_container_is_purged():
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const LOCK_PURGE_IDS")
    listed = source[start : source.index("];", start)]
    missing = [name for name in USER_CONTENT_IDS if f'"{name}"' not in listed]
    assert not missing, f"these still hold the user's words while locked: {missing}"


def test_text_fields_are_cleared_too():
    """A textarea keeps its text in `.value`, which `replaceChildren()` never
    touches: the document editor would otherwise stay fully readable behind
    the lock screen."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function purgeLockedContent(")
    body = source[start : source.index("\n}\n", start)]
    assert '"value" in field' in body or ".value = \"\"" in body
    for field in ("doc-content", "doc-title"):
        assert field in body, f"{field} keeps its text in .value and must be cleared"


def test_locking_reaches_every_open_tab():
    """Locking in one tab must lock the others.

    The audit found this by opening a second tab, which ROADMAP.md had named
    as an unchecked avenue. Locking in tab A cleared tab A and dropped the
    shared token, so the API correctly refused tab B, but tab B kept showing
    all 61 notes with no lock screen, indefinitely. Lock the notebook, walk
    away from a shared machine, and everything is still on screen in the
    window behind.

    `storage` is the right signal because it fires in *other* tabs of the same
    origin only: the tab that locked has already handled itself, and nothing
    has to poll.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert 'addEventListener("storage"' in source, (
        "no cross-tab lock listener, a second open tab keeps showing everything"
    )
    start = source.index('addEventListener("storage"')
    handler = source[start : source.index("\n});", start)]
    assert "purgeLockedContent()" in handler
    assert "showLockScreen(false)" in handler
    # A sign-in elsewhere must not be mistaken for a lock.
    assert 'localStorage.getItem("token")' in handler
