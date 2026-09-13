"""No two elements in index.html may share an id.

`document.getElementById` returns the *first* match and reports no error, so
a duplicate id silently binds half the code to the wrong element. That is
exactly how "Add persona" came to do nothing: a <div> in the Chat tab and the
Settings <textarea> both used `persona-prompt`, so `.value.trim()` ran against
the div, threw, and killed the click handler.

Browsers do not warn, linters do not run on this file, and the Python suite
cannot see the DOM, so this cheap parse is the only thing that would catch
the next one.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from tests._css_paths import css_text

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

# Ids that app.js creates at runtime rather than finding in the markup.
# `copy-fallback` is the last-resort copy dialog: it only exists while a
# browser has refused both clipboard mechanisms, so there is nothing to
# declare in index.html.
RUNTIME_IDS = {
    "user-css",
    "focus-timer-display",
    "focus-timer-toggle",
    "copy-fallback",
}


def _markup() -> str:
    """index.html with comments stripped.

    Comments here explain markup, so they quote tags, including ids, and a
    naive scan reads those as real elements.
    """
    return re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)


def _frontend_js() -> str:
    """app.js, whiteboard.js, graph.js, documents.js, library.js,
    dashboard.js and settings.js concatenated.

    The whiteboard subsystem (board/card CRUD, sketch drawing, export,
    move/resize) moved out of app.js into its own file, loaded by a second
    <script> tag, the graph view (force-directed map, layouts, tracing,
    the node popup) moved out into a third, the document editor moved out
    into a fourth (§10 of the app.js-split plan), the Library tab moved
    out into a fifth, out of *both* app.js and whiteboard.js, as §88.3's
    second file, the dashboard (widgets, masonry, the generative art) moved
    out into a sixth as §88.3's third file, and the settings modal, logs
    console and appearance system moved out into a seventh, settings.js , 
    as §88.3's fourth and last file. See index.html. A check that only read
    app.js would go on passing while silently covering none of the moved
    files' own $("...") lookups.
    """
    app = (INDEX.parent / "app.js").read_text(encoding="utf-8")
    whiteboard = (INDEX.parent / "whiteboard.js").read_text(encoding="utf-8")
    graph = (INDEX.parent / "graph.js").read_text(encoding="utf-8")
    documents = (INDEX.parent / "documents.js").read_text(encoding="utf-8")
    library = (INDEX.parent / "library.js").read_text(encoding="utf-8")
    dashboard = (INDEX.parent / "dashboard.js").read_text(encoding="utf-8")
    settings = (INDEX.parent / "settings.js").read_text(encoding="utf-8")
    return (
        app + "\n" + whiteboard + "\n" + graph + "\n" + documents + "\n" + library
        + "\n" + dashboard + "\n" + settings
    )


def test_no_duplicate_element_ids():
    ids = re.findall(r'\sid="([^"]+)"', _markup())
    duplicates = {name: n for name, n in Counter(ids).items() if n > 1}
    assert not duplicates, f"duplicate id(s) in index.html: {duplicates}"


def test_every_id_the_app_looks_up_actually_exists():
    """A typo'd id is `null`, and the failure lands wherever it is next used."""
    app = _frontend_js()
    declared = set(re.findall(r'\sid="([^"]+)"', _markup()))
    # Only the literal $("…") lookups; anything built from a variable can't be
    # checked statically and is skipped rather than guessed at.
    looked_up = set(re.findall(r'\$\("([a-z0-9-]+)"\)', app))
    missing = sorted(looked_up - declared - RUNTIME_IDS)
    assert not missing, (
        f"app.js/whiteboard.js/graph.js/documents.js/library.js/dashboard.js/settings.js look up ids that aren't "
        f"in index.html: {missing}"
    )


def test_the_prepaint_theme_table_matches_app_js():
    """index.html carries its own copy of THEME_PRESETS. Keep them equal.

    The inline script runs before app.js (and long before settings.js, which
    now owns THEME_PRESETS: §88.3 item 4) so the first paint already wears
    the right theme: without it every reload flashes the default. The cost
    is two copies of the same table, and a theme added to one and not the
    other looks fine until you reload, when the app flashes the wrong
    colours or falls back to the default entirely. Nothing else would
    notice.

    The pattern matches on the entry's *shape*, not on its first key. It used
    to require `theme:` there, which quietly stopped matching anything the day
    the presets became palette-only, they now compose with the separate
    light/dark choice instead of overriding it, so `midnight`/`daylight` became
    one `default` and no preset names a mode. A zero-match regex made this
    assert "the table has moved" while the table was sitting right there and
    the two copies agreed perfectly.
    """
    # **`theme-boot.js`, not index.html.** The block moved out of the page
    # when the last inline script was removed (the CSP kept refusing it, see
    # `test_static_freshness.py::test_the_page_has_no_inline_script_left`).
    # It is still the pre-paint copy and still has to match; only its file
    # changed. This test read index.html and, once the block left, reported
    # "the table has moved", which was true, and is exactly what it is for.
    boot = (INDEX.parent / "theme-boot.js").read_text(encoding="utf-8")
    settings = (INDEX.parent / "settings.js").read_text(encoding="utf-8")

    inline = set(re.findall(r"^\s{4}(\w+): \{ ", boot, re.M))
    declared = set(re.findall(r"^  (\w+): \{\n\s+label:", settings, re.M))

    assert inline, "the pre-paint theme table wasn't found: has it moved?"
    assert declared, "THEME_PRESETS wasn't found in settings.js, has it moved?"
    assert inline == declared, (
        "pre-paint themes and THEME_PRESETS disagree: "
        f"only in index.html={sorted(inline - declared)}, "
        f"only in settings.js={sorted(declared - inline)}"
    )


