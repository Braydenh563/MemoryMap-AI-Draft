"""The text-selection kebab, and the DOM-weight fix beside it.

These are lints over `frontend/app.js`, not behaviour tests: the same kind
`test_frontend_handlers.py` and `test_frontend_ids.py` already are, and for the
same reason: this Python suite cannot see a DOM, so the only thing it can
usefully guard is that the source still has the shape the live verification
proved correct. What was verified live in Chromium (and is recorded in
HANDOVER.md rather than here): the kebab appears, its menu stays inside the
viewport at 360x640 by flipping up and left, `Ctrl+Shift+E` opens it from a
keyboard selection, arrow keys move through it, "Save as a note" creates a note
and the global undo removes it again, and the note-card menus hold 0 items
until opened and 20 after.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "app.js"
CSS_DIR = Path(__file__).resolve().parents[1] / "frontend" / "css"


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _all_css() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(CSS_DIR.glob("*.css")))


def test_the_note_menu_is_not_built_until_it_is_opened():
    """The whole point of the change. `entryItem` builds one overflow menu per
    note and the Notes list renders the entire notebook, so an eagerly-built
    menu is ~68 DOM nodes times every note you own, measured live at 1,501
    notes as 133,748 nodes eager against 31,680 lazy.

    Guarded by shape rather than by count: the opener's handler has to call
    `fillMenu()` before `openActionMenu`, or the menu opens empty.
    """
    source = _app_js()
    start = source.index("function entryOverflowMenu(")
    body = source[start : start + 2000]
    assert "fillMenu();" in body, "the opener no longer fills the menu before opening it"
    assert body.index("fillMenu();") < body.index("openActionMenu(menu, opener)")


def test_the_selection_popup_clamps_the_right_way_round():
    """The bug this replaced: `Math.min(Math.max(margin, x), limit)` puts a box
    wider than the viewport *off* the left edge, because the limit falls below
    the floor and `min` wins. `Math.max(margin, Math.min(x, limit))` pins it to
    the margin instead. The nesting order is the entire fix, so it is what is
    asserted."""
    source = _app_js()
    start = source.index("function showSelectionPopupAt(")
    body = source[start : source.index("function selectionIsActionable(")]
    assert "Math.max(\n    margin,\n    Math.min(" in body, "left clamp is nested the wrong way round"
    assert "const top = Math.max(" in body, "top clamp is nested the wrong way round"


def test_the_selection_popup_can_be_reached_without_a_mouse():
    """It used to listen for `mouseup` and nothing else, which left it
    unreachable by touch (a long-press drag dispatches `selectionchange`) and
    by keyboard (Shift+Arrow dispatches neither)."""
    source = _app_js()
    assert 'document.addEventListener("selectionchange"' in source
    assert "selectionActions: openSelectionMenuFromKeyboard" in source
    assert 'selectionActions: { keys: "Ctrl+Shift+E"' in source


def test_the_new_shortcut_does_not_collide_with_an_existing_one():
    """Two features sharing one shortcut has happened here before, Ctrl+K was
    bound twice (ROADMAP Tier 1, item 13)."""
    source = _app_js()
    block = source[source.index("const DEFAULT_SHORTCUTS = {") :]
    block = block[: block.index("\n};")]
    keys = [line.split('keys: "')[1].split('"')[0] for line in block.splitlines() if 'keys: "' in line]
    assert len(keys) == len(set(keys)), f"duplicate shortcut binding among {keys}"


def test_both_ends_of_a_selection_are_checked_against_the_denylist():
    """Testing only `anchorNode` let a drag that started in prose and ended in
    a textarea (or the reverse) still raise the popup over a form field."""
    source = _app_js()
    start = source.index("function selectionIsActionable(")
    body = source[start : start + 600]
    assert "selection.anchorNode" in body and "selection.focusNode" in body


def test_menu_keyboard_navigation_is_shared_rather_than_owned_by_one_menu():
    """It lived inline inside `entryOverflowMenu`, so every menu built by
    `kebabMenu`, conversations, sidebars, and the selection menu, had no
    arrow keys at all. Found by driving the selection menu from the keyboard."""
    source = _app_js()
    assert "function wireMenuKeyboard(" in source
    assert source.count("wireMenuKeyboard(menu, opener)") >= 2, (
        "both kebabMenu and entryOverflowMenu should use the shared handler"
    )


def test_the_selection_popup_sits_above_the_persistent_panels():
    """Found live: at 360x640 the kebab rendered in the right place and was
    still unclickable, because `#agent-monitor` (z-index 1000) covered it.
    It must stay below the toast box (1050), which has to outrank everything."""
    # Comments stripped first: the rule carries a long one that names the very
    # z-index values being asserted on, and a naive split reads those instead.
    css = re.sub(r"/\*.*?\*/", "", _all_css(), flags=re.S)
    block = css[css.index(".selection-popup {") :]
    block = block[: block.index("}")]
    z = int(block.split("z-index:")[1].split(";")[0].strip())
    assert 1000 < z < 1050, f"selection popup z-index {z} is not between the panels and the toasts"


def test_the_popup_button_rule_does_not_swallow_the_menu_items():
    """`.selection-popup button` (0,1,1) beat `.menu-item` (0,1,0), so the
    menu's rows silently inherited the old toolbar's padding and `nowrap`."""
    css = _all_css()
    assert ".selection-popup > .menu-wrap > button {" in css
    assert "\n.selection-popup button {" not in css


def test_the_clipping_helper_quotes_and_attributes():
    """A clipping is somebody else's words; a notebook that cannot tell them
    from yours is worse than one that refuses clippings (BACKLOG.md §65)."""
    source = _app_js()
    start = source.index("function clippingMarkdown(")
    body = source[start : source.index("async function saveSelectionAsNote(")]
    assert "`> ${line}`" in body, "the passage is no longer quoted"
    assert "](${source.url})" in body, "the source is no longer linked"


def test_every_shortcut_has_something_to_run():
    """A binding with no entry in `runShortcut` is CLAUDE.md's shape 2 exactly:
    not buggy, never executed, `actions[id]?.()` swallows it in silence, so
    the key appears in the Settings list, rebinds happily, and does nothing.
    Checked here because the section was expanded from ten bindings to
    seventeen in one sitting."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    defaults = source.split("const DEFAULT_SHORTCUTS = {")[1].split("\n};")[0]
    ids = re.findall(r"^\s{2}(\w+):\s*\{ keys:", defaults, flags=re.M)
    assert len(ids) >= 17, ids

    actions = source.split("function runShortcut(id) {")[1].split("\n  actions[id]")[0]
    for name in ids:
        assert re.search(rf"\b{name}[,:]", actions), f"{name} has no action"
