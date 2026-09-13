"""Start the app.

  python -m memorymap             → server at http://localhost:8000
  python -m memorymap --desktop   → the same app in its own window
                                    (needs the optional pywebview:
                                     pip install pywebview)
"""

import argparse
import logging
import os
import sys
import threading
import time
import warnings
from pathlib import Path

import uvicorn

from memorymap.api.app import create_app
from memorymap.core import launch_status, startup_status

logger = logging.getLogger("memorymap.launcher")

HOST = "127.0.0.1"  # local only: this is a private app


def _port_from_env(raw: str | None = None) -> int:
    """The port the server binds, from MEMORYMAP_PORT, default 8000.

    `./start.sh --port N` and `start.bat --port N` export MEMORYMAP_PORT
    rather than passing an argument, because the value has to survive the
    launcher's own self-update re-exec and still reach this process. Before
    this function existed the flag was a half-kept promise: the launcher
    checked that port, opened a browser at that port, and then started a
    server that was still hardcoded to 8000.

    A junk or out-of-range value falls back to 8000 instead of raising. The
    launcher already rejects those with `--help` and exit 2, so anything
    that gets here came from the environment directly, and refusing to start
    the app over a stray variable is worse than ignoring it: the person who
    set it is not necessarily the person now trying to open their notes.
    """
    if raw is None:
        raw = os.environ.get("MEMORYMAP_PORT", "")
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return 8000
    if not 1 <= port <= 65535:
        return 8000
    return port


# Read once, at import, so every reader in this module sees one value even
# if the environment changes underneath a running process. Kept as a
# module-level name (rather than a call at each use) because that is what
# tests/test_desktop_launcher.py monkeypatches to point the desktop paths at
# a scratch port.
PORT = _port_from_env()

