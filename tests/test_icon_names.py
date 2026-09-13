"""Every icon this app asks for has to exist in the font it ships.

Reported with a screenshot: the active Favourites button rendered as an
**empty circle**: a button with nothing in it. The cause is a whole class of
bug rather than one icon. The off state asked for `ph:star`, the on state for
`ph:star-slash`, and `star-slash` is not in this app's vendored Phosphor
subset (1,530 of Phosphor's icons, not all of them).

**A missing glyph in an icon font is not an error.** The character simply has
nothing to draw. Nothing logs, nothing throws, the CSS class is applied
exactly as written, and the source reads as correct at every line, the same
shape as the `APPEARANCE_DEFAULTS` bug in CLAUDE.md: a value that is invalid
*where it is used*, not where it is set. It reached a user because one icon
name out of 176 was wrong and there was no way to know.

This is a lint, like `test_style_scale.py` and `test_frontend_ids.py`, and it
exists for the same reason: the Python suite cannot see the DOM, and a
browser is the only other thing that could have caught it.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PHOSPHOR_CSS = FRONTEND / "vendor" / "phosphor" / "style.css"

#: `ph-lead` is this app's own utility class for the margin between an icon
#: and its label (see `setLabel` in app.js): it rides on the same element and
#: is deliberately not an icon.
NOT_ICONS = {"lead"}


def _available() -> set[str]:
    css = PHOSPHOR_CSS.read_text(encoding="utf-8")
    return set(re.findall(r"\.ph-([a-z0-9-]+):before", css))


def _strip_line_comments(source: str) -> str:
    """A `ph:name` inside prose is documentation, not a request for a glyph, 
    two of them explain the label grammar itself."""
    return "\n".join(line.split("//")[0] for line in source.splitlines())


def _requested() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for path in sorted([*FRONTEND.rglob("*.js"), *FRONTEND.rglob("*.html")]):
        if "vendor" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        text = _strip_line_comments(source) if path.suffix == ".js" else source
        #: The two ways this app names an icon: the `ph:name Label` marker
        #: `setLabel` understands, and a literal class in the markup.
        for pattern in (r"""["'`]ph:([a-z0-9-]+)""", r'''class="ph ph-([a-z0-9-]+)'''):
            for match in re.finditer(pattern, text):
                used.setdefault(match.group(1), set()).add(path.name)
    return {name: where for name, where in used.items() if name not in NOT_ICONS}


def test_every_icon_asked_for_is_in_the_font():
    available = _available()
    requested = _requested()
    missing = {name: sorted(where) for name, where in requested.items() if name not in available}
    assert not missing, (
        "these icon names are not in frontend/vendor/phosphor, they render as "
        f"an empty button with nothing logged: {missing}"
    )


def test_the_lint_is_actually_looking_at_something():
    """A regex that silently stops matching would make the test above pass
    forever. These two numbers are the guard against that."""
    assert len(_available()) > 1_000, "the Phosphor subset looks truncated"
    assert len(_requested()) > 100, (
        "far fewer icon names found than this app uses, the scan is broken, "
        "not the icons"
    )
