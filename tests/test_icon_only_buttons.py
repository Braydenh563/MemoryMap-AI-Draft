"""A button whose whole content is an icon must be square, and in this app
that means it must carry `icon-only` (or `icon-button`).

**This is a lint, not a behaviour test, and it exists because of a measurement.**
Reported directly: "the popup close buttons are rectangular not square". Driven
in Chromium with every popup forced visible, nine of them measured **43.6 x 28**
- `agent-monitor-close`, `web-panel-close`, `timeline-popup-close`,
`graph-popup-close`, `graph-new-close`, `doc-find-close`, `doc-ai-close`,
`wb-library-close` and `extract-close`, along with the find bar's prev/next,
the four Library/Contents refresh buttons and the capture speak button.

Every one of them was `class="ghost small"` wrapped around a lone `<i class="ph
…">`, so it inherited `button.small`'s text padding (`0.25rem 0.8rem`) and came
out wider than it was tall. The squaring rule in `00-tokens-shell.css` keys off
the class, and the comment there records why it cannot key off the content
instead: `button:has(> i.ph:only-child)` also matches an icon *followed by a
text label*, because `:only-child` counts element siblings and ignores text, and
trying it squared every icon+label button in the app to the width of its own
words (`chat-compress` came out 91x91, measured).

So CSS cannot see text and the class has to be remembered per button, which is
exactly the kind of thing nobody remembers. Python can see the text, so this
test remembers it instead.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

# Buttons that hold an icon and no words, but are deliberately not square.
# Keep this list short and give every entry a reason.
ALLOWED = {
    # Sized 2rem square by `.graph-help-toggle` itself (03-dashboard-widgets.css),
    # which also rounds it to a circle. Adding `icon-only` would put this in a
    # cascade fight with that rule for no gain.
    "graph-help-toggle",
    # `.graph-zoom-btn` (02-chat-graph.css) fixes its own square size for the
    # map's zoom cluster, where the buttons stack into one pill.
    "graph-zoom-btn",
    # The document toolbar's own 32px square controls (07-whiteboard-misc.css).
    "doc-toolbar-width",
}

# A segmented control's cells are sized by the group, not individually: the
# Library's Cards/Rows pair measured 33.2x38 and 34.2x38, which is the segment
# height the row gives them, not `button.small` padding leaking through. Making
# each cell square would break the pair's shared height instead of fixing it.
ALLOWED_ATTRS = ("data-library-view",)


class _Buttons(HTMLParser):
    """Collects (line, tag, id, class, has_icon, text) for buttons and summaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.found: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in ("button", "summary"):
            self.stack.append(
                {
                    "line": self.getpos()[0],
                    "tag": tag,
                    "id": a.get("id", ""),
                    "cls": a.get("class", ""),
                    "icon": False,
                    "text": "",
                    # An aria-label/title is what makes an icon-only button
                    # readable; it is not text the layout has to fit.
                    "name": a.get("aria-label", "") or a.get("title", ""),
                    "attrs": a,
                    "depth": 0,
                }
            )
            return
        if self.stack:
            if tag == "i" and "ph" in a.get("class", "").split():
                self.stack[-1]["icon"] = True
            self.stack[-1]["depth"] += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("button", "summary") and self.stack:
            self.found.append(self.stack.pop())
        elif self.stack and self.stack[-1]["depth"] > 0:
            self.stack[-1]["depth"] -= 1

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1]["text"] += data


def _icon_only_buttons() -> list[dict]:
    parser = _Buttons()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    out = []
    for b in parser.found:
        if not b["icon"]:
            continue
        if re.sub(r"\s+", "", b["text"]):
            continue  # it has words; the class would square it to their width
        out.append(b)
    return out


def test_every_icon_only_button_is_marked_square() -> None:
    offenders = []
    for b in _icon_only_buttons():
        classes = set(b["cls"].split())
        if classes & {"icon-only", "icon-button"} or classes & ALLOWED:
            continue
        if any(b["attrs"].get(a) for a in ALLOWED_ATTRS):
            continue
        offenders.append(f"line {b['line']}: <{b['tag']} id={b['id']!r} class={b['cls']!r}>")
    assert not offenders, (
        "These buttons contain only an icon but carry neither `icon-only` nor "
        "`icon-button`, so `button.small`'s text padding will oval them "
        "(measured at 43.6x28 on nine popup close buttons). Add `icon-only` to "
        "the class list, or add the id/class to ALLOWED above with a reason:\n"
        + "\n".join(offenders)
    )


def test_every_icon_only_button_has_an_accessible_name() -> None:
    """No words means no accessible name unless one is spelled out."""
    offenders = []
    for b in _icon_only_buttons():
        if b["name"].strip():
            continue
        offenders.append(f"line {b['line']}: <{b['tag']} id={b['id']!r}>")
    assert not offenders, (
        "An icon-only button has no text for a screen reader to announce, so it "
        "needs `aria-label` or `title`:\n" + "\n".join(offenders)
    )
