"""Every control dock follows the dock grammar (UI_MODERNISATION_PLAN.md, Phase 8).

A dock is the control row at the top of a tab or sub-tab. The plan states one
grammar for all of them, identity, then find, then arrange, then actions , 
and this lint holds the parts of it that can be read from the markup:

- **Zone order.** Whatever zones a dock has appear in the order identity →
  find → arrange → actions, and each at most once.
- **One primary.** At most one filled button (a `<button>` with neither
  `ghost` nor `icon-only`) per dock. A second filled button is the "two
  answers to what this row is for" defect the plan names. "In the dock" here
  means the same thing the stylesheet means by it: a direct child of a zone,
  the run of controls `.dock > * > button` sizes. A clickable chip nested
  further in (the Chat header's model badge and context pill live inside the
  headline, as metadata you can press) is not in that run and is not a
  primary; keeping the lint and the stylesheet on one definition is what
  stops the two drifting.
- **Settings live in menus.** No checkbox or radio directly in a dock zone, 
  a switch is a setting, and belongs in a popover or in Settings. Inside a
  `.dock-menu` they are fine (that is what the View menu is for).
- **Utilities in a fixed order, last.** Within `.dock-actions`, after the
  primary: refresh, help, more: never help before refresh, never the kebab
  before either. A utility is recognised by its id (`*-refresh`,
  `*-help-toggle`) or class (`dock-more`).
- **No text-only segmented controls in a zone.** A `.seg`/`.segmented-control`
  in a dock zone must carry an icon per option or be inside a menu; the plan
  keeps segments for *view* and gives them icons. A segment's own cells are
  not counted as primaries: the fill on a segment *is* its selected state,
  not a call to action, so "one primary" is about the buttons beside it.

Like the other frontend lints this cannot see the DOM; `scratchpad/ui-sweeps/
docks.js` measures the same docks against a running app (one height per
dock, ≤ 7 visible controls per row). Docks join the lint by carrying
`data-dock-name="<name>"`, so a surface that has not been brought onto the grammar
yet is not failed for it, the ratchet is the count of docks that carry it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"

ZONES = ["dock-identity", "dock-find", "dock-arrange", "dock-actions"]

#: Docks that have been brought onto the grammar. Add a name here when a
#: surface lands; the test below fails if the markup and this list disagree,
#: so the ratchet cannot silently loosen.
ON_THE_GRAMMAR = {
    "chat",
    "graph",
    "library",
    "library-boards",
    "library-contents",
    "library-docs",
    "library-links",
    "library-media",
    "library-skills",
    "notes",
    "timeline",
    "reminders",
    # The one dock that is not a tab head: the Settings screen's Logs console,
    # reported as the last control row still built by hand. It lives inside the
    # settings modal, which is why `scratchpad/ui-sweeps/docks.js` (which walks
    # the seven tabs) does not see it and `logsdock.js` measures it instead.
    "settings-logs",
}


class _Segment:
    """One segmented control sitting directly in a dock zone."""

    def __init__(self, name: str, ident: str):
        self.dock = name
        self.id = ident or "(no id)"
        self.options = 0
        self.with_icon = 0


class _Dock:
    def __init__(self, name: str):
        self.name = name
        self.zones: list[str] = []
        self.filled: list[str] = []
        self.loose_switches: list[str] = []
        self.utilities: list[str] = []
        self.segments: list[_Segment] = []


class _Parser(HTMLParser):
    """A small stack walker: enough to know, for each element, which dock,
    which zone and whether a `.dock-menu` encloses it."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict] = []
        self.docks: list[_Dock] = []
        self.void = {"input", "img", "br", "hr", "meta", "link"}

    def _classes(self, attrs) -> set[str]:
        return set((dict(attrs).get("class") or "").split())

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = self._classes(attrs)
        frame = {"tag": tag, "classes": classes, "id": a.get("id") or "", "dock": None}
        if "data-dock-name" in a:
            dock = _Dock(a["data-dock-name"])
            self.docks.append(dock)
            frame["dock"] = dock
        self.stack.append(frame)
        dock = next((f["dock"] for f in reversed(self.stack) if f["dock"]), None)
        if dock is None:
            if tag not in self.void:
                pass
            else:
                self.stack.pop()
            return
        in_menu = any("dock-menu" in f["classes"] for f in self.stack[:-1])
        zone = next((z for z in ZONES if z in classes), None)
        if zone:
            dock.zones.append(zone)
        current_zone = next(
            (z for f in reversed(self.stack) for z in ZONES if z in f["classes"]), None
        )
        # Whether this element is a *direct* child of its zone, which is the
        # stylesheet's own test for "in the control run" (`.dock > * > button`).
        parent = self.stack[-2] if len(self.stack) > 1 else None
        in_run = bool(parent) and any(z in parent["classes"] for z in ZONES)
        # A cell of a segmented control is not a primary, and this had to be
        # said explicitly: `.seg button` is transparent by design (the fill is
        # the *selected* state), so a segment carries neither `ghost` nor, once
        # its options have words beside their icons, `icon-only`. Counting its
        # cells as filled buttons failed Contents for having four ways to group
        # an index, which is not the "two answers to what this row is for"
        # defect this test is here to catch. The docstring's own segment rule
        # is now a test as well, one line below.
        in_seg = any(
            "seg" in f["classes"] or "segmented-control" in f["classes"]
            for f in self.stack[:-1]
        )
        if not in_menu and current_zone:
            if (
                tag == "button"
                and in_run
                and not in_seg
                and "ghost" not in classes
                and "icon-only" not in classes
            ):
                dock.filled.append(a.get("id") or "(no id)")
            if tag == "input" and a.get("type") in ("checkbox", "radio"):
                dock.loose_switches.append(a.get("id") or a.get("name") or "(no id)")
            if ("seg" in classes or "segmented-control" in classes) and tag != "summary":
                dock.segments.append(_Segment(dock.name, a.get("id") or ""))
            if tag == "button" and in_seg and dock.segments:
                dock.segments[-1].options += 1
            if tag == "i" and in_seg and dock.segments:
                if any(c == "ph" or c.startswith("ph-") for c in classes):
                    dock.segments[-1].with_icon += 1
        if current_zone == "dock-actions" and not in_menu:
            ident = a.get("id") or ""
            if ident.endswith("-refresh"):
                dock.utilities.append("refresh")
            elif ident.endswith("-help-toggle"):
                dock.utilities.append("help")
            elif "dock-more" in classes:
                dock.utilities.append("more")
        if tag in self.void:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return


