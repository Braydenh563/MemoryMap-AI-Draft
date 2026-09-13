"""Where events go once their moment has passed (§36E).

MemoryMap already *produces* all of these, a reminder comes due, a background
job finishes, a run stops early, and shows each in its own way: a system
notification, a toast, a step timeline. Every one of those is a moment, and
missing the moment used to mean the event was gone. A long install finishing
minutes after you stopped watching left its only record on a screen inside
Settings that you had to know to open.

This is a lint, not a behaviour test, the store is `localStorage` and the
panel is DOM, neither of which this suite can see. What it pins is the shape:
the wiring exists, the honest caveat is on screen, and the two places that
would silently break it (an unguarded save before the unlock, and a panel that
inherits `nowrap` from the header) stay fixed. Both of those were real, and
both were found by looking at the running app rather than at the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._css_paths import css_text

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
STYLE = css_text()


def test_the_centre_exists_and_is_reachable_from_every_tab():
    """In the header, not in a tab: an event can arrive while you are anywhere,
    and a notification you have to go somewhere to find is one you never see."""
    assert 'id="notif-btn"' in INDEX
    assert 'id="notif-panel"' in INDEX
    assert 'id="notif-list"' in INDEX
    header = INDEX.split('<div class="header-controls">', 1)[1].split("</header>", 1)[0]
    assert 'id="notif-btn"' in header


@pytest.mark.parametrize(
    "producer",
    [
        # A reminder coming due.
        'kind: "reminder"',
        # A background job finishing, the one whose record was hardest to find.
        'kind: item.outcome === "failed" ? "error" : "task"',
        # A run that stopped early.
        'kind: "run"',
    ],
)
def test_every_event_the_app_produces_is_recorded(producer):
    assert producer in APP_JS


def test_recording_is_de_duplicated():
    """The reminder poll runs every thirty seconds and the task list re-renders
    every three; without a key, one due reminder becomes a hundred rows."""
    assert "if (key && items.some((n) => n.id === id)) return;" in APP_JS


def test_the_store_is_bounded():
    """A ring buffer, not a log file."""
    assert "MAX_NOTIFICATIONS" in APP_JS
    assert "items.slice(-MAX_NOTIFICATIONS)" in APP_JS


def test_the_panel_folds_in_what_is_overdue_on_the_server():
    """The one case an event log cannot cover: a reminder that came due while
    nothing was running to notice. The reminders table knows regardless."""
    opener = APP_JS.split("async function openNotifications(", 1)[1][:2000]
    assert 'apiJson("/reminders"' in opener


def test_the_save_waits_for_the_unlock():
    """§35E-bis found exactly this in the reminder poll: a request fired before
    the unlock is a guaranteed 401 on every cold load, and it reads in the
    server's log as an auth failure worth investigating. Reintroduced by the
    settings mirror, the tab restore writes `activeTab` at module level, and
    caught by watching the network in a browser."""
    saver = APP_JS.split("function saveUiState()", 1)[1][:900]
    assert "if (!authToken()) return;" in saver


def test_the_panel_does_not_inherit_nowrap_from_the_header():
    """`.header-controls` sets `white-space: nowrap` so "⚙ Settings" cannot
    break in two and make the bar taller. Right for the buttons, wrong for a
    panel of prose hanging off one: every title ran off the right edge on a
    single unwrappable line and was clipped mid-word."""
    block = re.search(r"\.notif-panel \{(.*?)\n\}", STYLE, re.S)
    assert block and "white-space: normal" in block.group(1)


def test_it_does_not_promise_what_a_local_first_app_cannot_do():
    """§36C's honest note, on screen rather than only in the roadmap."""
    assert "Nothing fires while MemoryMap is closed" in INDEX
