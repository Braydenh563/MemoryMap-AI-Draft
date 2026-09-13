"""A tool's own label carries an icon, and the icon has to survive rendering.

**The convention.** Every AI tool result in `ai/tools/` writes a `label`
shaped `"ph:icon-name Some human sentence"`, `_merge_categories` produces
`ph:folder Merged “X” into “Y” (N notes moved)`, `_search` produces
`ph:magnifying-glass Searched notes for …`, and so on for the ~40 of them.
The `ph:` prefix is not decoration in the string: `setLabel()` (app.js)
parses it, builds a real `<i class="ph ph-folder">` element, and renders the
rest as text beside it.

**The bug this exists to stop.** Assign one of those strings with plain
`.textContent` instead and nothing errors, nothing logs, and the page shows
the icon spec as literal words, reported with a screenshot of three agent
rows each reading `ph:folder Merged “…” into “Hobbies”`. `changeRow()` did
exactly that, on both the initial render and the ", undone" rewrite after an
undo, while every neighbouring renderer (`toolChip`, `renderToolConfirm`)
went through `setLabel` correctly. One renderer out of step is invisible
until someone runs the one tool whose output it draws.

A source scan, like `test_frontend_ids.py` and
`test_frontend_workspace_header.py` next to it, and for the same reason:
this repo's Python suite cannot see the DOM, so the only place to hold the
rule is the source that builds it.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "app.js"
TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "memorymap" / "ai" / "tools"


def _change_row_source() -> str:
    """`changeRow`'s own body: the renderer for a skill/tool change line."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function changeRow(")
    # The next top-level `function ` declaration ends it; `changeRow` has no
    # nested top-level declarations of its own.
    end = source.index("\nfunction ", start + 1)
    return source[start:end]


def test_the_change_row_renders_its_label_through_set_label():
    body = _change_row_source()
    assert "setLabel(label," in body, (
        "changeRow must build its label with setLabel(), a plain textContent "
        "assignment prints the 'ph:icon-name' prefix as visible text"
    )
    assert "label.textContent =" not in body, (
        "a textContent assignment to the label element is back in changeRow; "
        "that is the exact shape that printed 'ph:folder Merged …' on screen"
    )


def test_the_undo_rewrite_also_keeps_the_icon():
    """The second half of the same bug: undoing a change rewrote the label to
    `…, undone` and, doing it with textContent, dropped the icon that had
    been rendering correctly a moment earlier."""
    body = _change_row_source()
    assert ", undone" in body, "the undone-state rewrite has moved or changed name"
    undone_line = next(line for line in body.splitlines() if ", undone" in line)
    assert "setLabel(" in undone_line, (
        "the ', undone' rewrite must go through setLabel too, or an undone row "
        "loses the icon the same row had before it was undone"
    )


def test_the_tools_really_do_emit_ph_prefixed_labels():
    """The premise the two tests above rest on, pinned down rather than
    assumed: if the tools ever stopped using this convention, those tests
    would keep passing while guarding nothing."""
    labels = []
    for path in TOOLS_DIR.glob("*.py"):
        labels += re.findall(r'"label":\s*\(?\s*f?"(ph:[a-z-]+)', path.read_text(encoding="utf-8"))
        labels += re.findall(r'\["label"\]\s*=\s*f?"(ph:[a-z-]+)', path.read_text(encoding="utf-8"))
    assert len(labels) > 10, (
        "expected the ai/tools/ modules to still write 'ph:icon-name …' labels; "
        f"found {len(labels)}"
    )
