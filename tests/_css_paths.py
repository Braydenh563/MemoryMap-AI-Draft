"""Where the CSS lives, now that it isn't one file.

`frontend/style.css` was split into multiple linked files (ROADMAP.md
Priority 0 item 2: "CSS splitting into multiple linked `<link>` files is
mechanically low-risk"). Every test that used to hardcode
`frontend/style.css` needs the same list, in the same order index.html
loads them in: that order is load-bearing (the split was cut only at
section-comment boundaries, so concatenating these files in this order
reproduces the old single file byte-for-byte, which is what guarantees no
selector's cascade/specificity position moved). One shared list here means
a ninth file, or a reorder, is a one-line change instead of an N-line hunt
through every test that used to open `style.css` directly.

Not named `test_*.py` on purpose: pytest would otherwise try to collect it
and find no tests in it.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
CSS_DIR = FRONTEND_DIR / "css"

#: Matches index.html's <link rel="stylesheet"> order exactly.
CSS_FILES = [
    CSS_DIR / "00-tokens-shell.css",
    CSS_DIR / "01-forms-settings.css",
    CSS_DIR / "02-chat-graph.css",
    CSS_DIR / "03-dashboard-widgets.css",
    CSS_DIR / "04-chat-dock-appearance.css",
    CSS_DIR / "05-sidebars-themes.css",
    CSS_DIR / "06-timeline-dialogs.css",
    CSS_DIR / "07-whiteboard-misc.css",
    CSS_DIR / "08-consistency.css",
    #: The documents editor's own layout (DOCUMENTS_PLAN Phase 2). Appended
    #: rather than inserted: it is linked last in index.html, and this list is
    #: load order, which is what makes the concatenation above meaningful.
    CSS_DIR / "09-editor.css",
    CSS_DIR / "10-responsive.css",
]


def css_text() -> str:
    """All of CSS_FILES, concatenated in load order.

    Byte-for-byte what `frontend/style.css` used to return from
    `.read_text()`, see the split's own diff, or diff this against a
    `cat`'d concatenation of CSS_FILES, to confirm.
    """
    return "".join(p.read_text(encoding="utf-8") for p in CSS_FILES)