def test_every_theme_names_a_palette_that_exists():
    """A theme selecting a palette with no CSS silently renders as default."""
    # THEME_PRESETS moved to settings.js with the rest of appearance (§88.3
    # item 4): read from there now.
    app = (INDEX.parent / "settings.js").read_text(encoding="utf-8")
    css = css_text()

    used = set(re.findall(r'palette: "(\w+)"', app))
    defined = set(re.findall(r':root\[data-palette="(\w+)"\]', css))
    # "default" is the base :root, deliberately without a [data-palette] block.
    missing = sorted(used - defined - {"default"})
    assert not missing, f"themes select palettes with no CSS: {missing}"


def test_rediscover_never_offers_the_note_it_is_already_showing():
    """Reported as "the Another button is broken", and it was.

    The pick was uniform over every note WITH REPLACEMENT, so it could hand
    back the note already on screen and the click did nothing visible. Not
    rare: 1 in N, so a tenth of clicks on a ten-note notebook, half of them on
    two notes, and every single one when there is only one note to show.
    """
    # renderRandomNoteWidget moved to dashboard.js with the rest of the
    # dashboard widgets (§88.3's app.js split), and the shuffle it used to be
    # is now `renderRandomShuffle`: the widget leads with the scored notes
    # (WORLD_CLASS_PLAN 15, I4) and falls back to the shuffle under ten notes,
    # which is where this guard still belongs. Pointed at the function that
    # holds the behaviour rather than relaxed: the "Another" button is exactly
    # as broken as it ever was if it can hand back the note on screen.
    app = (INDEX.parent / "dashboard.js").read_text(encoding="utf-8")
    start = app.index("async function renderRandomShuffle(")
    body = app[start : start + 2200]
    assert "entries.filter(" in body, "the current note is not excluded from the pool"
    assert "current" in body


def test_rediscover_disables_another_when_there_is_nothing_else_to_show():
    """A live-looking button that cannot do anything is the exact shape of
    "this control is broken", trap 12, arriving by a new route."""
    # renderRandomShuffle holds the shuffle now, see the note above.
    app = (INDEX.parent / "dashboard.js").read_text(encoding="utf-8")
    start = app.index("async function renderRandomShuffle(")
    # The end of the function, not a fixed character count. A 2600-char window
    # was doing this job and a comment added inside the function pushed the
    # line being asserted past it, a lint that fails on prose is a lint people
    # learn to weaken.
    body = app[start : app.index("\n}\n", start)]
    assert "entries.length < 2" in body
    assert "disabled = true" in body


def test_a_widget_does_not_stack_class_names_on_every_render():
    """`className += " muted"` appends again each time the dashboard redraws."""
    app = (INDEX.parent / "app.js").read_text(encoding="utf-8")
    assert 'className += " muted"' not in app


APPEARANCE_KEY = re.compile(r'appearancePref\(\s*"([\w-]+)"')
DEFAULTS_BLOCK = re.compile(r"const APPEARANCE_DEFAULTS = \{(.*?)\n\};", re.S)
DEFAULT_KEY = re.compile(r'(?m)^\s*"?([\w-]+)"?\s*:')


def test_every_appearance_setting_has_a_default():
    """A missing default is not a missing default, it is the string
    "undefined" written into a CSS custom property.

    `applyAppearance` pipes these straight into `root.style.setProperty`, so a
    key absent from `APPEARANCE_DEFAULTS` reaches the stylesheet as literal
    `undefined` (or `NaN`, once it goes through `Number()`). That is invalid
    wherever it is *used*, not where it is set, so the damage lands far from
    the cause: `border-style` and `shadow-intensity` shipped without defaults,
    and between them took the border off every card, input, textarea, select
    and modal in the app, `border-style: var(--border-style) !important`
    matches all of those, and the shadow off every card, by poisoning the
    rgba() inside `--glass-shadow`. The app rendered flat and borderless on
    every fresh profile and nothing anywhere reported an error.
    """
    # APPEARANCE_DEFAULTS moved to settings.js with the rest of appearance
    # (§88.3 item 4): but appearancePref() itself is still called from a
    # handful of places in app.js too (renderEmblem's motion check, the
    # startup closure's theme/palette restore), so a key read only from
    # app.js has to be checked against the same table or this test would
    # miss exactly the class of bug it exists for.
    app = (INDEX.parent / "app.js").read_text(encoding="utf-8")
    settings = (INDEX.parent / "settings.js").read_text(encoding="utf-8")
    block = DEFAULTS_BLOCK.search(settings)
    assert block, "APPEARANCE_DEFAULTS wasn't found in settings.js, has it moved?"

    #: Settings whose "unset" state is meaningful, so a default would be wrong.
    #: `page-bg` unset means "let the palette supply the page", and
    #: `applyPageBackground` reads a falsy value as exactly that.
    OPTIONAL = {"page-bg"}

    declared = set(DEFAULT_KEY.findall(block.group(1)))
    used = set(APPEARANCE_KEY.findall(app)) | set(APPEARANCE_KEY.findall(settings))
    missing = sorted(used - declared - OPTIONAL)
    assert not missing, (
        "These appearance settings are read but have no entry in "
        f"APPEARANCE_DEFAULTS: {missing}. Each one resolves to undefined and is "
        "written into a CSS custom property as that word."
    )
