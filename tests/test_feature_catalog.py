"""Every row in the two catalogues has to still reach real code.

The app lists what it can do in two places: the "Tools and features" browser
(`featureCatalog()` in dashboard.js) and the command palette
(`paletteCommands()` in app.js). Both are hand-written tables of
`{label, run}`, and a `run` is a closure: nothing in the browser, and nothing
in this suite, complains when the function it calls was renamed six months ago
or the element id it focuses was deleted with the markup around it. The row
goes on rendering, the person clicks it, and either nothing happens or the
console takes an exception nobody has open.

That is worse than a missing row. A catalogue is a promise about the app, and
the one failure mode it must not have is listing something that is not there.

Asked for with the audit that added the surfaces built since either table was
last touched: "Every row must be checked against real code (a row whose `run`
points at a dead id or a removed function is worse than a missing row) ... Add
a lint that fails when a catalog row names an id or function that does not
exist."

What it checks, per row, against the four lists the app itself keeps:

* `switchTab("x")` names a tab in `TABS` (app.js).
* `showNotesSection("x")` names a section in `NOTES_SECTIONS` (app.js).
* `openSettingsModal("x")` names a section in `SETTINGS_SECTIONS` (settings.js).
* `showDocSidebarSection("x")` names one in `DOC_SIDEBAR_SECTIONS` (documents.js).
* every `$("id")` and `getElementById("id")` exists in index.html, and every
  `[data-*="value"]` selector's value appears there too.
* every name called as a function, or handed to `run:` bare, is defined
  somewhere in the frontend, as a function, a binding, or a `window.` export.

`test_frontend_ids.py` already covers `$("id")` across the whole frontend, so
the id half of this is belt and braces; the function half is what nothing else
can see.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
INDEX = FRONTEND / "index.html"

#: Every script index.html loads, which is the scope a `run` resolves in: the
#: catalogues live in two of these files and call freely into the other seven,
#: because they are plain scripts sharing one global scope rather than modules.
SCRIPTS = (
    "app.js",
    "whiteboard.js",
    "graph.js",
    "graph-canvas.js",
    "documents.js",
    "library.js",
    "dashboard.js",
    "settings.js",
    "editor.js",
)

#: Names a row may call that are the platform rather than the app. Kept short
#: on purpose: anything else a row calls has to be findable in the frontend, so
#: a renamed helper fails here instead of in a browser.
BUILTINS = {
    #: Keywords that a naive "name followed by (" scan reads as calls:
    #: `async () => …`, `if (…)`, `catch (…)`.
    "async",
    "await",
    "catch",
    "else",
    "Boolean",
    "Event",
    "Number",
    "Promise",
    "String",
    "clearTimeout",
    "document",
    "fetch",
    "if",
    "for",
    "function",
    "parseInt",
    "requestAnimationFrame",
    "return",
    "setTimeout",
    "switch",
    "typeof",
    "while",
    "window",
}


def _read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Block and line comments out, strings left alone.

    The comments in this codebase quote code at length (they are the design
    record), so a naive scan reads a renamed function out of a paragraph
    explaining why it was renamed.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def _body(source: str, signature: str) -> str:
    """The body of one function, by brace matching from its signature."""
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def _without_strings(text: str) -> str:
    """Every string literal blanked out.

    A row's own copy is prose, and prose contains brackets: "The optional
    extras (OCR, speech, vision)" reads to a "name followed by (" scan as a
    call to a function named `extras`. Only the code half of a row can be
    checked for the names it calls, so the strings go first.
    """
    for pattern in (r'"[^"\n]*"', r"'[^'\n]*'", r"`[^`]*`"):
        text = re.sub(pattern, '""', text)
    return text


def _catalogues() -> dict[str, str]:
    """The two tables, with their comments stripped."""
    return {
        "featureCatalog (dashboard.js)": _strip_comments(
            _body(_read("dashboard.js"), "function featureCatalog() {")
        ),
        "paletteCommands (app.js)": _strip_comments(
            _body(_read("app.js"), "function paletteCommands() {")
        ),
    }


def _markup() -> str:
    return re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)


def _declared_names() -> set[str]:
    """Everything the frontend defines that a row could legitimately call."""
    names: set[str] = set()
    for script in SCRIPTS:
        source = _strip_comments(_read(script))
        names |= set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", source))
        names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", source))
        names |= set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=", source))
        #: Destructured bindings (`const {a, b} = …`): rare here, but a row
        #: calling one is still calling something real.
        for group in re.findall(r"\b(?:const|let|var)\s*\{([^}]*)\}\s*=", source):
            names |= {part.strip().split(":")[-1].strip() for part in group.split(",")}
    return {name for name in names if name}


def _list_literal(script: str, name: str) -> set[str]:
    """A `const NAME = ["a", "b"]` list, read out of the file that owns it."""
    source = _read(script)
    match = re.search(rf"\b{name}\s*=\s*\[(.*?)\]", source, flags=re.S)
    assert match, f"{name} is not declared in {script}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_every_catalogue_row_switches_to_a_tab_that_exists():
    tabs = _list_literal("app.js", "TABS")
    for where, body in _catalogues().items():
        for tab in re.findall(r'switchTab\("([^"]+)"\)', body):
            assert tab in tabs, f"{where}: switchTab({tab!r}) but TABS is {sorted(tabs)}"


def test_every_catalogue_row_opens_a_section_that_exists():
    sections = {
        ("showNotesSection", "app.js", "NOTES_SECTIONS"),
        ("openSettingsModal", "settings.js", "SETTINGS_SECTIONS"),
        ("showDocSidebarSection", "documents.js", "DOC_SIDEBAR_SECTIONS"),
    }
    for call, script, const in sections:
        known = _list_literal(script, const)
        for where, body in _catalogues().items():
            for name in re.findall(rf'{call}\("([^"]+)"', body):
                assert name in known, (
                    f"{where}: {call}({name!r}) but {const} is {sorted(known)}"
                )


def test_every_catalogue_row_names_an_element_that_exists():
    """Both the `$("id")` lookups and the `[data-x="y"]` selectors.

    The selectors matter as much as the ids: three rows reach a sub-tab by
    `querySelector('[data-target="library-view-whiteboard"]')`, and a renamed
    sub-tab leaves that returning null, which is a click that does nothing at
    all rather than an error.
    """
    markup = _markup()
    ids = set(re.findall(r'\bid="([^"]+)"', markup))
    for where, body in _catalogues().items():
        for element in re.findall(r'\$\("([\w-]+)"\)', body) + re.findall(
            r'getElementById\("([\w-]+)"\)', body
        ):
            assert element in ids, f"{where}: $({element!r}) is in no element in index.html"
        for attribute, value in re.findall(r'\[(data-[\w-]+)="([^"]+)"\]', body):
            assert f'{attribute}="{value}"' in markup, (
                f'{where}: no element has {attribute}="{value}"'
            )


def test_every_catalogue_row_calls_a_function_that_exists():
    """The half nothing else can see.

    A row's `run` is dead code until someone clicks it, so a function renamed
    in one file and still named in a catalogue in another is invisible until a
    person goes looking for the feature and finds that it does nothing.
    """
    declared = _declared_names() | BUILTINS
    for where, body in _catalogues().items():
        code = _without_strings(body)
        called = set(re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(", code))
        #: `run: openSketch,` and `run: toggleTheme,`: handed over rather than
        #: called, and just as dead if the name has moved.
        called |= set(re.findall(r"run:\s*([A-Za-z_$][\w$]*)\s*[,}]", code))
        #: `window.openPageReader?.()`: the optional call is how a row reaches
        #: a function in a file that may not have loaded yet, and the name
        #: still has to be exported somewhere.
        called |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\??\.?\(", code))
        missing = sorted(name for name in called if name not in declared)
        assert not missing, (
            f"{where} calls names that are defined nowhere in the frontend: "
            f"{missing}. A row that points at a removed function is worse than "
            "a missing row: fix the row, or delete it if the feature is gone."
        )


def test_no_two_rows_claim_the_same_thing():
    """One feature, one row.

    Two rows with the same name is how a catalogue that is edited by adding to
    the end starts double-counting: the heading counts rows, so a duplicate
    inflates the number the dialog puts in front of the reader.
    """
    body = _catalogues()["featureCatalog (dashboard.js)"]
    names = re.findall(r'\{\s*name:\s*"([^"]+)"', body)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"these feature names appear more than once: {duplicates}"

    labels = re.findall(r'label:\s*"([^"]+)"', _catalogues()["paletteCommands (app.js)"])
    #: The palette's labels carry their icon, so they are compared whole.
    repeated = sorted({label for label in labels if labels.count(label) > 1})
    assert not repeated, f"these palette commands appear more than once: {repeated}"


def test_the_count_in_the_heading_is_counted_not_typed():
    """The number is the list's own length, or it is a number that drifts.

    "105 things MemoryMap can do" was accurate on the day it was written. It is
    computed from the rendered rows (`shown` in `renderFeatures`), and this
    keeps it that way: a literal in that string would be a promise the file
    stops keeping the moment a row is added.
    """
    source = _strip_comments(_read("dashboard.js"))
    heading = re.search(r"features-count[^;]*?;", source, flags=re.S)
    assert heading, "the features dialog no longer sets #features-count"
    assert "${shown}" in heading.group(0), (
        "the heading must count the rows it just rendered, not carry a number"
    )
    assert not re.search(r"\b\d{2,}\s+things MemoryMap can do", source), (
        "the count in the heading is hard-coded; it has to come from the list"
    )
