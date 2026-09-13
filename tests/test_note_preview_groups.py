"""`notePreviewText`'s capture-group indices must track INLINE_MD's shape.

A lint, not a behaviour test, for the reason the other frontend lints exist:
this Python suite cannot run `app.js`. It pins the one coupling that already
broke silently.

Reported with a screenshot of the Contents page, "Girl with bell undefined",
"Leafeon Pokemon image test undefined". The `++colour|text++` highlight
alternative was added to INLINE_MD *after* `notePreviewText`'s replacer was
written, introducing two capture groups in the middle of the pattern and
shifting every index past it by two. Nothing failed loudly: the `??` chain
walked off the end of the branches it knew about, the last one evaluated to
`undefined`, and `String.replace` stringified that straight into the preview.

Three things were wrong and only one was visible: an image previewed as
"undefined", a link previewed as "undefined", and `==red|highlighted==`
previewed as "red", the colour name, because the optional colour group was
being read as the text.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "app.js"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _inline_md() -> str:
    src = _source()
    start = src.index("const INLINE_MD =")
    return src[start : src.index(";", start)]


def _preview_replacer() -> str:
    """The function body with its comments stripped.

    Comments matter here: the fix that prompted these tests explains itself by
    naming the very indices it must not read, so scanning the raw text would
    match the prose rather than the code."""
    src = _source()
    start = src.index("function notePreviewText(")
    body = src[start : src.index("\n}", start)]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("//"))


def _capture_group_count(pattern: str) -> int:
    """Capturing groups only: `(?:`, `(?<!` and friends do not count."""
    return len(re.findall(r"(?<!\\)\((?!\?)", pattern))


def test_inline_md_still_has_twelve_capture_groups():
    """The canary. If this number moves, an alternative was added or removed
    and every index in the replacer below has shifted with it."""
    assert _capture_group_count(_inline_md()) == 12


def test_the_preview_reads_the_text_groups_not_the_colour_groups():
    """g4 and g6 are the *colour* names in `==red|x==` and `++blue|x++`.
    Reading either as the text is what previewed a highlight as "red"."""
    body = _preview_replacer()
    used = set(re.findall(r"m\[(\d+)\]", body))
    assert "4" not in used, "m[4] is the ==colour== group, not the highlighted text"
    assert "6" not in used, "m[6] is the ++colour++ group, not the highlighted text"


def test_the_preview_reaches_the_image_and_link_groups():
    """g9/g10 are the image's alt and url, g11/g12 the link's text and url.
    Not reaching them is what put the literal "undefined" in a preview."""
    used = set(re.findall(r"m\[(\d+)\]", _preview_replacer()))
    for group in ("9", "10", "11"):
        assert group in used, f"m[{group}] is never read, so that branch returns undefined"


def test_every_text_carrying_group_is_read():
    """One entry per alternative that yields displayable text."""
    used = set(re.findall(r"m\[(\d+)\]", _preview_replacer()))
    # code, bold, strike, highlight text, ++ text, italic, image alt, link text
    assert {"1", "2", "3", "5", "7", "8", "9", "11"} <= used


def test_an_empty_alt_still_says_something():
    """`![](/media/x.jpg)` has an empty g9, so the replacer must fall through
    to a word rather than rendering nothing where a picture was."""
    assert '"image"' in _preview_replacer()
