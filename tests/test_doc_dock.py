"""The document editor's top dock (§ documents).

Reported with a screenshot: "fix/redesign the ui, layout, alignment, sizing,
and look of the documents top dock". What it showed was a single row holding
the title plus twelve controls of four different heights, wrapping onto three
lines with "⬇ PDF" and a bin left alone on the last of them.

Two causes, both invisible in the source and both found by measuring in a
browser:

1. The dock carried `.doc-toolbar`, the *formatting* toolbar's class, so
   `.doc-toolbar button` restyled its `.ghost.small` buttons as 2rem glyph
   buttons while leaving the `<select>` and the segmented control alone.
2. The first fix used `height: var(--control-h)`, and `--control-h` is scoped
   to `.library-toolbar`/`.library-controls`. Undefined here, so the rule was
   invalid and did nothing, silently. Measured: 45 / 43 / 37 / 27 / 22 / 18px
   across six controls that are meant to be one height.

These are lints: nothing here can see a rendered page. They pin the two causes
so neither can come back unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
CSS = "".join(
    p.read_text(encoding="utf-8") for p in sorted(Path("frontend/css").glob("*.css"))
)


def test_the_dock_is_not_a_formatting_toolbar():
    """`.doc-toolbar button` is written for H1/B/I glyph buttons. The dock
    shared the class and inherited it."""
    dock = HTML.split('class="row space-between doc-dock"')[1].split("</div>")[0]
    assert "doc-toolbar" not in HTML.split("doc-dock")[0][-200:], "the dock kept the class"
    assert 'class="doc-toolbar" id="doc-toolbar"' in HTML, "the formatting bar keeps it"
    assert dock


def test_the_dock_declares_the_control_height_it_uses():
    """`--control-h` is not a global token. Used without being declared it is
    invalid where it is *used*, and an invalid height is silently no height, 
    the same shape as the appearance-defaults bug in CLAUDE.md."""
    block = CSS.split(".doc-dock {")[1].split("}")[0]
    assert "--control-h:" in block, (
        "--control-h is scoped to .library-toolbar; the dock has to declare its own"
    )
    heights = CSS.split(".doc-dock .ghost.small,")[1].split("}")[0]
    assert "height: var(--control-h)" in heights


def test_every_control_in_the_dock_is_sized_by_that_one_rule():
    """A select, a segmented control and a button each arrive from a different
    base rule and each size themselves."""
    selectors = CSS.split(".doc-dock .ghost.small,")[1].split("{")[0]
    for part in (".doc-file-type", ".seg"):
        assert part in selectors, part


def test_the_least_used_controls_are_behind_one_kebab():
    """Export .md, export PDF and delete were a third of the bar."""
    assert 'id="doc-dock-menu"' in HTML
    menu = HTML.split('id="doc-dock-menu"')[1].split("</details>")[0]
    for element_id in ("doc-export-md", "doc-export-pdf", "doc-delete"):
        assert f'id="{element_id}"' in menu, element_id


def test_the_ids_did_not_move():
    """documents.js binds by id. A redesign that renames one is a redesign
    that silently unwires it, the "features that never ran" shape."""
    js = Path("frontend/documents.js").read_text(encoding="utf-8")
    for element_id in re.findall(r'\$\("(doc-[a-z-]+)"\)', js):
        assert f'id="{element_id}"' in HTML, element_id


def test_the_export_label_is_set_with_setlabel_not_textcontent():
    """The button carries an icon element now. `textContent = …` would wipe
    it, which is the kind of thing that looks fine until you open the menu."""
    js = Path("frontend/documents.js").read_text(encoding="utf-8")
    assert 'setLabel($("doc-export-md")' in js
    assert '$("doc-export-md").textContent' not in js


def test_the_kebab_closes_on_a_pick_and_on_a_click_away():
    """`<details>` gives open/close, Enter/Space and Escape. It gives neither
    of these."""
    js = Path("frontend/documents.js").read_text(encoding="utf-8")
    assert "doc-dock-menu-item" in js
    assert "menu.contains(event.target)" in js


def test_the_name_and_the_type_share_a_row():
    """They are the same statement about the document. Moving the select off
    the action row is also what let that row fit on one line, measured at
    1018px, it was 20px too wide with the select still in it."""
    identity = HTML.split('class="doc-dock-identity"')[1].split("</span>")[0]
    assert 'id="doc-title"' in identity
    # DOCUMENTS Phase 1 moved the file type off the identity row into the
    # dock's ⋯ menu (its "File type" section): the row is the title alone and
    # the action row stays at five controls.
    menu = HTML.split('id="doc-dock-menu"')[1].split("</details>")[0]
    assert 'id="doc-file-type"' in menu
    assert 'id="doc-file-type"' not in identity


def test_printing_still_hides_the_dock():
    """It used to be hidden by `.doc-toolbar`; losing that class silently put
    a toolbar on every printed page."""
    assert "body.printing-doc .doc-dock," in CSS


def test_every_kebab_uses_the_same_icon():
    """Reported from two screenshots side by side: the gallery's kebab was
    vertical dots and every other one in the app was horizontal. The app had
    picked `ph:dots-three` long before this session (`kebabMenu()` in app.js,
    the graph's mobile "more" toggle); the dock and the gallery menus were
    added later and each guessed the vertical variant. Nothing renders wrong
    - it just reads as two different controls doing one job."""
    sources = {
        p.name: p.read_text(encoding="utf-8")
        for p in (
            Path("frontend/index.html"),
            Path("frontend/app.js"),
            Path("frontend/library.js"),
            Path("frontend/documents.js"),
        )
    }
    for name, text in sources.items():
        assert "dots-three-vertical" not in text, f"{name} uses the vertical kebab"
    assert 'class="ph ph-dots-three"' in sources["index.html"]
    assert '"ph:dots-three"' in sources["app.js"]
    #: library.js used to draw its own kebab and is asserted *not* to now: the
    #: Images/Files gallery menu was a second implementation of one control, 
    #: its own `<details>`, its own list class, its own placement code, which
    #: is how it drifted from every other menu in the app three times over. It
    #: calls `kebabMenu()` (app.js) like everything else, so the glyph is
    #: chosen in exactly one place and this file cannot disagree with it.
    assert "ph:dots-three" not in sources["library.js"], (
        "library.js is drawing its own kebab again, use kebabMenu() from app.js"
    )