def _docks() -> list[_Dock]:
    text = re.sub(r"<!--.*?-->", "", INDEX.read_text(encoding="utf-8"), flags=re.S)
    parser = _Parser()
    parser.feed(text)
    return parser.docks


def test_every_dock_on_the_grammar_is_marked_and_vice_versa():
    names = {d.name for d in _docks()}
    assert names == ON_THE_GRAMMAR, (
        f"docks in the markup: {sorted(names)}; docks this lint expects: "
        f"{sorted(ON_THE_GRAMMAR)}: update ON_THE_GRAMMAR when a surface lands"
    )


@pytest.mark.parametrize("dock", _docks(), ids=lambda d: d.name)
def test_zones_are_in_order_and_unique(dock):
    assert len(dock.zones) == len(set(dock.zones)), f"{dock.name}: a zone appears twice"
    order = [ZONES.index(z) for z in dock.zones]
    assert order == sorted(order), f"{dock.name}: zones out of order: {dock.zones}"


@pytest.mark.parametrize("dock", _docks(), ids=lambda d: d.name)
def test_one_primary_action(dock):
    assert len(dock.filled) <= 1, f"{dock.name}: more than one filled button: {dock.filled}"


@pytest.mark.parametrize("dock", _docks(), ids=lambda d: d.name)
def test_switches_live_in_menus(dock):
    assert not dock.loose_switches, (
        f"{dock.name}: a checkbox/radio sits directly in a dock zone: {dock.loose_switches}"
    )


def _segments():
    return [s for d in _docks() for s in d.segments]


@pytest.mark.parametrize("seg", _segments(), ids=lambda s: f"{s.dock}:{s.id}")
def test_segments_in_a_zone_carry_an_icon_per_option(seg):
    """The docstring's segment rule, which was described and never asserted.

    A segmented control in a dock means *view*, and the plan gives it icons so
    that four ways of drawing one list read as one control rather than as four
    words someone left in the row. Words may sit beside the icons; what is
    refused is an option with no icon at all.
    """
    assert seg.options, f"{seg.dock}:{seg.id}: a segment with no options"
    assert seg.with_icon >= seg.options, (
        f"{seg.dock}:{seg.id}: {seg.options} options but only {seg.with_icon} "
        "carry an icon; a segment in a dock zone gives every option one"
    )


@pytest.mark.parametrize("dock", _docks(), ids=lambda d: d.name)
def test_utilities_keep_their_order(dock):
    expected = ["refresh", "help", "more"]
    seen = [u for u in expected if u in dock.utilities]
    assert dock.utilities == seen, (
        f"{dock.name}: utilities are {dock.utilities}; the order is refresh · help · more"
    )
