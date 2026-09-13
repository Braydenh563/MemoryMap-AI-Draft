"""A new session starts at the front of every tab (§ navigation).

Reported directly:

    "can you also make it so when the user begins a new session after logging
     into the app, it resets the navigation on all the tabs to the default
     subtabs?? Ive had times where I log into the app, click on the notes tab,
     and the tab is selected on 'Write with AI' instead of 'Your Notes'
     because that must have been what I was on last."

Which sub-tab you are on is not a preference; it is where you happen to be
standing. Reopening on the last *tab* is useful. Reopening three levels in, on
a sub-tab you visited once a week ago, reads as the app being in a state you
did not put it in.

These are lints: there is no DOM here. The behaviour itself was checked in a
browser: deep in Write with AI + Image Gallery → a reload keeps the place, a
lock/unlock and a fresh session both come back on Your Notes and All.
"""

from __future__ import annotations

from pathlib import Path

JS = Path("frontend/app.js").read_text(encoding="utf-8")


def test_a_reload_keeps_your_place_and_a_new_session_does_not():
    """`sessionStorage` draws exactly that line for free: it survives a reload
    and is cleared when the tab or the app window closes."""
    block = JS.split("function resetNavigationForNewSession()")[1].split("\n}")[0]
    assert "sessionStorage.getItem(SESSION_STARTED_KEY)" in block
    assert "sessionStorage.setItem(SESSION_STARTED_KEY" in block
    assert "return false" in block, "one-shot: a second call in the same session does nothing"


def test_storage_that_throws_leaves_the_old_behaviour():
    """A private window or a shell with site data blocked throws on access.
    Not resetting is the safe answer, the alternative is resetting on every
    single navigation."""
    block = JS.split("function resetNavigationForNewSession()")[1].split("\n}")[0]
    assert "catch" in block


def test_unlocking_also_resets():
    """The lock screen is an overlay, not a page: unlocking after an idle lock
    never reloads anything, so a load-time reset alone would leave every
    sub-tab where it was hours ago, which is the reported case."""
    block = JS.split("async function submitLockForm()")[1].split("\n}")[0]
    assert "resetNavigationToDefaults();" in block
    assert block.index("resetNavigationToDefaults();") < block.index("startApp();"), (
        "startApp is what reads the stored section back"
    )


def test_the_library_is_reset_through_its_own_click_handler():
    """Its switcher keeps state in the DOM (which button has `.active`), not
    in storage, so clearing a key cannot reach it, and re-implementing the
    handler's section-show, gallery-poll and whiteboard-landing logic here is
    exactly the shape this codebase keeps getting bitten by."""
    block = JS.split("function resetNavigationToDefaults()")[1].split("\n}\n")[0]
    assert 'data-target="library-view-documents"' in block
    assert ".click()" in block


def test_only_navigation_is_reset_not_display_preferences():
    """grid/list, the timeline's bucket, reminders' list/calendar and the
    editor's Live/Source are choices someone made on purpose."""
    keys = JS.split("const NAVIGATION_KEYS = [")[1].split("]")[0]
    assert "NOTES_SECTION_STORE" in keys
    # `timeline-scale` replaced `timeline-view` when the Timeline became one
    # feed with a bucket picker (TIMELINE_PLAN Phase 1): the preference it
    # keeps is which bucket, and it is a preference for the same reason.
    for preference in ("library-view", "timeline-scale", "reminderView", "DOC_VIEW_KEY"):
        assert preference not in keys, f"{preference} is a preference, not a position"


def test_the_reset_runs_before_the_notes_strip_reads_the_key():
    """Order matters: `initNotesSubtabs` calls `activeNotesSection()`, which
    reads the key this clears."""
    assert JS.index("resetNavigationForNewSession();") < JS.index("initNotesSubtabs();")
