"""Every stylesheet closes every block it opens.

**This exists because losing one `}` cost a whole feature's styling and
nothing anywhere reported it.**

A phone-width commit added `@media (max-width: 600px) {` to
`07-whiteboard-misc.css` and did not close it. Everything after it: the two
hundred lines of mindmap node, edge, chevron and badge styling that Phase 2
had written and measured, was swallowed into that media query. A mind map
therefore rendered with its real styling *only* on a viewport under 600px
wide, and with none of it at any other width: no fill, no border, no branch
spine, no rounded corners, and its hover controls laid out as a full-width
block instead of a positioned row.

Every existing guard was blind to it, and that is the point of this file:

- CSS has no parse errors of this kind. An unclosed block is legal-looking
  input; the parser simply keeps consuming rules into it.
- `node --check` reads JavaScript.
- `test_style_scale.py` lints *declarations* (spacing values against the
  scale), and every declaration involved was on the scale.
- `test_frontend_ids.py` / `test_frontend_handlers.py` read HTML and JS.
- The mindmap Playwright sweep's 35 assertions were all still green: they
  check DOM structure, API state and geometry that JavaScript computes and
  writes inline. None of that changes when a stylesheet goes inert.

So a whole phase could, and did, pass its own tests with its stylesheet
switched off. The only thing that found it was measuring what a node actually
painted (`getComputedStyle(node).backgroundColor` read `rgba(0, 0, 0, 0)`),
which is CLAUDE.md's standing rule and the reason it is a standing rule.

The check is deliberately about *nesting depth*, not about formatting: it
counts braces outside comments and strings, and asserts the file ends where it
started. That is exactly the failure above and nothing else, so it cannot
start refusing legitimate CSS someone writes later.
"""

from __future__ import annotations

import pytest

from tests._css_paths import FRONTEND_DIR


def _sheets() -> list:
    files = sorted((FRONTEND_DIR / "css").glob("*.css"))
    assert files, "no stylesheets found: has the css directory moved?"
    return files


def _depth_trace(text: str) -> tuple[int, int]:
    """Final nesting depth, and the line it first went negative on (0 if not).

    Braces inside `/* … */` comments and inside quoted strings do not count, 
    a `content: "}"` is real CSS and a comment full of examples is common in
    this codebase, which comments at length by house style.
    """
    depth = 0
    first_negative = 0
    in_comment = False
    quote = ""
    line_no = 1
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\n":
            line_no += 1
            i += 1
            continue
        if in_comment:
            if text.startswith("*/", i):
                in_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = ""
            i += 1
            continue
        if text.startswith("/*", i):
            in_comment = True
            i += 2
            continue
        if char in "\"'":
            quote = char
            i += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0 and not first_negative:
                first_negative = line_no
        i += 1
    return depth, first_negative


@pytest.mark.parametrize("sheet", _sheets(), ids=lambda p: p.name)
def test_a_stylesheet_closes_every_block_it_opens(sheet) -> None:
    depth, first_negative = _depth_trace(sheet.read_text(encoding="utf-8"))
    assert first_negative == 0, (
        f"{sheet.name} has a stray `}}` at line {first_negative}: it closes a "
        "block that was never opened, so every rule after it lands at the top "
        "level whether or not that is what was meant."
    )
    assert depth == 0, (
        f"{sheet.name} ends {depth} block(s) deep: a `{{` somewhere in it is "
        "never closed, so every rule after that point has been swallowed into "
        "it. Nothing else in this suite can see that, read this file's "
        "docstring for what it cost the last time."
    )