# Shown in the desktop window the instant it opens, before the server is
# reachable: replaces what used to be a black/blank window for however long
# _wait_for_server() took, which on a cold start (embeddings warmup, a slow
# machine) is not always instant. Someone running in "hidden console" mode
# (show_console_on_startup=False, or the packaged installer's console-less
# build) has *no* terminal to watch either, so this is the only feedback
# they get that anything is happening at all, reported directly: "the
# window doesn't [show] until all the checks and dependency updates are
# done", which is exactly the gap between this window opening and
# `_boot_and_swap` below finishing.
#
# Deliberately plain, inline HTML/CSS/JS rather than a page served from
# `frontend/`, the whole point is that it must render with no server
# listening on HOST:PORT yet, so it cannot be a request to that server. The
# palette (#4664f0) matches index.html's own `theme-color` meta tag rather
# than pulling in the real app's CSS, so the swap to the real window doesn't
# jar even though nothing is actually shared between them.
#
# The logo is the same reason, and is why it is **copied** here as inline SVG
# rather than referenced. Asked for directly ("add the logo to the loading
# screen"); this window used to show a 10px blue dot beside the wordmark,
# which is the first thing anyone sees of the app on a cold start. It cannot
# be `<img src="/favicon.svg">`, there is no server to serve it, and a
# `file://` path breaks in the packaged build, so the artwork is duplicated.
# It is 30 lines of static geometry that has changed once; keeping the two in
# sync by hand is cheaper than the alternatives, and a drift shows up
# immediately on the next launch.
_LOADING_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 18px; height: 100%; background: #12141c; color: #e7e9ee;
    font: 14px/1.4 -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  .mark { display: flex; align-items: center; gap: 12px; font-size: 18px; font-weight: 600; }
  .mark svg { width: 46px; height: 46px; display: block; }
  /* The step list, the same one scripts/splash.ps1 draws before this
     window exists, so the handoff from that window to this one looks
     like the same list carrying on rather than a restart. */
  .steps { list-style: none; margin: 0; padding: 0; width: 300px; }
  .steps li { display: flex; align-items: baseline; gap: 8px; padding: 3px 0;
              color: #5d6472; }
  .steps li .tick { width: 14px; flex: none; text-align: center; }
  .steps li .name { flex: none; }
  .steps li .detail { color: #5d6472; font-size: 12px; overflow: hidden;
                      text-overflow: ellipsis; white-space: nowrap; }
  .steps li.done { color: #9aa1ad; }
  .steps li.done .tick { color: #4a9d7a; }
  .steps li.active { color: #e7e9ee; }
  .steps li.active .tick { color: #4664f0; animation: mm-pulse 1.4s ease-in-out infinite; }
  .steps li.active .detail { color: #9aa1ad; }
  .steps li.failed { color: #e58f8f; }
  .steps li.failed .tick { color: #e58f8f; }
  @keyframes mm-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
  .bar-track { width: 300px; height: 6px; border-radius: 3px; background: #262b3a; overflow: hidden; }
  .bar-fill { height: 100%; width: 4%; background: #4664f0; border-radius: 3px;
              transition: width 300ms ease-out; }
  .bar-fill.error { background: #e5a13a; }
  #status { color: #9aa1ad; min-height: 1.2em; }
  /* Two lines reserved, not one: the longest tip names the data folder,
     which wraps, and a fixed 1.4em clipped its second line. min-height
     rather than height so nothing can shift the bar and the step list
     every six seconds either. */
  #tip { color: #5d6472; font-size: 12px; min-height: 2.8em; max-width: 340px;
         text-align: center; transition: opacity 200ms ease-out; }
  /* Reduced motion: the pulse and both fades go, the information stays.
     Nothing here is conveyed by movement alone. */
  @media (prefers-reduced-motion: reduce) {
    .steps li.active .tick { animation: none; }
    .bar-fill, #tip { transition: none; }
  }
</style></head>
<body>
  <div class="mark"><svg viewBox="0 0 100 100" role="img" aria-label="MemoryMap AI">
    <defs>
      <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#5b7cff"/><stop offset="55%" stop-color="#4664f0"/>
        <stop offset="100%" stop-color="#a927d8"/>
      </linearGradient>
      <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#ffffff" stop-opacity="0.22"/>
        <stop offset="60%" stop-color="#ffffff" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <rect width="100" height="100" rx="23" fill="url(#tile)"/>
    <rect width="100" height="100" rx="23" fill="url(#sheen)"/>
    <g stroke="#ffffff" stroke-width="5.5" stroke-linecap="round" opacity="0.92">
      <path d="M50 50 50 20"/><path d="M50 50 78.5 40.7"/><path d="M50 50 67.6 74.3"/>
      <path d="M50 50 32.4 74.3"/><path d="M50 50 21.5 40.7"/>
    </g>
    <g fill="#ffffff">
      <circle cx="50" cy="20" r="7.5"/><circle cx="78.5" cy="40.7" r="7.5"/>
      <circle cx="67.6" cy="74.3" r="7.5"/><circle cx="32.4" cy="74.3" r="7.5"/>
      <circle cx="21.5" cy="40.7" r="7.5"/>
    </g>
    <circle cx="50" cy="50" r="13" fill="#4664f0"/>
    <circle cx="50" cy="50" r="9.5" fill="#ffffff"/>
  </svg><span>MemoryMap AI</span></div>
  <ul class="steps" id="steps"></ul>
  <div class="bar-track"><div class="bar-fill" id="bar"></div></div>
  <div id="status">Starting…</div>
  <div id="tip"></div>
  <script>
    // Seeded by _loading_html() from the launcher's own status file before
    // this window is created: see core/launch_status.py. The launcher's
    // work (the git pull, building .venv, the pip install) is already over
    // by the time this page exists, so without the seed the list would
    // open empty and only ever learn about the steps still to come. An
    // empty seed is the ordinary case for `python -m memorymap --desktop`
    // run by hand, and falls back to the one step this process owns.
    window.__mmSeed = [];
    window.__mmTips = [
      "Your notes never leave this machine.",
      "Ctrl+K opens the command palette.",
      "The capture box files a thought for you, in the right place.",
      "The first run installs about 300 MB once. Later starts take seconds.",
      "Your notes live in your own data folder, as plain files you can copy."
    ];

    var mmSteps = window.__mmSeed.slice();
    // The share of the bar the launcher's steps already account for. This
    // process's own phases divide up what is left, so the bar carries on
    // from where the pre-Python splash stopped rather than resetting.
    var mmBase = 0;
    var mmOwn = null;   // the row this process is narrating into

    // Built from DOM nodes rather than an innerHTML string: every title
    // and detail here came out of a shell script by way of a text file,
    // and the project's own lint exists because the next author to touch
    // a line like this interpolates one.
    function mmRender() {
      var list = document.getElementById("steps");
      list.textContent = "";
      for (var i = 0; i < mmSteps.length; i++) {
        var s = mmSteps[i];
        var mark = s.state === "done" ? "\\u2713"
                 : s.state === "failed" ? "\\u00d7"
                 : s.state === "active" ? "\\u25cf" : "\\u25cb";
        var row = document.createElement("li");
        row.className = s.state;
        var tick = document.createElement("span");
        tick.className = "tick";
        tick.textContent = mark;
        var name = document.createElement("span");
        name.className = "name";
        name.textContent = s.title;
        var detail = document.createElement("span");
        detail.className = "detail";
        detail.textContent = s.detail || "";
        row.appendChild(tick);
        row.appendChild(name);
        row.appendChild(detail);
        list.appendChild(row);
      }
    }

    function mmSetup() {
      var done = 0, total = 0;
      for (var i = 0; i < mmSteps.length; i++) {
        if (mmSteps[i].state === "done") done++;
        total = mmSteps[i].total || total;
      }
      if (!total) total = mmSteps.length || 1;
      // The last step is this process: whatever the launcher called it, it
      // is the one still running, so this window narrates into it.
      if (mmSteps.length && mmSteps[mmSteps.length - 1].state !== "done") {
        mmOwn = mmSteps[mmSteps.length - 1];
      } else {
        mmOwn = { step: total, total: total, title: "Start",
                  detail: "Starting the app", state: "active" };
        mmSteps.push(mmOwn);
      }
      mmBase = Math.round(done * 100 / total);
      mmRender();
      document.getElementById("bar").style.width = Math.max(mmBase, 4) + "%";
    }

    // Called from the Python side (window.evaluate_js) as the launcher
    // learns more, not polled from here, see startup_status.py's own
    // docstring for why the loading window can't ask the server itself.
    window.__mmSetStatus = function (text, pct) {
      document.getElementById("status").textContent = text;
      // The row keeps the launcher's own detail for this step and the line
      // below carries the phase inside it. Writing the phase into both put
      // the same sentence on screen twice, one above the other, which reads
      // as a rendering bug rather than as two pieces of information.
      if (mmOwn && mmOwn.state !== "active") {
        mmOwn.state = "active";
        mmRender();
      }
      // pct is this process's own progress through its own phases; the bar
      // shows it inside the slice the launcher's finished steps left.
      var scaled = mmBase + (pct * (100 - mmBase) / 100);
      document.getElementById("bar").style.width = Math.max(scaled, 4) + "%";
    };
    // The last step really does finish, and this is the moment: the server
    // answered and the window is about to be pointed at the app. Without
    // it nothing ever marked the step this process owns as done, so the
    // list closed on four ticks out of five and the bar on 98.4% of its
    // track, every launch, which is the "only ever goes to 3/5 and then it
    // loads" report: not a step that was skipped, a step nobody ticked.
    window.__mmSetDone = function (text) {
      document.getElementById("status").textContent = text;
      if (mmOwn) {
        mmOwn.state = "done";
        mmOwn.detail = text;
        mmRender();
      }
      document.getElementById("bar").style.width = "100%";
    };
    window.__mmSetError = function (text) {
      document.getElementById("status").textContent = text;
      document.getElementById("bar").className = "bar-fill error";
      document.getElementById("bar").style.width = "100%";
      if (mmOwn) {
        mmOwn.state = "failed";
        mmOwn.detail = text;
        mmRender();
      }
    };

    mmSetup();

    // One tip at a time, changed every six seconds, starting at a random
    // one so the same tip is not the only one anybody ever reads. Under
    // reduced motion the fade goes and the text simply swaps.
    var mmTip = document.getElementById("tip");
    var mmTipAt = Math.floor(Math.random() * window.__mmTips.length);
    var mmReduced = window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function mmShowTip() {
      mmTip.textContent = window.__mmTips[mmTipAt % window.__mmTips.length];
      mmTipAt++;
    }
    mmShowTip();
    setInterval(function () {
      if (mmReduced) { mmShowTip(); return; }
      mmTip.style.opacity = "0";
      setTimeout(function () { mmShowTip(); mmTip.style.opacity = "1"; }, 200);
    }, 6000);
  </script>
</body></html>"""


def _loading_html(steps=None, data_dir: str | None = None) -> str:
    """`_LOADING_HTML` with the launcher's step history seeded into it.

    Read before `_close_launch_splash()` deletes the status file, which is
    the only window in which it exists: see `_run_desktop`. With no
    launcher (someone ran `python -m memorymap --desktop` by hand) there is
    no history, and the page renders the one step this process owns, which
    is exactly what `_LOADING_HTML` already says on its own.
    """
    import json

    if steps is None:
        steps = launch_status.read_file(os.environ.get("MM_SPLASH_FILE"))
    if data_dir is None:
        data_dir = os.environ.get("MEMORYMAP_DATA_DIR") or ""

    html = _LOADING_HTML
    if steps:
        seed = [
            {
                "step": s.step,
                "total": s.total,
                "title": s.title,
                "detail": s.detail,
                "state": s.state,
            }
            for s in launch_status.summarise(steps)
        ]
        html = html.replace("window.__mmSeed = [];", f"window.__mmSeed = {json.dumps(seed)};")
    if data_dir:
        # The last tip names the folder rather than describing it: "where
        # are my notes" is the most-asked question this app has, and the
        # loading window is one of the few places with room to answer it.
        html = html.replace(
            '"Your notes live in your own data folder, as plain files you can copy."',
            json.dumps(f"Your notes live in {data_dir}, as plain files you can copy."),
        )
    return html

# Coarse phase name -> a fixed progress-bar percentage. Real percentages
# aren't knowable, create_app() has no notion of "38% done", but a handful
# of ordered, named phases read as real progress rather than an indeterminate
# spinner, which is what was asked for ("a progress bar with sub text
# showing the action currently being done"). A phase this map doesn't know
# about (core/startup_status.py's own default, or a future phase string
# added there without updating this) still shows as text, just without
# advancing the bar past whatever the last known phase left it at.
_STARTUP_PHASE_PERCENT = {
    "Starting…": 4,
    "Setting up your notebook…": 30,
    "Starting local services…": 55,
    "Warming up search…": 75,
    "Starting the server…": 92,
}

# start.bat's own console window (the one visible when start-desktop.bat is
# double-clicked) blocks synchronously on this process, then falls through to
# an "app has stopped" message and `pause`, a keypress prompt that would
# leave that window sitting on screen indefinitely. This exit code is the
# signal back to the batch file that a "User view" relaunch already handed
# the app off to a separate, console-less process and it should close itself
# immediately instead: see the errorlevel check in start.bat.
RELAUNCHED_HIDDEN_EXIT_CODE = 42


def _run_server() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")


def _wait_for_server(timeout: float = 20.0) -> bool:
    """Poll until uvicorn is actually accepting connections on HOST:PORT,
    instead of guessing a fixed delay before pointing the window at it.

    `create_app()` (singleton init, embeddings warmup, etc.) runs
    synchronously on the server thread BEFORE uvicorn binds its listening
    socket: so this genuinely waits for the app to be ready, not merely
    for a thread to have started. Reported directly: the desktop window
    "sits on a black screen for a while before loading in", which a flat
    `sleep(1.0)` fully explains on a cold start (first run, heavier
    startup work, a slower machine) that takes longer than a second, the
    window opened and tried to load the page before anything was
    listening, with nothing to make it retry. Bounded, so a server that
    genuinely fails to start doesn't hang the launcher forever, the window
    still opens either way; this only affects when it opens relative to the
    server being ready to answer it.
    """
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _close_launch_splash() -> None:
    """Take down start.bat's pre-Python splash, if there is one.

    The launcher shows a window (scripts/splash.ps1) for the phase before this
    process exists at all, the git pull, building .venv, and a pip install
    that can run to minutes. That window watches the file named in
    MM_SPLASH_FILE and closes when it disappears, so this is the whole
    protocol: delete the file.

    Called the instant *this* process's own loading window is on screen, not
    earlier and not later. Earlier leaves a gap with nothing on screen at the
    slowest possible moment, which is the problem the splash exists to solve;
    later leaves two windows stacked, with an always-on-top one covering the
    real progress bar.

    Never raises. A missing variable, a file already gone, a permission error
    on TEMP: none of those are reasons to fail a launch that has otherwise
    got this far.
    """
    path = os.environ.get("MM_SPLASH_FILE")
    if not path:
        return
    _finish_splash_start_step(path)
    try:
        os.remove(path)
    except OSError as exc:
        logger.debug("couldn't close the launch splash: %s", exc)


def _finish_splash_start_step(path: str) -> None:
    """Tick the launcher's last step before its window goes, so the splash
    ends on a finished list rather than on four of five.

    Reported three times, the last with a screenshot of exactly this window:
    Update, Python, Dependencies and Desktop window all ticked, Start on a blue
    dot, "4 of 5 steps done", and then the app. The two rounds before this one
    were real bugs in start.bat; this is not one. start.bat deliberately leaves
    Start active in desktop mode, because this process's own loading window
    inherits the same list and owns that step until the server answers, and
    ticking it in both would put two Starts in one list. So the splash was
    always going to end one step short, correctly, and that is still what a
    person sees: a progress bar that gives up a step from the end.

    The launcher's *own* Start step really is finished at this line, though.
    It has built the environment, started this process, and this process has a
    window ready to show: the handover is the completion, which is exactly what
    browser mode has always written ("Handed over to the app"). Desktop mode
    can say the same thing to the same file.

    **Appended here rather than in start.bat**, and the ordering is the whole
    trick: `_loading_html()` has already read this file by the time this runs
    (see `_run_desktop`, the window is created first), so the list this process
    seeds itself with still says Start is active, and its own row re-activates
    and finishes on its own. The two windows tell one continuous story instead
    of two Starts.

    A beat before the delete, because splash.ps1 polls at 250ms: written and
    removed in the same instant, the finished state would never be rendered.

    Never raises, for the same reason the delete below does not: a missing
    file, a permission error on TEMP, a malformed history, none of them are
    reasons to fail a launch that has otherwise got this far.
    """
    try:
        steps = launch_status.summarise(launch_status.read_file(path))
        if not steps:
            return
        last = steps[-1]
        if last.done or last.failed:
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{last.step}|{last.total}|{last.title}|Handed over to the app|done\n")
        # Two of the splash's own poll ticks, so the completed list is drawn
        # and read rather than flashed. The window is the only thing on screen
        # at this point (`webview.start()` has not run yet), so this cannot
        # leave two windows stacked, which is the failure the delete below is
        # timed to avoid.
        time.sleep(0.5)
    except (OSError, ValueError, IndexError) as exc:
        logger.debug("couldn't tick the launcher's last step: %s", exc)


def _push_status_to_window(window, text: str) -> None:
    """Best-effort `window.__mmSetStatus(text, pct)` call: see
    _LOADING_HTML. Must never raise: this runs from the same background
    thread that still has to start the real server and swap the window's
    URL, and a closed/destroyed window (someone quit during startup) or an
    unexpected pywebview version is a reason to skip a cosmetic update, not
    to crash the launcher before it gets to actually starting the app.
    """
    import json

    pct = _STARTUP_PHASE_PERCENT.get(text, _STARTUP_PHASE_PERCENT["Starting the server…"])
    try:
        window.evaluate_js(f"window.__mmSetStatus && window.__mmSetStatus({json.dumps(text)}, {pct})")
    except Exception as exc:
        logger.debug("couldn't update the loading window: %s", exc)


def _mark_start_step_done(window) -> None:
    """Best-effort `window.__mmSetDone()`: see `_LOADING_HTML`.

    Wrapped exactly like `_push_status_to_window` for the same reason, this
    runs on the background thread that still has to swap the window over to
    the real app, and a window someone closed during startup must not be
    able to stop that.
    """
    try:
        window.evaluate_js(
            "window.__mmSetDone && window.__mmSetDone('Ready')"
        )
    except Exception as exc:
        logger.debug("couldn't tick the last step in the loading window: %s", exc)


def _wait_for_server_with_progress(window, timeout: float = 45.0) -> bool:
    """Same poll `_wait_for_server` does, plus pushing `startup_status`'s
    current phase to the loading window whenever it changes, see that
    module's own docstring for why this can read it directly rather than
    over HTTP. A longer default timeout than `_wait_for_server`'s own: that
    function times out fast because its caller has no better option than to
    open a window pointed at a server that may never come up; this one's
    caller has a loading window already open and a real "still working, here
    is what on" status to show while it waits, so there is more reason to be
    patient before calling it a failure.
    """
    import socket

    last_shown = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        phase = startup_status.get_phase()
        if phase != last_shown:
            _push_status_to_window(window, phase)
            last_shown = phase
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _boot_and_swap(window) -> None:
    """Runs on pywebview's own post-start background thread (`func=` below)
    once the loading window is already on screen. Starts the real server,
    narrates `startup_status`'s phases onto it while that happens, then
    swaps the same window over to the real app, or, if the server never
    comes up, leaves a plain-language error in place of an indefinite spinner.

    A separate window was considered and rejected: pywebview's
    `window.load_url()` retargets an *existing* window, so this is one
    window's whole lifecycle rather than opening a second one and tearing
    down the first: simpler, and no flicker from a close/reopen.
    """
    os.environ["MEMORYMAP_DESKTOP"] = "1"
    server = threading.Thread(target=_run_server, daemon=True)
    server.start()
    if _wait_for_server_with_progress(window):
        # Tick the step this process owns *before* the swap, not after: after
        # the swap this page no longer exists. The step is genuinely over at
        # this line, the socket answered, so this is the real completion
        # rather than a tick bought to fill the bar. It is on screen for the
        # navigation only, but it is the difference between a launch that
        # ends on a finished list and one that ends on four of five.
        # Ticked, then swapped immediately. A quarter-second hold was tried
        # here first, to make this window's own finished list visible, and the
        # owner asked for it back: "remove the delay on the other splash
        # loading screen in the main window". They are right, and the reason is
        # that the hold was solving the wrong window's problem. The list a
        # person actually watches finish is the launcher's splash, which now
        # ticks its own last step before it closes
        # (`_finish_splash_start_step`); by the time this page could show
        # anything, the app is what they are waiting for. Nothing is lost: the
        # step is still marked done, so a `Details` pane or a log read after
        # the fact tells the truth about what happened.
        _mark_start_step_done(window)
        window.load_url(f"http://{HOST}:{PORT}")
        _focus_window(window)
    else:
        try:
            window.evaluate_js(
                "window.__mmSetError && window.__mmSetError("
                "'The server did not start. Check the logs and try restarting.')"
            )
        except Exception as exc:
            logger.warning("server never came up, and couldn't show that in the window: %s", exc)


def _focus_window(window) -> None:
    """Best-effort: bring the window to the front and give it real input
    focus the moment it swaps from the loading page to the real app. Asked
    for directly, alongside the loading window itself, without this, the
    window that was sitting in front narrating startup progress is not
    guaranteed to still have focus once the swap happens, on every window
    manager/backend.

    Two independent attempts, neither load-bearing for the other: pywebview
    has no single `focus()` method with consistent behaviour across its
    GTK/Qt/WebView2/Cocoa backends: `show()` is the closest built-in, and
    only some of those backends treat it as focus-stealing rather than just
    un-hiding an already-visible window. So this also asks the *page itself*
    to focus its own OS window via plain DOM `window.focus()`, which every
    backend's underlying web engine already implements for exactly this, 
    and which works before the newly-loaded page has finished loading,
    since it acts on the window object rather than anything in the DOM.
    Wrapped the same way every other optional-pywebview-surface call in this
    file is: a missing method, or a platform that refuses a focus-steal
    request outright (some window managers do, by policy), is not worth
    crashing the launcher over.
    """
    try:
        window.show()
    except Exception as exc:
        logger.debug("window.show() during focus handoff didn't work: %s", exc)
    try:
        window.evaluate_js("window.focus()")
    except Exception as exc:
        logger.debug("couldn't ask the page to focus its own window: %s", exc)


def _get_console_hwnd() -> int | None:
    """The Win32 handle of this process's own console window, or None.

    None means either this isn't Windows, or this Windows process genuinely
    has no console to show/hide, the packaged installer's PyInstaller build
    sets `console=False`, so `GetConsoleWindow()` correctly returns NULL
    there. Shared between the startup auto-hide below and the tray's own
    live toggle so both agree on the same handle.
    """
    try:
        import ctypes

        return ctypes.windll.kernel32.GetConsoleWindow() or None
    except Exception as exc:
        logger.warning("couldn't look up the console window: %s", exc)
        return None


def _pythonw_path() -> Path | None:
    """`pythonw.exe` next to the interpreter currently running this, the
    windowless CPython build every standard Windows install/venv ships
    alongside `python.exe`. None if it isn't there (a non-standard Python
    build) or this isn't Windows."""
    if sys.platform != "win32":
        return None
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.is_file() else None


def _spawn_desktop(hidden: bool):
    """Start a fresh `memorymap --desktop` process in the given console
    mode, independent of whatever process/window is calling this, the one
    spawn primitive `_maybe_relaunch_hidden` (startup), the tray's live
    toggle, and the Settings-triggered restart (`routes_settings.py`'s
    `/system/console-mode`) all share, so the three call sites can't drift
    into three slightly different flag combinations. Returns the `Popen`,
    or None if this isn't win32 or (for hidden) no pythonw.exe was found.
    """
    if sys.platform != "win32":
        return None
    try:
        import subprocess

        if hidden:
            pythonw = _pythonw_path()
            if pythonw is None:
                logger.warning(
                    "no pythonw.exe next to %s, can't relaunch console-less",
                    sys.executable,
                )
                return None
            # CREATE_NO_WINDOW: even pythonw.exe can end up with a console
            # if one is inherited from the parent rather than allocated
            # fresh: this refuses one outright. DETACHED_PROCESS: don't
            # inherit this process's own console/handles either, so the new
            # process is fully independent of whatever cmd/terminal window
            # launched it: which is what lets that window close on its own
            # once this process exits, instead of staying open because
            # something it spawned is still attached to it.
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            return subprocess.Popen(
                [str(pythonw), "-m", "memorymap", "--desktop", "--hidden-relaunch"],
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                close_fds=True,
                cwd=os.getcwd(),
            )
        # Going visible: a plain python.exe (console-subsystem) child with
        # CREATE_NEW_CONSOLE explicitly gets a fresh console from Windows
        # regardless of whether this process, hidden/console-less, if it
        # got here via the pythonw.exe path above, has one of its own to
        # offer it.
        CREATE_NEW_CONSOLE = 0x00000010
        return subprocess.Popen(
            [sys.executable, "-m", "memorymap", "--desktop"],
            creationflags=CREATE_NEW_CONSOLE,
            close_fds=True,
            cwd=os.getcwd(),
        )
    except Exception as exc:
        logger.warning("couldn't relaunch in %s console mode: %s", "hidden" if hidden else "visible", exc)
        return None


def restart_in_console_mode(hidden: bool) -> bool:
    """Public entry point for switching Dev view / User view from outside
    this process entirely: the HTTP route Settings' own toggle calls
    (`/system/console-mode`), which runs on the server thread and has no
    access to pywebview's `window`/`icon` objects the tray's own toggle
    uses for a tidier teardown. Spawns the replacement first and only exits
    this process if that succeeded, so a failed relaunch (no pythonw.exe,
    Windows refused the spawn) leaves the running app running rather than
    killing it for nothing.
    """
    process = _spawn_desktop(hidden)
    if process is None:
        return False
    os._exit(0)
    return True  # unreachable: os._exit() never returns; keeps every path explicit


def _maybe_relaunch_hidden(show_on_startup: bool, already_relaunched: bool):
    """"User view", done properly: instead of creating a console and then
    trying to hide it, which `ShowWindow`/`GetConsoleWindow` turned out
    not to reliably do, reported live as hiding "just changes what window
    is currently focused" without anything actually disappearing, the
    likely cause being Windows Terminal's ConPTY plumbing returning a
    handle to a hidden pseudo-console host rather than the real on-screen
    window: this relaunches via `pythonw.exe`, which never allocates a
    console in the first place. Nothing to hide, nothing to get wrong.

    Only for a *source* checkout (`start.bat`/`start-desktop.bat`): the
    packaged installer's PyInstaller build already sets `console=False`, so
    `_get_console_hwnd()` returns None there and this whole question never
    comes up. `already_relaunched` is this function's own recursion guard, 
    the relaunched pythonw.exe process runs this same code path again with
    `--hidden-relaunch` set, and must not try to relaunch itself forever.

    Returns the spawned `Popen` on success (the caller's job is to exit
    right after: see `RELAUNCHED_HIDDEN_EXIT_CODE`), or None to mean
    "carry on in this process", the platform is wrong, the preference asks
    for the console to stay visible, this already *is* the relaunched
    process, or spawning failed for a reason worth falling back from rather
    than crashing the launcher over.
    """
    if (
        sys.platform != "win32"
        or getattr(sys, "frozen", False)
        or show_on_startup
        or already_relaunched
    ):
        return None
    process = _spawn_desktop(hidden=True)
    if process is None:
        logger.warning(
            "falling back to hiding the console window instead of never creating one"
        )
    return process


def _ancestor_console_hwnds(own_hwnd: int | None) -> list[int]:
    """Every other visible top-level window owned by this process's parent
    chain (the shell that launched it, cmd.exe, and above that whatever
    hosts it), skipping `own_hwnd` if it's already in that chain.

    `GetConsoleWindow()` alone is reported not to be enough: hiding it was
    seen live to change which window has focus without making anything
    disappear: the one failure mode that fits is Windows Terminal, whose
    ConPTY plumbing means the handle a child process gets back from
    `GetConsoleWindow()` can belong to a hidden pseudo-console host rather
    than the actual on-screen terminal tab (that window belongs to
    WindowsTerminal.exe, several processes up, not to conhost.exe or to
    this Python process at all). Walking the real parent-process chain and
    hiding whatever top-level windows those processes own is a second,
    independent way to reach the actual visible window regardless of which
    terminal is hosting it, legacy conhost included, where this usually
    just finds the same window `_get_console_hwnd` already did.

    Unverified on real Windows, same as the rest of this file's console
    handling: every step is wrapped so a wrong assumption here degrades to
    "did nothing extra" rather than crashing the launcher.
    """
    import ctypes
    import ctypes.wintypes as wintypes

    hwnds: list[int] = []
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == -1:
            return hwnds
        try:
            parent_of: dict[int, int] = {}
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if kernel32.Process32First(snapshot, ctypes.byref(entry)):
                while True:
                    parent_of[entry.th32ProcessID] = entry.th32ParentProcessID
                    if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)

        # Up to the shell (cmd.exe) and whatever hosts *that*, start.bat's
        # own self-update relaunch (os.execv-free here, but the tray's
        # Restart uses it elsewhere) means this can legitimately be several
        # levels, not just one; capped so a corrupt/cyclic PPID chain (a
        # dead process's PID reused by something unrelated) can't loop.
        ancestry: set[int] = set()
        pid = os.getpid()
        for _ in range(8):
            parent = parent_of.get(pid)
            if not parent or parent in ancestry or parent == 0:
                break
            ancestry.add(parent)
            pid = parent
        if not ancestry:
            return hwnds

        found: list[int] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _each_window(hwnd, _lparam):
            if hwnd == own_hwnd or not user32.IsWindowVisible(hwnd):
                return True
            owner_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            # GetWindow(hwnd, GW_OWNER) != 0 means this is a child/owned
            # window (a dialog, a tooltip) rather than a real top-level
            # shell window: skipping those keeps this to "the terminal
            # window itself", not every popup any ancestor process has open.
            GW_OWNER = 4
            if owner_pid.value in ancestry and not user32.GetWindow(hwnd, GW_OWNER):
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_each_window), 0)
        hwnds = found
    except Exception as exc:
        logger.warning("couldn't walk the parent process chain for console windows: %s", exc)
    return hwnds


def _window_class_name(hwnd: int) -> str:
    """Diagnostic only: which window class actually owns a handle, so a log
    line can tell "ConsoleWindowClass" (legacy conhost, expected to hide
    cleanly) apart from anything else (Windows Terminal's own class,
    or a handle that isn't what was intended at all) without needing
    someone to attach a debugger to find out."""
    import ctypes

    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value or "?"
    except Exception:
        return "?"


def _console_window_targets(console_hwnd: int) -> dict[int, str]:
    """Every window this app will show/hide together as "the console":
    `console_hwnd` itself plus whatever `_ancestor_console_hwnds` finds,
    each mapped to its window class name for the diagnostic log line in
    `_apply_console_visibility`. Split out from applying visibility so the
    startup path and the tray's live toggle act on the exact same set
    computed once, rather than the ancestor walk (a live enumeration) maybe
    disagreeing with itself between two separate calls.
    """
    targets = {console_hwnd: _window_class_name(console_hwnd)}
    for hwnd in _ancestor_console_hwnds(console_hwnd):
        targets.setdefault(hwnd, _window_class_name(hwnd))
    return targets


def _apply_console_visibility(targets: dict[int, str], hidden: bool) -> None:
    """Hide or show a set of windows found by `_console_window_targets`, and
    say what actually happened, reported live that the startup hide "just
    changes what window is currently focused" rather than making anything
    disappear, which a silent `ShowWindow` call gives no way to diagnose
    after the fact. Every step here is logged (visible in Settings -> Logs,
    or on stdout if the console itself is what's being tested) so the
    *next* report can say which of these actually ran and what Windows
    said back, instead of "still doesn't work."
    """
    import ctypes

    user32 = ctypes.windll.user32
    SW_HIDE, SW_SHOW = 0, 5
    for hwnd, class_name in targets.items():
        # One bad handle/API surface must not stop the rest, same reasoning
        # as the AppUserModelID call's own try/except: an unexpected
        # ctypes.windll shape this wasn't tested against should degrade to
        # "skipped one window, logged why" rather than take the whole
        # attempt down.
        try:
            was_visible = bool(user32.IsWindowVisible(hwnd))
            user32.ShowWindow(hwnd, SW_HIDE if hidden else SW_SHOW)
            now_visible = bool(user32.IsWindowVisible(hwnd))
            logger.info(
                "console %s: hwnd=%s class=%r was_visible=%s now_visible=%s",
                "hide" if hidden else "show", hwnd, class_name, was_visible, now_visible,
            )
        except Exception as exc:
            logger.warning(
                "couldn't %s hwnd=%s class=%r: %s",
                "hide" if hidden else "show", hwnd, class_name, exc,
            )


def _stop_background_work() -> None:
    """Stop every background job before an exit that skips the normal one.

    `os._exit` and `os.execv` both replace or end this process immediately:
    no `finally`, no atexit, no uvicorn shutdown, and so no lifespan handler.
    The server's own lifespan calls `bgtasks.stop_all()` for the graceful
    paths (`/shutdown`, Ctrl+C); this is the same call for the two paths that
    are deliberately abrupt.

    Never raises and never blocks for long: the process is going away, and a
    Quit button that hangs is worse than a stray subprocess.
    """
    try:
        from memorymap.core import bgtasks

        bgtasks.stop_all()
    except Exception as exc:  # noqa: BLE001  # best effort on the way out
        logger.warning("couldn't stop background work before exiting: %s", exc)


def _run_desktop(hidden_relaunch: bool = False) -> None:
    """A real app window: uvicorn in a background thread,
    pywebview in front. Closing the window exits the process.

    `hidden_relaunch` is True only when this process IS the console-less
    `pythonw.exe` relaunch `_maybe_relaunch_hidden` spawned: see there for
    why relaunching, rather than hiding an already-created console, is
    "User view"'s actual mechanism now.
    """
    # Read the preference, and try a relaunch if it calls for one, before
    # anything else, including importing webview: if this is about to hand
    # off to a separate process and exit, nothing below matters. ConfigManager
    # reads preferences.json straight off disk with no server dependency at
    # all (deps.init_app_state hasn't run, and doesn't need to), so this is
    # safe before the server thread, or the process's own console, has
    # done anything.
    from memorymap.core.config import ConfigManager

    show_on_startup = ConfigManager().get_preference("show_console_on_startup", True)
    relaunched = _maybe_relaunch_hidden(show_on_startup, hidden_relaunch)
    if relaunched is not None:
        raise SystemExit(RELAUNCHED_HIDDEN_EXIT_CODE)

    try:
        import webview  # the optional pywebview package
    except ImportError:
        print(
            "The desktop window needs the optional pywebview package:\n"
            "  pip install pywebview\n"
            "Starting the normal server instead, open http://localhost:8000"
        )
        _run_server()
        return

    # Hide the console before starting anything else, unless the user has
    # asked to keep seeing it, asked for directly: "I want it to be hidden
    # but the user can make it show ... if they want", both as a startup
    # preference (Settings, this) and live (the tray toggle below). None on
    # any non-Windows platform, or the packaged installer's console-less
    # build: nothing to hide either way. Only reached at all when
    # _maybe_relaunch_hidden declined above: platform/frozen/preference
    # said not to, or spawning pythonw.exe itself failed, so this is now
    # the fallback path, not the primary one: same ShowWindow-based attempt
    # this app always had, kept for whatever situation made the relaunch
    # not apply.
    #
    # This used to run after _wait_for_server(), on the theory that reading
    # the preference needed deps.get_config()'s singleton, which create_app()
    # only builds on the server thread. That made the console fully visible
    # for the entire startup wait, which on a cold start (embeddings warmup,
    # etc.) is the same multi-second gap §"sometimes takes a while to
    # initially load" is about: so "hidden at startup" was true only after
    # a visible delay, reported directly as the console "still showing".
    # Reading the preference above, before the server thread starts, is what
    # fixed that half of it.
    console_hwnd = _get_console_hwnd() if sys.platform == "win32" else None
    console_hidden = False
    console_targets: dict[int, str] = {}
    if console_hwnd is not None:
        console_targets = _console_window_targets(console_hwnd)
        if not show_on_startup:
            _apply_console_visibility(console_targets, hidden=True)
            console_hidden = True

    # The window opens on the loading page immediately, before the server
    # thread has even started, let alone finished create_app()'s
    # migrations/embeddings-warmup/etc.: instead of waiting here for
    # _wait_for_server() the way this used to. Reported directly: someone
    # running with the console hidden (the `show_on_startup=False` branch
    # just above, or the packaged installer's console-less build) has no
    # terminal to watch either, so a window that doesn't open until the
    # server answers is, for them, no feedback at all that anything is
    # happening. The real server start, the phase narration, and the swap to
    # the real URL all happen in `_boot_and_swap`, run by `webview.start()`
    # below once this window is actually on screen (pywebview's own
    # `func=`/`args=`, the standard way to do post-open work without
    # blocking the window from appearing in the first place).
    window = webview.create_window(
        "MemoryMap AI",
        html=_loading_html(),
        width=1200,
        height=800,
        min_size=(420, 500),
        # pywebview defaults this to False, which blocks selecting or
        # copying any text in the window, reported directly ("can't
        # highlight or copy text in the desktop view"). Applies to the real
        # app once loaded; the loading page has nothing worth selecting.
        text_select=True,
    )
    # The handoff from start.bat's splash to this window. create_window has
    # returned, so this window is the one the user is about to be looking at;
    # the splash's job is over the moment it is.
    _close_launch_splash()
    # `private_mode` defaults to True in pywebview, which throws away
    # localStorage and cookies when the window closes. The browser build keeps
    # a great deal in localStorage, the theme and every appearance key, the
    # "onboardingDone" flag, the auth token, the active tab, sidebar widths, 
    # so the desktop app was starting from scratch every single time. That is
    # one cause behind three separate reports (§35E): the theme resetting to
    # default, the onboarding tour showing on every launch, and having to sign
    # in again each time.
    #
    # The storage lives beside the notes rather than in pywebview's own
    # default, so "where your data is" stays one answer, and deleting the data
    # directory really does remove everything.

    # The app icon: replaces the default Python snake in the taskbar and
    # title bar. Two levels up from src/memorymap/__main__.py lands at the
    # repo root; frontend/icon.ico sits there. A PyInstaller build has no
    # "two levels up", everything bundled lands directly under the
    # extraction root with the `src/` layer gone, same reasoning and same
    # fix as FRONTEND_DIR in api/app.py. The ICO contains a 512px PNG entry,
    # which pywebview on Windows and WebKit on macOS both accept. None is a
    # valid fallback: a missing file never blocks the window.
    #
    # Linux gets the plain PNG instead: GTK's icon loading goes through
    # GdkPixbuf, and unlike Windows/macOS this was never actually run
    # against a Linux desktop to confirm ICO decodes there, icon-512.png
    # is the one format every platform this app now ships on is known to
    # accept, so there's no reason to gamble on the untested one for a
    # cosmetic detail.
    if getattr(sys, "frozen", False):
        _frontend_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend"
    else:
        _frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    _icon_path = _frontend_dir / ("icon-512.png" if sys.platform.startswith("linux") else "icon.ico")
    _icon = str(_icon_path) if _icon_path.is_file() else None

    if sys.platform == "win32":
        try:
            import ctypes
            # Setting a custom AppUserModelID tells Windows this is a distinct app,
            # decoupling the taskbar icon from the Python executable's default snake.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "memorymap.desktop.app.1"
            )
        except Exception as exc:
            # Best-effort cosmetic fix: a wrong or missing taskbar icon is not
            # worth blocking the window over, so this must never crash the
            # launcher. But CodeQL is right that a silent `except: pass` here
            # hides a real failure mode too: an unexpected `ctypes.windll`
            # shape (a Windows build this wasn't tested against) would fail
            # every time with no way to tell a cosmetic no-op from a bug.
            # Logged, not swallowed.
            logger.warning("could not set the Windows AppUserModelID: %s", exc)

    # Asked for directly, alongside the installer: a way to manage the app
    # without a terminal window sitting open, and a place for "close" to go
    # that isn't "quit", the whole point of a background app.  Optional in
    # the same way voice/semantic search are (see core/extras.py): a source
    # checkout without pystray+Pillow installed still gets a normal window,
    # it just closes for real instead of minimizing.
    #
    # Windows only, deliberately: see _start_tray's own docstring: this
    # runs pystray's event loop on a daemon thread while webview.start()
    # blocks the main one, which Windows' pystray backend tolerates and
    # macOS's does not (already excluded for exactly that reason). Linux's
    # GTK-based backend has the same main-thread-only UI constraint as
    # macOS's AppKit, so shipping the identical off-main-thread architecture
    # there risks the same class of crash on a platform this was never
    # built or run against, the Linux build gets a real window that closes
    # for real instead, the same fallback already in place when pystray
    # simply isn't installed.
    tray_icon = (
        _start_tray(window, _icon_path, console_hwnd, console_hidden, console_targets)
        if sys.platform == "win32"
        else None
    )
    if tray_icon is not None:
        # **Closing the window is not quitting the app, and it now says so.**
        # The hide itself has been here since the tray was added; what was
        # missing is everything around it. Reported as a thing to build, 
        # "maybe make it so the app window can be closed but the app will
        # still be open in the system tray, and then the window can be
        # reopened again. so there is a difference between minimising the app
        # and quitting the app", which is a fair description of what a
        # silent hide looks like from outside: the window vanishes, nothing
        # explains where it went, and the only way back is noticing an icon
        # you were never told to look for.
        #
        # Two things fix that and neither changes the hide:
        #
        # 1. **A preference.** `close_to_tray` defaults to on (a background
        #    notebook is the point of the tray) and can be turned off, in
        #    which case the X button quits properly, which is what someone
        #    who does not want a resident app expects it to do, and what the
        #    Linux/macOS builds already do for want of a tray.
        # 2. **One notice, the first time.** A balloon from the tray icon
        #    itself, so the explanation appears next to the thing being
        #    explained. Once per install, keyed on a preference: an app that
        #    tells you the same thing every time you close it is worse than
        #    one that never tells you.
        _told_about_tray = {"done": False}

        def _on_closing() -> bool:
            try:
                from memorymap.core import deps

                config = deps.get_config()
                if not config.get_preference("close_to_tray", True):
                    # A real quit, so the same teardown the tray's own Quit
                    # does: this path skips the lifespan handler too.
                    _stop_background_work()
                    return True
                if not _told_about_tray["done"] and not config.get_preference(
                    "tray_hide_explained", False
                ):
                    _told_about_tray["done"] = True
                    config.set_preference("tray_hide_explained", True)
                    try:
                        tray_icon.notify(
                            "Still running here. Click the icon to bring the "
                            "window back, or right-click → Quit to close it "
                            "properly.",
                            "MemoryMap AI",
                        )
                    except Exception as exc:  # noqa: BLE001  # balloons are optional
                        logger.debug("couldn't show the tray balloon: %s", exc)
            except Exception as exc:  # noqa: BLE001  # never block a close
                logger.warning("close-to-tray check failed: %s", exc)
            window.hide()
            return False  # cancels the real close, pywebview just hides it

        window.events.closing += _on_closing

    storage = Path(os.getenv("MEMORYMAP_DATA_DIR", "data")).resolve() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(  # blocks until the window closes; daemon dies with us
            _boot_and_swap,  # runs on its own thread once the window is open
            window,
            private_mode=False,
            storage_path=str(storage),
            **(({"icon": _icon}) if _icon else {}),
        )
    except TypeError:
        # An older pywebview without one of the keyword arguments above
        # (icon/private_mode/storage_path): `func`/`args` have been part of
        # pywebview's `start()` since long before those, so this fallback
        # only drops the newer ones, never the loading-window handoff.
        # Starting with a forgetful window is much better than not starting
        # at all: the desktop app is the only way in for someone who
        # installed it that way.
        print(
            "This pywebview is too old to keep settings between launches "
            "(pip install -U pywebview). Starting anyway."
        )
        webview.start(_boot_and_swap, window)
    finally:
        # Only reached once the window is really gone (Quit, not a hide), 
        # an icon left running with no window behind it is a stray process
        # nothing can get back to.
        if tray_icon is not None:
            tray_icon.stop()


def _start_tray(
    window,
    icon_path: Path,
    console_hwnd: int | None,
    console_hidden: bool,
    console_targets: dict[int, str] | None = None,
):
    """The system tray icon: Open / View Logs / Restart / Quit.

    Returns None: and the caller falls back to an ordinary window that
    really closes on the X button, when pystray or Pillow aren't installed.
    Both are optional for the same reason pywebview itself is (core/extras.py):
    a source checkout that never asked for the desktop window shouldn't need
    them, and the packaged Windows installer bundles both so this path is
    always taken there.

    Runs pystray's own event loop in a daemon thread: `webview.start()` below
    blocks the main thread until the window is really destroyed, and pystray's
    `run()` blocks too: two things that both want to block forever can't
    share one thread. Windows' pystray backend (the only platform this ships
    on) tolerates running off the main thread; that would not be true on
    macOS, which is one reason the desktop build doesn't target it.
    """
    try:
        import pystray
        from PIL import Image
    except ImportError:
        logger.info(
            "no system tray: install pystray + Pillow for one "
            "(pip install pystray Pillow), or use the Windows installer, "
            "which bundles both"
        )
        return None
    except Exception as exc:
        # Not just ImportError: pystray picks a backend at import time (Xorg,
        # AppKit, win32...) and that backend's own init can raise anything, 
        # found in this sandbox as Xlib.error.DisplayNameError on a headless
        # Linux box with no X server. A missing tray icon is cosmetic; the
        # window is not, so this must degrade the same way a genuinely
        # missing package does rather than take the whole launcher down.
        logger.warning("system tray unavailable, continuing without one: %s", exc)
        return None

    image = None
    if icon_path.is_file():
        try:
            # Pillow's ICO decoder warns "Image was not the expected size"
            # for any .ico whose largest frame doesn't match the size in its
            # directory header: true of frontend/icon.ico, and harmless here
            # since we only ever want the largest frame. Scoped to this one
            # call so a genuine UserWarning from elsewhere still surfaces.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Image was not the expected size",
                    category=UserWarning,
                )
                image = Image.open(icon_path)
        except OSError as exc:
            logger.warning("couldn't load %s for the tray icon: %s", icon_path, exc)
    if image is None:
        # A flat brand-blue square rather than no icon at all, pystray
        # requires a real image, and a missing tray icon reads as "the app
        # crashed", not "cosmetic fallback".
        image = Image.new("RGBA", (64, 64), (74, 108, 247, 255))

    def _open(icon, item) -> None:
        # `show()` un-minimises but does not raise or focus, so clicking Open
        # while the window was merely *behind* something did nothing visible, 
        # which reads as the menu item being broken. `_focus_window` is the
        # same helper the loading-window handoff already uses for this.
        window.show()
        _focus_window(window)

    # Running from start.bat/start-desktop.bat rather than the packaged
    # installer (whose PyInstaller build sets console=False, so there is no
    # window to find) leaves a cmd.exe console sitting behind the app, 
    # asked for directly: a way to get rid of it without losing the ability
    # to bring it back for a stray print/traceback. `console_hwnd` and its
    # initial `console_hidden` state come from the caller, which already
    # applied the show_console_on_startup preference before the window even
    # opened: this menu item is the *live* control, and toggling it also
    # writes the preference back, so "hide it" or "show it" from here is
    # remembered for the next launch too, not just this one.
    console_state = {"hidden": console_hidden}

    def _console_hidden(item) -> bool:
        return console_state["hidden"]

    def _toggle_console(icon, item) -> None:
        if console_hwnd is None:
            return
        going_hidden = not console_state["hidden"]

        # Best-effort, same as the startup path's own fallback: works for
        # legacy conhost, a no-op under Windows Terminal's ConPTY (see
        # _maybe_relaunch_hidden's docstring): which the restart below is
        # what actually guarantees, at the cost of a brief relaunch instead
        # of an instant toggle.
        _apply_console_visibility(console_targets or {console_hwnd: _window_class_name(console_hwnd)}, hidden=going_hidden)
        console_state["hidden"] = going_hidden

        try:
            from memorymap.core import deps

            deps.get_config().set_preference("show_console_on_startup", not going_hidden)
        except Exception as exc:
            # Remembering the choice is a nicety on top of the live toggle,
            # which has already happened above, never let a failure here
            # make the menu item look like it did nothing.
            logger.warning("couldn't save the console visibility preference: %s", exc)

        # The reliable half: relaunch into the correct mode from scratch
        # rather than trust the ShowWindow attempt just above actually
        # worked: same _spawn_desktop the startup path and the
        # Settings-triggered restart both use, so all three take identical
        # action for the same mode switch.
        process = _spawn_desktop(hidden=going_hidden)
        if process is None:
            return  # nothing to relaunch into; the ShowWindow attempt above is all there is

        icon.stop()
        window.destroy()
        os._exit(0)

    def _go(js: str):
        """A tray item that brings the window forward and *lands somewhere*.

        Reported directly: "the options and buttons in the system tray dont
        fully navigate to the propper features, just the tabs or settings
        modal." Two items existed and each hand-rolled the same three steps, 
        show, focus, evaluate a string of JS, so adding a third meant copying
        them again, which is why there was never a third.

        Every generated item carries the same lock guard, and that is the
        reason this is a factory rather than a list of one-liners: a tray menu
        must never reach past the lock screen, and a guard that has to be
        remembered per item is a guard that will be forgotten. Locked, the
        window still comes forward, the person asked for the app, and the
        honest answer is the lock screen, not nothing happening.

        **Also closes Settings first, if it's open.** Reported directly, on
        "Reminders" specifically but asked to apply to "the others" too: a
        tray item that calls `switchTab(...)` switches the tab *underneath*
        an open Settings modal, which is a full-screen overlay, the tab
        changes, nothing about it is visible, and clicking Reminders reads as
        broken. `switchTab()` itself has no opinion on a modal sitting on top
        of it; closing that modal first is this factory's job, applied once
        here rather than repeated (or, as happened once already, forgotten)
        per item.
        """
        close_settings_first = (
            "if (typeof settingsModalOpen === 'function' && settingsModalOpen()"
            " && typeof closeSettingsModal === 'function') { closeSettingsModal(); }"
        )

        def run(icon, item) -> None:
            window.show()
            _focus_window(window)
            try:
                window.evaluate_js(
                    "if (document.getElementById('lock-overlay')"
                    "?.classList.contains('hidden')) {"
                    + close_settings_first
                    + js
                    + "}"
                )
            except Exception as exc:  # noqa: BLE001  # a menu item is not worth a crash
                logger.warning("tray navigation failed: %s", exc)

        return run

    def _view_logs(icon, item) -> None:
        # Reported directly, twice: this used to open Settings unconditionally
        # (reaching straight past the lock screen, fixed once already, see
        # the lock-overlay guard below) and, separately, never actually landed
        # on the Logs section, it called `openSettingsModal()` with no
        # argument and then `showSettingsSection('logs')`, a function that
        # does not exist anywhere in the frontend (grepped, not assumed) and
        # so silently did nothing past opening Settings on whatever section it
        # last had open. `openSettingsModal(section)` already takes the
        # section directly: every other settings-bound tray item below
        # already calls it this way (`openSettingsModal('tasks')`,
        # `openSettingsModal('models')`); this was the one holdout.
        window.show()
        _focus_window(window)
        window.evaluate_js(
            "if (document.getElementById('lock-overlay')?.classList.contains('hidden')"
            " && typeof openSettingsModal === 'function') {"
            " openSettingsModal('logs'); }"
        )

    def _restart(icon, item) -> None:
        # Re-execs this same process rather than spawning a second one, no
        # window during the gap, and never two copies of the app arguing
        # over the same SQLite file if something goes wrong mid-relaunch.
        #
        # The argv has to be built differently for the two install types, and
        # getting it wrong broke Restart in exactly the build where it is
        # hardest to notice. `[sys.executable, *sys.argv]` is right from
        # source, where `sys.executable` is python.exe and `sys.argv[0]` is the
        # script: but in a PyInstaller build **both are the .exe**, so that
        # form passes the executable's own path as a positional argument.
        # `parse_args` has no positionals, so it exits(2) on "unrecognized
        # arguments", and the packaged app has no console to print that to:
        # the user clicks Restart, the window closes, and nothing comes back.
        argv = list(sys.argv) if getattr(sys, "frozen", False) else [sys.executable, *sys.argv]
        _stop_background_work()
        icon.stop()
        window.destroy()
        os.execv(sys.executable, argv)

    def _quit(icon, item) -> None:
        # **Before the hard exit below, not after it, there is no after.**
        # Reported directly: "make sure that if the app is quit, all ai tasks
        # and bg tasks stop as well." `os._exit(0)` skips every shutdown hook
        # this process has, including the lifespan handler that calls exactly
        # this function, so quitting from the tray was the one exit path that
        # left a pip install and a SearXNG server running with nothing left to
        # own them.
        _stop_background_work()
        icon.stop()
        window.destroy()
        # window.destroy() runs on this thread (pystray's own), not the main
        # thread blocked inside webview.start(), reported directly: Quit
        # closed the window but left the process (and the uvicorn server
        # thread behind it) running, because a cross-thread destroy call
        # isn't guaranteed to actually unblock that main-thread wait. A hard
        # exit is the same shape _restart already trusts (os.execv, no
        # graceful winddown either) and guarantees the process, and the
        # terminal it's running in: actually ends.
        os._exit(0)

    def _new_note(icon, item) -> None:
        """Straight to an empty note, focused and ready to type.

        The reason a tray icon earns its place in a notebook app: the whole
        point of "capture it before you lose it" is not having to find the
        window, pick a tab and click into a box first. Everything else on this
        menu is app management; this is the only item that does the app's
        actual job.

        Guarded by the lock overlay exactly as View Logs is, a tray item must
        never reach past the lock screen, and by `typeof`, because the menu
        can be clicked while the page is still loading. Kept as its own named
        function rather than folded into the `_go` factory below (which would
        remove some duplication) because test_tray.py locates this function's
        body by splitting this file's source text on its own signature, the
        safer fix for "close Settings first" was adding the same guard `_go`
        now carries, not restructuring around a test with no other reason to
        change today. (This paragraph deliberately avoids spelling that
        signature out verbatim, for the same reason, that string appearing
        twice is exactly what broke the split the first time this was tried.)
        """
        window.show()
        _focus_window(window)
        window.evaluate_js(
            "if (!document.getElementById('lock-overlay')?.classList.contains('hidden')) {}"
            " else if (typeof switchTab === 'function') {"
            " if (typeof settingsModalOpen === 'function' && settingsModalOpen()"
            " && typeof closeSettingsModal === 'function') { closeSettingsModal(); }"
            " switchTab('notes');"
            " document.getElementById('entry-content')?.focus(); }"
        )

    # Everything a tray icon is for: capture something, ask something, check
    # on the app, get to the settings that matter. Each item lands on the
    # feature rather than on the tab that contains it, see `_go`.
    menu_items = [
        pystray.MenuItem("Open MemoryMap AI", _open, default=True),
        pystray.MenuItem("New note", _new_note),
        pystray.MenuItem(
            "Ask a question",
            _go("if (typeof switchTab === 'function') { switchTab('chat');"
                " document.getElementById('chat-input')?.focus(); }"),
        ),
        pystray.MenuItem(
            "Search everything",
            _go("if (typeof openPalette === 'function') openPalette();"
                " else if (typeof switchTab === 'function') switchTab('library');"),
        ),
        pystray.MenuItem(
            "Record a meeting",
            _go("if (typeof openMeetingRecorder === 'function') openMeetingRecorder();"),
        ),
        pystray.MenuItem(
            "Reminders",
            _go("if (typeof switchTab === 'function') switchTab('reminders');"),
        ),
        pystray.MenuItem(
            "Whiteboard",
            _go("if (typeof switchTab === 'function') switchTab('whiteboard');"),
        ),
        pystray.MenuItem(
            "Background tasks",
            _go("if (typeof openSettingsModal === 'function') openSettingsModal('tasks');"),
        ),
        pystray.MenuItem(
            "Settings",
            _go("if (typeof openSettingsModal === 'function') openSettingsModal('models');"),
        ),
        pystray.MenuItem("View Logs", _view_logs),
        pystray.Menu.SEPARATOR,
        # The other half of "there is a difference between minimising the app
        # and quitting the app", the same hide the window's own close button
        # now does, reachable from here so the behaviour is discoverable
        # rather than only ever happening to you.
        pystray.MenuItem("Hide to tray", lambda icon, item: window.hide()),
    ]
    if console_hwnd is not None:
        menu_items.append(
            pystray.MenuItem("Hide console window", _toggle_console, checked=_console_hidden)
        )
    menu_items += [
        pystray.MenuItem("Restart", _restart),
        pystray.MenuItem("Quit", _quit),
    ]
    icon = pystray.Icon(
        "memorymap",
        image,
        "MemoryMap AI",
        pystray.Menu(*menu_items),
    )
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def _export_markdown(destination: str) -> int:
    """Write the Markdown export zip to `destination`, with no server.

    Exists for the uninstallers: `./uninstall.sh --export ~/notes.zip`
    should be able to take someone's notes out before `--delete-data`
    removes them, on a machine where the app is exactly what is being
    removed and a browser download is not an option.

    It calls the same `build_markdown_export` the Settings download uses,
    so there is one archive format and not two. A destination that names a
    directory gets the default filename inside it, which is what someone
    typing `--export .` means.
    """
    from memorymap.api.routes_settings import build_markdown_export
    from memorymap.core import deps

    target = Path(destination).expanduser()
    if target.is_dir():
        target = target / "memorymap-markdown.zip"
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Could not create {target.parent}: {exc}")
        return 1

    db = deps.get_db()
    with db.session() as session:
        payload = build_markdown_export(session)
    try:
        target.write_bytes(payload)
    except OSError as exc:
        print(f"Could not write {target}: {exc}")
        return 1
    print(f"Exported your notes to {target} ({len(payload) // 1024} KB).")
    return 0


def _reset_password() -> int:
    """Forgotten password: clear the credential so setup runs again.

    This is deliberately a command you type at a terminal, not a button in the
    UI: a "reset my password" link inside the app someone is locked out of
    would just be a way in for anyone at the keyboard.

    It is honest about the two halves of what happens, because they are very
    different:

    - Ordinary notes are NOT encrypted with the password. They are plain rows
      in SQLite, and they come back untouched.
    - Private notes ARE. Their data key is wrapped with a key derived from the
      password, so without it they cannot be decrypted by anyone, including
      this command. Clearing the credential strands them permanently.
    """
    from memorymap.core import deps
    from memorymap.core.database import Entry, User, Vault
    from sqlalchemy import func, select

    config = deps.get_config()
    db = deps.get_db()
    with db.session() as session:
        user = session.scalar(select(User))
        if user is None:
            print("No password is set, start the app and it will ask you to choose one.")
            return 0
        private_count = session.scalar(
            select(func.count(Entry.id)).where(Entry.is_private == True)  # noqa: E712
        ) or 0

        print(f"Notebook: {config.data_dir}")
        print("\nClearing the password will let you set a new one next start.")
        print("  · Your ordinary notes are not encrypted and come back untouched.")
        if private_count:
            print(
                f"  · Your {private_count} PRIVATE note(s) are encrypted with the "
                "current\n    password. They cannot be recovered without it, not by "
                "this command,\n    not by anyone. They will be lost."
            )
        else:
            print("  · You have no private notes, so nothing is unrecoverable.")

        answer = input("\nType RESET to confirm: ").strip()
        if answer != "RESET":
            print("Cancelled: nothing was changed.")
            return 1

        session.delete(user)
        # The wrapped key is useless once its password is gone; leaving it
        # would make the next setup silently reuse a vault it cannot open.
        for row in session.scalars(select(Vault)):
            session.delete(row)
        session.commit()

    print("\nPassword cleared. Start the app and it will ask you to set a new one.")
    if private_count:
        print("The private notes that were encrypted with the old password are gone.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="memorymap", description="MemoryMap AI")
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="open MemoryMap in its own app window (needs pywebview)",
    )
    parser.add_argument(
        "--export",
        metavar="PATH",
        help="write your notes to PATH as a Markdown zip and exit "
        "(the same archive Settings downloads)",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="forgot your password: clear it so you can set a new one "
        "(private notes encrypted with it are lost)",
    )
    # Internal: set by _maybe_relaunch_hidden's own pythonw.exe relaunch to
    # mark "this already is the console-less process," so it doesn't try to
    # relaunch itself again. Not something a person should ever type, hence
    # SUPPRESS rather than a documented flag.
    parser.add_argument("--hidden-relaunch", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.export:
        raise SystemExit(_export_markdown(args.export))
    if args.reset_password:
        raise SystemExit(_reset_password())
    if args.desktop:
        _run_desktop(hidden_relaunch=args.hidden_relaunch)
    else:
        _run_server()


if __name__ == "__main__":
    main()
