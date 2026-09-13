"""No two keyboard shortcuts may claim the same chord.

This has now gone wrong twice, the same way both times, and neither time was
caught by anything but a person pressing the keys.

The agent bar ("ask the agent anything") bound its chord in a
`document.addEventListener("keydown", …)` of its own rather than in
`DEFAULT_SHORTCUTS`. It first collided with the navigation palette on Ctrl+K, 
both overlays opened at once, and the agent bar, being later in the DOM, ate
every click meant for the palette underneath. The fix moved it to
Ctrl+Shift+K. That is the sketch pad's chord, and it had been since the
shortcut was added, so the fix swapped one silent collision for another and
Ctrl+Shift+K then opened the sketch pad *and* the agent bar together
(reported by the user, again by pressing the keys).

Nothing about either collision was visible in review: the two bindings were
hundreds of lines apart and one of them was not in the table you would read
to check. A browser will happily run both handlers, and the Python suite
cannot see the DOM, so this parse of the table is the cheapest thing that
can fail the build on the next one.

The rule this encodes, and the reason the fix was not just "pick another
letter": **every chord belongs in `DEFAULT_SHORTCUTS`.** A chord bound
anywhere else is invisible to this test, so a loose binding is the bug even
when it happens not to collide today.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.js"

#: `id: { keys: "Ctrl+Shift+K", label: … }`, the one shape every entry in
#: DEFAULT_SHORTCUTS uses.
ENTRY = re.compile(r'^\s*(\w+):\s*\{\s*keys:\s*"([^"]+)"', re.MULTILINE)


def _default_shortcuts() -> dict[str, str]:
    source = APP.read_text(encoding="utf-8")
    start = source.index("const DEFAULT_SHORTCUTS")
    # The table's closing "};" at the start of a line, every entry inside is
    # indented, so this cannot stop early on a nested object.
    end = source.index("\n};", start)
    return {name: keys for name, keys in ENTRY.findall(source[start:end])}


def test_the_table_was_actually_found():
    """A regex that silently matches nothing would make every test below
    pass while checking exactly nothing, the failure mode worth guarding in
    a test that is itself a parse."""
    table = _default_shortcuts()
    assert len(table) > 15, table
    assert table["quickSketch"] == "Ctrl+Shift+K"


def test_no_two_shortcuts_share_a_chord():
    table = _default_shortcuts()
    clashes = {keys: n for keys, n in Counter(table.values()).items() if n > 1}
    assert not clashes, (
        "These chords are bound to more than one action:\n"
        + "\n".join(
            f"  {keys}: {', '.join(i for i, k in table.items() if k == keys)}"
            for keys in clashes
        )
    )


def test_the_agent_bar_does_not_bind_its_own_chord():
    """The specific loose binding both collisions came from. It is now
    `runShortcut("askAgent")`; a `keydown` listener testing for a modifier
    combination anywhere near the command palette means it has grown one
    back."""
    source = APP.read_text(encoding="utf-8")
    start = source.index("--- Global Command Palette")
    region = source[start : start + 4000]
    offenders = [
        line.strip()
        for line in region.splitlines()
        if re.search(r"(ctrlKey|metaKey).*(shiftKey|e\.key)", line)
    ]
    assert not offenders, (
        "The agent bar is binding a chord directly again, put it in "
        "DEFAULT_SHORTCUTS instead, or this test cannot see it:\n"
        + "\n".join(f"  {line}" for line in offenders)
    )


def test_every_shortcut_has_an_action():
    """A chord in the table with no branch in `runShortcut` is a key that
    does nothing: and the shortcuts help screen still advertises it."""
    source = APP.read_text(encoding="utf-8")
    start = source.index("function runShortcut(")
    # Both spellings the object uses: `quickSketch: openSketch,` and the
    # ES6 shorthand `toggleTheme,`. Matching only the first is what made an
    # earlier draft of this test report a perfectly wired shortcut as dead.
    region = source[start : start + 6000]
    actions = set(re.findall(r"^\s*(\w+)\s*[:,]", region, re.MULTILINE))
    missing = sorted(set(_default_shortcuts()) - actions)
    assert not missing, f"Shortcuts with no action: {missing}"
