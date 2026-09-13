"""The highlight/text-colour allowlists, which live in three places at once.

A lint, not a behaviour test, in the same family as test_style_scale.py:
Python cannot render the page, but it can check that three lists agree.

Why it exists: the parser's list said six colours while the toolbars offered
eight. Picking Red from the highlight menu wrote `==red|text==`, the
optional-colour group in INLINE_MD declined to match "red|", and the note
rendered the literal text "red|text" inside a yellow highlight. Nothing
threw, and each of the three files read as correct on its own, the bug only
exists in the disagreement between them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend"
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
DOCUMENTS_JS = (ROOT / "documents.js").read_text(encoding="utf-8")
CSS = (ROOT / "css" / "05-sidebars-themes.css").read_text(encoding="utf-8")


def _toolbar_colours() -> list[str]:
    match = re.search(r"const MD_COLOURS = \[(.*?)\];", DOCUMENTS_JS, re.S)
    assert match, "MD_COLOURS not found: has the toolbar moved?"
    return re.findall(r'"([a-z]+)"', match.group(1))


def _regex_colour_groups() -> list[list[str]]:
    """Every `(a|b|c)` alternation used as a colour list in the two patterns."""
    groups = []
    for name in ("INLINE_MD", "INLINE_MD_LEGACY"):
        body = re.search(rf"const {name} =\s*(/.*?/g);", APP_JS, re.S)
        assert body, f"{name} not found"
        for alternation in re.findall(r"\(([a-z]+(?:\|[a-z]+){3,})\)", body.group(1)):
            groups.append(alternation.split("|"))
    return groups


def test_the_toolbar_offers_exactly_the_colours_the_parser_accepts():
    toolbar = set(_toolbar_colours())
    assert toolbar, "no colours found in MD_COLOURS"
    groups = _regex_colour_groups()
    assert groups, "no colour alternations found in the inline patterns"
    for group in groups:
        assert set(group) == toolbar, (
            "A colour list in app.js's inline patterns disagrees with "
            f"MD_COLOURS. Parser: {sorted(group)}; toolbar: {sorted(toolbar)}. "
            "A colour the toolbar can write but the parser will not match "
            "renders as its own literal name inside the note."
        )


def test_every_offered_colour_has_a_stylesheet_rule():
    for colour in _toolbar_colours():
        assert f"mark.text-highlight-{colour}" in CSS, (
            f"no highlight rule for {colour!r}: it would fall back to the "
            "default and be indistinguishable from yellow."
        )
        assert f".text-ink-{colour}" in CSS, (
            f"no text-colour rule for {colour!r}: the class would be inert."
        )
