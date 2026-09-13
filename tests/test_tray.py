"""The system-tray menu: Open, New note, View Logs, [console], Restart, Quit.

None of this can be driven here, pystray needs a real desktop session and the
menu callbacks close over a pywebview window. What *is* testable is the part
that was actually broken, and it was broken in the one build where nobody would
see it: the packaged Windows app, which has no console to print an error to.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SOURCE = Path("src/memorymap/__main__.py").read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    """The same shape as the real one: flags only, no positionals."""
    parser = argparse.ArgumentParser(prog="memorymap")
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--hidden-relaunch", action="store_true")
    return parser


def test_the_frozen_build_would_die_on_the_old_restart_argv():
    """Why the fix below exists, pinned as an executable fact.

    `os.execv(sys.executable, [sys.executable, *sys.argv])` is correct from
    source, where sys.executable is python.exe and sys.argv[0] is the script.
    In a PyInstaller build **both are the .exe**, so the executable's own path
    arrives as a positional argument.
    """
    frozen_argv = ["MemoryMap.exe", "--desktop"]
    old_style = ["MemoryMap.exe", *frozen_argv]  # execv's argv
    try:
        _parser().parse_args(old_style[1:])
    except SystemExit as exit_:
        assert exit_.code == 2
    else:
        raise AssertionError("expected argparse to reject the duplicated exe path")


def test_the_fixed_argv_parses_in_both_install_types():
    frozen_argv = ["MemoryMap.exe", "--desktop"]
    # Frozen: argv is already correct as-is.
    assert _parser().parse_args(frozen_argv[1:]).desktop is True
    # Source: python.exe plus the script path.
    source_argv = ["/usr/bin/python", "/src/memorymap/__main__.py", "--desktop"]
    assert _parser().parse_args(source_argv[2:]).desktop is True


def test_restart_branches_on_frozen():
    block = SOURCE.split("def _restart(")[1].split("def ")[0]
    assert 'getattr(sys, "frozen", False)' in block
    assert "os.execv(sys.executable, argv)" in block


# --- the menu items ------------------------------------------------------------


def test_the_menu_has_the_items_it_advertises():
    for label in ("Open MemoryMap AI", "New note", "View Logs", "Restart", "Quit"):
        assert f'pystray.MenuItem("{label}"' in SOURCE, label


def test_showing_the_window_also_raises_it():
    """`show()` un-minimises but does not raise or focus, so clicking a menu
    item while the window was merely behind something did nothing visible."""
    for callback in ("_open", "_view_logs", "_new_note"):
        block = SOURCE.split(f"def {callback}(")[1].split("\n    def ")[0]
        assert "_focus_window(window)" in block, callback


def test_no_tray_item_can_reach_past_the_lock_screen():
    """Reported once already for View Logs, which used to open Settings
    unconditionally. Any item that runs JS in the page has to check."""
    for callback in ("_view_logs", "_new_note"):
        block = SOURCE.split(f"def {callback}(")[1].split("\n    def ")[0]
        assert "lock-overlay" in block, callback


def test_quick_capture_targets_an_element_that_exists():
    """The id was wrong first time, `entry-input`, which is not in the page.
    A tray item that focuses nothing looks like it did nothing."""
    block = SOURCE.split("def _new_note(")[1].split("\n    def ")[0]
    ids = re.findall(r"getElementById\('([^']+)'\)", block)
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    for element_id in ids:
        assert f'id="{element_id}"' in html, element_id


def test_a_missing_tray_backend_never_takes_the_launcher_down():
    """pystray picks a backend at import time and that backend's init can raise
    anything: found here as an Xlib error on a headless box. A missing tray
    icon is cosmetic; the window is not."""
    block = SOURCE.split("def _start_tray(")[1].split("\ndef ")[0]
    assert "except ImportError:" in block
    assert "except Exception as exc:" in block
    assert block.count("return None") >= 2


# --- closing the window is not quitting the app ---------------------------------


def test_closing_the_window_hides_it_rather_than_quitting():
    """Asked for directly: "make it so the app window can be closed but the
    app will still be open in the system tray… so there is a difference
    between minimising the app and quitting the app"."""
    block = SOURCE.split("def _on_closing(")[1].split("\n        window.events.closing")[0]
    assert "window.hide()" in block
    assert "return False" in block, "returning False is what cancels the real close"


