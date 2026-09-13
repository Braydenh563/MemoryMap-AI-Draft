"""The dashboard layout's stored lists must be able to hold every widget.

**A lint, not a behaviour test**, and it exists because the behaviour test
nobody wrote would have caught this a long time ago: `DashboardLayout.order`
carries *every* widget, visible and hidden, and its cap was `max_length=20`
while the dashboard had grown to twenty-five. Every save of a full layout came
back `422`, `saveDashLayout` swallowed the failure by design (a dead preference
must not break the page), and the visible symptom was that reordering a widget
simply did nothing: reported as the widget manager needing a redesign rather
than as a broken request.

The catalogue lives in JavaScript and the cap lives in Python, so nothing else
in this codebase can notice them drifting apart. This can.
"""

from __future__ import annotations

import re
from pathlib import Path

from memorymap.api.routes_settings import DASHBOARD_LAYOUT_MAX

DASHBOARD_JS = Path(__file__).resolve().parents[1] / "frontend" / "dashboard.js"


def widget_names() -> list[str]:
    """The keys of `DASH_WIDGETS`, read out of the source.

    Parsed rather than imported for the obvious reason, there is no
    JavaScript runtime in this suite, and the pattern is deliberately narrow:
    a key at one level of indentation whose value opens with `{ title:`. A
    looser match would count object literals nested inside a renderer and
    report a catalogue larger than the one that exists.
    """
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    start = source.index("const DASH_WIDGETS = {")
    end = source.index("\n};", start)
    block = source[start:end]
    return re.findall(r"^  ([A-Za-z0-9_]+): \{ title:", block, re.MULTILINE)


def test_the_catalogue_was_actually_found():
    """A regex that matched nothing would make every assertion below pass."""
    names = widget_names()
    assert len(names) > 10
    assert "stats" in names and "streak" in names


def test_the_cap_can_hold_every_widget():
    """The failure this file exists for: a layout listing every widget must be
    storable, or rearranging the dashboard cannot be saved at all."""
    assert len(widget_names()) <= DASHBOARD_LAYOUT_MAX


def test_the_cap_leaves_room_to_add_more():
    """Not `==`: a cap exactly the size of the catalogue would fail on the very
    next widget, which is the same bug again with a different number. Ten spare
    slots is several sessions of headroom, and the assertion says plainly when
    it is time to raise the bound rather than discovering it through a 422."""
    assert len(widget_names()) + 10 <= DASHBOARD_LAYOUT_MAX
