"""No element gets its click handler bound twice (roadmap §36D).

Found by accident while making Quit reachable: `$("app-quit").addEventListener`
appeared twice, and so did `$("task-history-clear").addEventListener`. Both
copies had been spliced into the *middle of `renderChatModeSeg()`* by an
editing accident.

That parsed, so nothing complained, but `renderChatModeSeg` runs on every
chat-mode change, so each call bound another listener to both buttons. Clicking
Quit after switching modes a few times opened that many confirm dialogs and
fired that many shutdown requests.

The class of bug is worth a check for the same reason `test_frontend_ids.py`
exists: browsers do not warn, no linter runs on this file, and the Python suite
cannot see the DOM. A duplicate registration is silent until it is several
dialogs deep.

It also catches the genuinely dangerous version, a listener bound inside a
function that runs more than once, which accumulates without bound.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.js"
WHITEBOARD = Path(__file__).resolve().parents[1] / "frontend" / "whiteboard.js"
GRAPH = Path(__file__).resolve().parents[1] / "frontend" / "graph.js"
GRAPH_CANVAS = Path(__file__).resolve().parents[1] / "frontend" / "graph-canvas.js"
EDITOR = Path(__file__).resolve().parents[1] / "frontend" / "editor.js"
DOCUMENTS = Path(__file__).resolve().parents[1] / "frontend" / "documents.js"
LIBRARY = Path(__file__).resolve().parents[1] / "frontend" / "library.js"
DASHBOARD = Path(__file__).resolve().parents[1] / "frontend" / "dashboard.js"
SETTINGS = Path(__file__).resolve().parents[1] / "frontend" / "settings.js"

#: Two listeners on one element for one event is fine when they do different
#: jobs: the settings overlay has a backdrop-click-to-close and a delegated
#: cross-link handler, and both are correct. What is never fine is a
#: registration that can run more than once, so that is what this checks.
#: (element, event) pairs that legitimately have two handlers, and why.
ALLOWED_DOUBLES = {
    # Two different jobs on the same overlay, both registered once: closing on
    # a backdrop click, and delegating clicks on the "that setting lives over
    # there" cross-links inside it.
    ("settings-modal", "click"),
    # Two unrelated jobs on the capture box, both registered once: driving the
    # `[[wiki link]]` autocomplete, and keeping the character count and the
    # draft in localStorage. Merging them would couple a text-editing aid to a
    # persistence concern for no gain.
    ("entry-content", "input"),
}

BINDING = re.compile(r'\$\("([\w-]+)"\)\??\.addEventListener\(\s*"(\w+)"')


def _source() -> str:
    """app.js, whiteboard.js and graph.js, with block comments left alone.

    The whiteboard subsystem (board/card CRUD, sketch drawing, export,
    move/resize) moved out of app.js into its own file, loaded by a second
    <script> tag, and the graph view (force-directed map, layouts, tracing,
    the node popup) moved out into a third, see index.html, so a
    duplicate-registration bug inside either, or a registration split across
    files, needs all of them scanned together to be caught. editor.js (the
    "/" menu and block frames) is the fourth, documents.js (the document
    editor itself, split out of app.js, §10 of the app.js-split plan) is the
    fifth, library.js (the Library tab, split out of *both* app.js and
    whiteboard.js: §88.3) is the sixth, dashboard.js (widgets, masonry,
    the generative art: §88.3) is the seventh, and settings.js (the settings
    modal, the logs console, and appearance, §88.3, the fourth and last file
    in the split) is the eighth, and graph-canvas.js (the Canvas 2D graph
    renderer and its worker plumbing, GRAPH_PLAN.md §5 Phase 1) is the
    ninth: the reason this list has to grow with the split rather than
    being left at however many files it started with: a lint that cannot
    see a file cannot catch anything in it.

    Only comments are stripped: a `$("x").addEventListener` inside a comment is
    documentation of the pattern, not a second registration, this test's own
    docstring would otherwise be quoted back at it.
    """
    combined = (
        APP.read_text(encoding="utf-8")
        + "\n"
        + WHITEBOARD.read_text(encoding="utf-8")
        + "\n"
        + GRAPH.read_text(encoding="utf-8")
        + "\n"
        + GRAPH_CANVAS.read_text(encoding="utf-8")
        + "\n"
        + EDITOR.read_text(encoding="utf-8")
        + "\n"
        + DOCUMENTS.read_text(encoding="utf-8")
        + "\n"
        + LIBRARY.read_text(encoding="utf-8")
        + "\n"
        + DASHBOARD.read_text(encoding="utf-8")
        + "\n"
        + SETTINGS.read_text(encoding="utf-8")
    )
    return re.sub(r"/\*.*?\*/", "", combined, flags=re.S)


def test_no_element_is_bound_to_the_same_event_twice():
    """The check that would have caught it.

    I first tried a stricter rule, that every `$("id").addEventListener` sits
    at the top level, since the two broken ones were nested. That is not this
    codebase's convention: plenty of handlers are registered inside init
    functions that run exactly once, and flagging those would be noise that
    gets suppressed rather than read.

    So the rule is the narrower true one: **the same element bound to the same
    event in two places.** That is what `app-quit` and `task-history-clear`
    were, and it is nearly always either a copy-paste or an editing accident.
    Where two handlers for one event genuinely do different jobs, the pair goes
    in ALLOWED_DOUBLES with the reason, and writing the reason is the point.
    """
    doubles = {
        pair: n for pair, n in Counter(BINDING.findall(_source())).items() if n > 1
    }
    unexplained = {p: n for p, n in doubles.items() if p not in ALLOWED_DOUBLES}
    assert not unexplained, (
        "These elements are bound to the same event in two places:\n  "
        + "\n  ".join(f'$("{el}").addEventListener("{ev}") × {n}' for (el, ev), n in unexplained.items())
        + "\n\nEach registration fires. If one of them sits inside a function "
        "that runs more than once, they accumulate without bound, which is "
        "what Quit did, opening one confirm dialog per chat-mode change.\n"
        "If both are deliberate, add the pair to ALLOWED_DOUBLES with why."
    )


def test_quit_is_reachable_without_opening_settings():
    """"Make the quit app button more available and easy to access rather than
    just being buried in settings." Closing an app is a top-level action, and
    four clicks into a settings panel is the one place nobody looks, most of
    all in the desktop window, where closing the window is not the same thing
    as stopping the server behind it."""
    markup = (APP.parent / "index.html").read_text(encoding="utf-8")
    header = re.search(r"<header id=\"top-bar\">.*?</header>", markup, re.S).group(0)
    assert 'id="quit-btn"' in header


def test_both_quit_buttons_share_one_handler():
    """Two copies of the shutdown sequence would drift, and this file already
    demonstrated exactly that, twice over."""
    source = _source()
    assert source.count("async function quitApp()") == 1


#: Functions this file must define exactly once, and what a second copy costs.
#:
#: JavaScript's answer to two `function foo()` declarations at the same scope is
#: to keep the last one, silently. Nothing warns, nothing throws, and every
#: reference, including a `setInterval` registered *next to the first one* , 
#: resolves to the survivor. So the dead half of the pair looks harmless in the
#: diff while its timer goes on running the live half.
ONCE_ONLY = {
    "checkDueReminders": (
        "the Wave O poller was replaced by §36C's, but its "
        "setInterval was left behind, so the new poller ran on two 30s "
        "timers: twice the requests, and a race where both polls read the "
        "announced-ids list before either wrote to it, announcing a reminder "
        "twice. Found by watching the network log of the running app."
    ),
}


def test_a_replaced_function_took_its_timer_with_it():
    """A rewrite that leaves the old definition behind is not dead code.

    Checked by name rather than in general, because plenty of names here are
    legitimately defined once inside a closure and once outside it (the step
    timeline's `startPlan` and the chat's `startPlannedRun` were nearly such a
    pair). These are the ones where a duplicate has actually bitten.
    """
    source = _source()
    for name, why in ONCE_ONLY.items():
        found = len(re.findall(rf"(?m)^(?:async )?function {name}\(", source))
        assert found == 1, f"{name} is defined {found} times: {why}"


def test_the_reminder_poll_waits_for_the_unlock():
    """It runs on load, before there is a token, and a background poll that
    401s once per start is noise in the browser console and in the server's own
    log: where it reads as an auth failure worth investigating."""
    source = _source()
    body = re.search(
        r"(?ms)^async function checkDueReminders\(\).*?\n\}", source
    ).group(0)
    assert "authToken()" in body.split("apiJson")[0], (
        "checkDueReminders asks for /reminders before checking there is a token"
    )
    assert source.count('$("app-quit").addEventListener("click", quitApp)') == 1
    assert source.count('$("quit-btn")?.addEventListener("click", quitApp)') == 1