def test_close_to_tray_is_a_choice_and_defaults_to_on():
    block = SOURCE.split("def _on_closing(")[1].split("\n        window.events.closing")[0]
    assert 'get_preference("close_to_tray", True)' in block
    # Off means the X button really quits, and that path skips the lifespan
    # handler, so it has to stop background work itself.
    quitting = block.split('if not config.get_preference("close_to_tray", True):')[1]
    assert "_stop_background_work()" in quitting
    assert "return True" in quitting


def test_the_hide_explains_itself_exactly_once():
    """An app that tells you the same thing every time you close it is worse
    than one that never tells you."""
    block = SOURCE.split("def _on_closing(")[1].split("\n        window.events.closing")[0]
    assert "tray_hide_explained" in block
    assert 'set_preference("tray_hide_explained", True)' in block
    assert "tray_icon.notify(" in block


def test_the_setting_round_trips_through_preferences():
    """A field Pydantic doesn't know about is silently dropped, which is how a
    switch that looks like it saves doesn't: the same bug this file's
    console-mode tests exist for."""
    settings = Path("src/memorymap/api/routes_settings.py").read_text(encoding="utf-8")
    assert "close_to_tray: bool | None = None" in settings
    assert '"close_to_tray": config.get_preference("close_to_tray", True)' in settings
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'id="pref-close-to-tray"' in html


# --- the abrupt exits still stop background work --------------------------------


def test_quit_and_restart_stop_background_work_before_exiting():
    """`os._exit` and `os.execv` skip every shutdown hook this process has,
    including the lifespan handler that stops background jobs, so quitting
    from the tray was the one exit that left pip and SearXNG running."""
    for callback in ("_quit", "_restart"):
        block = SOURCE.split(f"def {callback}(")[1].split("\n    def ")[0]
        assert "_stop_background_work()" in block, callback
        # Before, not after: there is no after.
        # `rindex`, not `index`: the comment above the call names it too, and
        # matching the prose instead of the code is how this test would pass
        # for a version that stops nothing.
        exit_call = "os._exit(0)" if callback == "_quit" else "os.execv"
        assert block.index("_stop_background_work()") < block.rindex(exit_call), callback


def test_stopping_background_work_never_raises():
    """It runs on the way out. A Quit button that throws is a Quit button that
    leaves the window on screen."""
    block = SOURCE.split("def _stop_background_work()")[1].split("\ndef ")[0]
    assert "except Exception" in block
    assert "bgtasks.stop_all()" in block


# --- the menu lands on features, not just on tabs --------------------------------


def test_the_menu_reaches_the_features_it_names():
    """Reported: "the options and buttons in the system tray dont fully
    navigate to the propper features, just the tabs or settings modal"."""
    for label in ("Ask a question", "Search everything", "Reminders",
                  "Whiteboard", "Background tasks", "Settings", "Hide to tray"):
        assert f'pystray.MenuItem(\n            "{label}"' in SOURCE or \
            f'pystray.MenuItem("{label}"' in SOURCE, label


def test_every_generated_menu_item_carries_the_lock_guard():
    """The guard lives in the factory rather than in each item, which is the
    reason it cannot be forgotten for a new one."""
    block = SOURCE.split("def _go(js: str):")[1].split("\n    def _view_logs")[0]
    assert "lock-overlay" in block
    assert "window.show()" in block and "_focus_window(window)" in block


def test_the_tray_only_calls_frontend_functions_that_exist():
    """A tray item that calls a function nobody defined does nothing and says
    nothing: the exact failure the report describes.

    Widened after a real miss: this used to scan only the `menu_items = [...]`
    list literal, which covers an inline `_go("...")` call but not a named
    callback's own body: exactly where `_view_logs` called `showSettingsSection`,
    a function that existed nowhere in the frontend, for at least one whole
    session before being caught. Scoped from `_go`'s own definition (the
    first tray-navigation helper) through the end of `menu_items`, which
    covers `_go`, `_view_logs`, `_new_note` and the list itself in one pass, 
    everything that runs JS in the page on this menu.
    """
    import re as _re

    menu = SOURCE.split("def _go(js: str):")[1].split("icon = pystray.Icon(")[0]
    names = set(_re.findall(r"typeof (\w+) === 'function'", menu))
    js = "".join(
        Path(f"frontend/{name}").read_text(encoding="utf-8")
        for name in ("app.js", "settings.js", "library.js")
    )
    for name in names:
        assert _re.search(rf"(async )?function {name}\b", js), name
