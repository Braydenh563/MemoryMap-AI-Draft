"""The desktop window's taskbar icon (Windows only).

Windows groups the taskbar by AppUserModelID, and a Python-hosted process
inherits Python's: which is why the window's own icon can be set correctly
and the taskbar still shows the snake. `_run_desktop` sets an explicit
AppUserModelID to fix that, but only ever on Windows: `ctypes.windll` does
not exist anywhere else, so an unguarded call would be an AttributeError at
import time on every other platform this app runs on.

This suite cannot run on Windows, so it cannot prove the fix *works* there, 
only that the branch is genuinely gated by `sys.platform`, not merely
swallowed by the surrounding try/except, and that the launcher still starts
cleanly on the platform this sandbox actually has.
"""

from __future__ import annotations

import os
import sys
import types
import warnings
from pathlib import Path

import pytest

import memorymap.__main__ as launcher
from memorymap.core import startup_status


@pytest.fixture(autouse=True)
def _restore_desktop_env_var():
    """`_run_desktop` sets `MEMORYMAP_DESKTOP=1` directly on `os.environ`
    (§35E: test_file_save.py keys export behaviour off it), not through
    `monkeypatch`. `monkeypatch.delenv(..., raising=False)` looks like the
    right guard but is a no-op when the var is already absent, it only
    records an undo step for a key it actually deletes, so it would NOT
    have caught this: it silently missed the leak in an earlier version of
    this file, and MEMORYMAP_DESKTOP=1 stayed set for every test that ran
    afterwards in the same process. This restores the exact pre-test value
    (present or absent) no matter what the launcher does to it.
    """
    original = os.environ.get("MEMORYMAP_DESKTOP")
    yield
    if original is None:
        os.environ.pop("MEMORYMAP_DESKTOP", None)
    else:
        os.environ["MEMORYMAP_DESKTOP"] = original


class _FakeEvents:
    """Just enough of pywebview's `window.events` for `_start_tray`'s
    `window.events.closing += handler` to work without erroring, real
    pywebview's `Event` supports `+=` via `__iadd__`; this is the same
    protocol with nothing behind it."""

    def __init__(self):
        self.closing_handlers: list = []

    def __iadd__(self, handler):
        self.closing_handlers.append(handler)
        return self


class _FakeWindow:
    """Stands in for the `pywebview.Window` `_run_desktop` gets back from
    `create_window`. `_boot_and_swap` (§ the loading-window handoff) calls
    `evaluate_js`/`load_url` on whatever `create_window` returned: recording
    both here is what lets a test prove that handoff actually happened,
    which recording only the top-level `start(**kwargs)` call could not."""

    def __init__(self):
        self.evaluate_js_calls: list[str] = []
        self.load_url_calls: list[str] = []
        self.show_calls = 0
        self.events = _FakeEvents()

    def evaluate_js(self, script):
        self.evaluate_js_calls.append(script)

    def load_url(self, url):
        self.load_url_calls.append(url)

    def show(self):
        self.show_calls += 1

    def hide(self):
        pass

    def destroy(self):
        pass


def _fake_webview(monkeypatch, *, icon_kwarg_supported=True, run_start_func=False):
    """A stand-in for the optional `pywebview` package, which isn't
    installed here (CLAUDE.md's dependency list deliberately omits it).

    `run_start_func`: real `webview.start(func, args, ...)` calls `func`
    on its own thread once the window is open, `_run_desktop` now hands it
    `_boot_and_swap`, the loading-window-to-real-app handoff. Most tests
    don't want that running (it starts a real server thread and polls a
    real socket); pass True for the tests that specifically exercise it.
    """
    calls = {"create_window": None, "start": None, "window": None}

    def create_window(title, url=None, html=None, **kwargs):
        window = _FakeWindow()
        calls["create_window"] = {"title": title, "url": url, "html": html, "kwargs": kwargs}
        calls["window"] = window
        return window

    def start(func=None, args=None, **kwargs):
        if not icon_kwarg_supported and "icon" in kwargs:
            raise TypeError("start() got an unexpected keyword argument 'icon'")
        calls["start"] = kwargs
        if run_start_func and func is not None:
            func(*(args if isinstance(args, tuple) else (args,) if args is not None else ()))

    fake = types.ModuleType("webview")
    fake.create_window = create_window
    fake.start = start
    monkeypatch.setitem(sys.modules, "webview", fake)
    return calls


def _quiet_server_thread(monkeypatch):
    """`_run_desktop` starts uvicorn on a background thread and waits for it
    to actually start accepting connections. Neither is needed to test the
    window setup: and since `_run_server` is mocked to a no-op below,
    nothing real is ever listening on HOST:PORT for `_wait_for_server`'s own
    poll loop to find, which would otherwise burn its whole real-time
    timeout on every test that uses this fixture."""
    monkeypatch.setattr(launcher, "_run_server", lambda: None)
    monkeypatch.setattr(launcher, "_wait_for_server", lambda timeout=20.0: True)


def test_wait_for_server_returns_once_something_is_actually_listening(monkeypatch):
    """The desktop window used to open after a flat `time.sleep(1.0)` guess
    at how long uvicorn takes to bind, reported directly as a black screen
    on startup on a cold/slow start that took longer than that. This proves
    the replacement polls a real socket rather than guessing: it returns
    False while nothing is listening on that port, and True as soon as
    something is."""
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    host, port = listener.getsockname()
    monkeypatch.setattr(launcher, "HOST", host)
    monkeypatch.setattr(launcher, "PORT", port)

    # Bound but not listening yet: connections are refused.
    assert launcher._wait_for_server(timeout=0.3) is False

    listener.listen(1)
    try:
        assert launcher._wait_for_server(timeout=2.0) is True
    finally:
        listener.close()


def test_windows_only_branch_is_not_taken_on_this_platform(monkeypatch, tmp_path):
    """The AppUserModelID call is gated by `sys.platform == "win32"`, not
    merely caught if it fails, proven by installing a fake `ctypes.windll`
    that WOULD succeed if called, and asserting it never is, here on Linux.
    """
    assert sys.platform != "win32", "this test's premise requires a non-Windows sandbox"

    called = {"set_app_id": False}

    class _FakeShell32:
        @staticmethod
        def SetCurrentProcessExplicitAppUserModelID(app_id):
            called["set_app_id"] = True

    class _FakeWindll:
        shell32 = _FakeShell32

    import ctypes

    monkeypatch.setattr(ctypes, "windll", _FakeWindll, raising=False)
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    _quiet_server_thread(monkeypatch)
    _fake_webview(monkeypatch)

    launcher._run_desktop()  # must not raise

    assert called["set_app_id"] is False


def test_desktop_launcher_still_starts_the_window(monkeypatch, tmp_path):
    """Sanity check for the rest of `_run_desktop`, so a future edit to the
    icon/AppUserModelID block can't silently break window creation itself."""
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    _quiet_server_thread(monkeypatch)
    calls = _fake_webview(monkeypatch)

    launcher._run_desktop()

    assert calls["create_window"] is not None
    assert calls["create_window"]["title"] == "MemoryMap AI"
    assert calls["start"] is not None
    # The window opens on the loading placeholder, not the real server URL, 
    # see the loading-window tests below for the handoff itself.
    assert calls["create_window"]["url"] is None
    # `_loading_html()` rather than the bare constant since Brief 17: the
    # page is seeded with the launcher's own step history, read out of
    # MM_SPLASH_FILE before `_close_launch_splash` deletes it, so the step
    # list carries on from the pre-Python splash instead of starting empty.
    assert calls["create_window"]["html"] == launcher._loading_html()
    assert launcher._LOADING_HTML in calls["create_window"]["html"] or (
        "__mmSeed" in calls["create_window"]["html"]
    )


def test_loading_window_swaps_to_the_real_url_once_the_server_answers(monkeypatch, tmp_path):
    """The core of the loading-window feature: `_boot_and_swap` (handed to
    `webview.start` as `func=`) starts the server and, once it's reachable,
    points the *same* window at the real URL rather than opening a second
    one. Proven by actually running `_boot_and_swap` (`run_start_func=True`)
    against a fake server/progress poll, not just asserting it was wired up.
    """
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "_run_server", lambda: None)
    monkeypatch.setattr(launcher, "_wait_for_server_with_progress", lambda window, timeout=45.0: True)
    calls = _fake_webview(monkeypatch, run_start_func=True)

    launcher._run_desktop()

    window = calls["window"]
    assert window is not None
    assert window.load_url_calls == [f"http://{launcher.HOST}:{launcher.PORT}"]
    # Asked for directly: the window must take focus once it swaps from the
    # loading page to the real app, not just navigate silently in place.
    assert window.show_calls >= 1
    assert any("window.focus()" in call for call in window.evaluate_js_calls)


def test_loading_window_shows_an_error_if_the_server_never_comes_up(monkeypatch, tmp_path):
    """The other half: a server that never answers must not leave the window
    stuck on an indefinite spinner with no explanation, `_boot_and_swap`
    pushes `__mmSetError` into the page instead of calling `load_url`."""
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "_run_server", lambda: None)
    monkeypatch.setattr(launcher, "_wait_for_server_with_progress", lambda window, timeout=45.0: False)
    calls = _fake_webview(monkeypatch, run_start_func=True)

    launcher._run_desktop()

    window = calls["window"]
    assert window.load_url_calls == []
    assert any("__mmSetError" in call for call in window.evaluate_js_calls)
    # No focus-steal on the error path, there's no real app underneath to
    # bring forward, just the same loading window now showing an error.
    assert window.show_calls == 0
    assert not any("window.focus()" in call for call in window.evaluate_js_calls)


def test_progress_poll_narrates_startup_status_phase_changes(monkeypatch, tmp_path):
    """`_wait_for_server_with_progress` is what actually reads
    `startup_status.get_phase()` and pushes it to the window, proven here
    directly, independent of the rest of `_run_desktop`, against a real
    (if never-listening) socket so it also has to time out and return False
    rather than hang the test."""
    monkeypatch.setattr(launcher, "HOST", "127.0.0.1")
    monkeypatch.setattr(launcher, "PORT", 1)  # nothing listens on port 1
    original_phase = startup_status.get_phase()
    try:
        startup_status.set_phase("Warming up search…")
        window = _FakeWindow()

        result = launcher._wait_for_server_with_progress(window, timeout=0.3)

        assert result is False
        assert any("Warming up search" in call for call in window.evaluate_js_calls)
    finally:
        startup_status.set_phase(original_phase)


def test_tray_is_not_attempted_on_this_non_windows_platform(monkeypatch, tmp_path):
    """`_start_tray` runs pystray's event loop off the main thread, which its
    own docstring says only Windows' backend is known to tolerate (macOS was
    excluded from the desktop build for exactly this reason, and Linux's
    GTK-based backend has the same main-thread-only constraint as macOS's
    AppKit). The call is gated by `sys.platform == "win32"`, not merely
    left to fail safely if attempted, proven here by making `_start_tray`
    itself raise if it's ever called, on this non-Windows sandbox.
    """
    assert sys.platform != "win32", "this test's premise requires a non-Windows sandbox"

    def _explode(window, icon_path):
        raise AssertionError("_start_tray must not be called on this platform")

    monkeypatch.setattr(launcher, "_start_tray", _explode)
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    _quiet_server_thread(monkeypatch)
    _fake_webview(monkeypatch)

    launcher._run_desktop()  # must not raise


def test_the_taskbar_icon_is_a_png_on_linux_not_the_windows_ico(monkeypatch, tmp_path):
    """GdkPixbuf (Linux's icon loader, via GTK) was never actually run
    against the .ico this app ships for Windows/macOS, icon-512.png is the
    one format confirmed to exist and that every platform accepts, so Linux
    gets that one instead of gambling on the untested format."""
    assert sys.platform.startswith("linux"), "this test's premise requires a Linux sandbox"

    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    _quiet_server_thread(monkeypatch)
    calls = _fake_webview(monkeypatch)

    launcher._run_desktop()

    icon = calls["create_window"]["kwargs"].get("icon") or calls["start"].get("icon")
    assert icon is not None
    assert icon.endswith("icon-512.png")


def test_desktop_launcher_degrades_if_icon_kwarg_is_unsupported(monkeypatch, tmp_path):
    """An older pywebview without `icon=` must not crash the launcher, the
    desktop app is the only way in for someone who installed it that way."""
    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    _quiet_server_thread(monkeypatch)
    calls = _fake_webview(monkeypatch, icon_kwarg_supported=False)

    launcher._run_desktop()  # must not raise, even though start() TypeErrors once

    assert calls["start"] is not None


# --- the tray's "Hide console window" item ----------------------------------
#
# `_start_tray` itself is not gated by sys.platform (its caller is), so
# unlike the AppUserModelID/pystray-event-loop branches above, this can be
# called directly here with fake pystray/PIL/ctypes.windll stand-ins, this
# sandbox still can't prove a real Windows console actually hides, but it can
# prove the menu item is built (or skipped) correctly and drives the right
# Win32 call with the right flag.


def _fake_pystray_and_pil(monkeypatch):
    created = {}

    class FakeMenuItem:
        def __init__(self, text, action, default=False, checked=None):
            self.text = text
            self.action = action
            self.checked = checked

    class FakeMenu:
        #: pystray's own sentinel for a divider between menu groups. The real
        #: `pystray.Menu` carries it as a class attribute, and the tray menu
        #: uses one to separate "do something with the app" from "hide it".
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            created["menu"] = menu

        def run(self):
            pass

        def stop(self):
            pass

    fake_pystray = types.ModuleType("pystray")
    fake_pystray.MenuItem = FakeMenuItem
    fake_pystray.Menu = FakeMenu
    fake_pystray.Icon = FakeIcon
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)

    fake_image_mod = types.ModuleType("PIL.Image")
    fake_image_mod.new = lambda *a, **k: object()
    fake_image_mod.open = lambda *a, **k: object()
    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = fake_image_mod
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", fake_image_mod)

    return created


def _fake_pystray_only(monkeypatch):
    """Like `_fake_pystray_and_pil`, but leaves the real `PIL.Image` in place
    so a test can exercise the actual ICO decoder against a real file."""
    created = {}

    class FakeMenuItem:
        def __init__(self, text, action, default=False, checked=None):
            self.text = text
            self.action = action
            self.checked = checked

    class FakeMenu:
        #: pystray's own sentinel for a divider between menu groups. The real
        #: `pystray.Menu` carries it as a class attribute, and the tray menu
        #: uses one to separate "do something with the app" from "hide it".
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            created["menu"] = menu
            created["image"] = image

        def run(self):
            pass

        def stop(self):
            pass

    fake_pystray = types.ModuleType("pystray")
    fake_pystray.MenuItem = FakeMenuItem
    fake_pystray.Menu = FakeMenu
    fake_pystray.Icon = FakeIcon
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)

    return created


def test_tray_icon_loads_the_real_ico_without_a_pillow_size_warning(monkeypatch):
    """frontend/icon.ico's largest frame doesn't match the size recorded in
    its own directory header, which makes Pillow's ICO decoder raise a
    `UserWarning: Image was not the expected size`, reproduced directly
    against this exact file before this test was written. `_start_tray`
    must load it without that warning escaping, not merely without raising
    an exception (a warning is silent by default, which is exactly what let
    it go unnoticed for as long as it did).

    Needs *real* Pillow, unlike every other test in this file, pystray is
    faked, but the point here is decoding the real icon.ico, which a fake
    PIL can't stand in for. Pillow is the "desktop" extra
    (pyproject.toml), not requirements.txt, so plain CI doesn't have it: 
    caught by a real CI failure (Tests (Python 3.11), passing locally only
    because Pillow happens to already be in this venv) after this test was
    first written skip-less."""
    pytest.importorskip("PIL")
    _fake_pystray_only(monkeypatch)
    icon_path = Path(__file__).resolve().parent.parent / "frontend" / "icon.ico"
    assert icon_path.is_file()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        icon = launcher._start_tray(_fake_window(), icon_path, None, False)

    assert icon is not None
    assert not any(issubclass(w.category, UserWarning) for w in caught)


def _fake_window():
    return types.SimpleNamespace(show=lambda: None, evaluate_js=lambda js: None)


@pytest.fixture()
def _config_dir(tmp_path, monkeypatch):
    """`_toggle_console` persists the show_console_on_startup preference via
    deps.get_config(), a global singleton: point it at a fresh temp dir for
    this test only, and reset it afterward so it can't leak into other
    tests in this file or the ones that run after it."""
    from memorymap.core import deps

    monkeypatch.setenv("MEMORYMAP_DATA_DIR", str(tmp_path))
    deps.reset_app_state()
    yield
    deps.reset_app_state()


def _fake_windll(monkeypatch, *, console_hwnd, show_window_calls=None):
    """`IsWindowVisible`/`GetClassNameW` cover `_apply_console_visibility`
    and `_window_class_name`'s own diagnostic logging; the ancestor-walk
    (`CreateToolhelp32Snapshot` etc.) is deliberately left unfaked, its own
    try/except degrading to "found nothing extra" on a missing/incomplete
    `ctypes.windll` shape is exactly the behaviour worth exercising here,
    the same way this sandbox itself exercises it on every real test run.
    """
    import ctypes

    visible_state = {console_hwnd: True}

    def _show_window(hwnd, flag):
        if show_window_calls is not None:
            show_window_calls.append((hwnd, flag))
        visible_state[hwnd] = flag != 0  # SW_HIDE == 0, everything else shows it

    fake = types.SimpleNamespace(
        kernel32=types.SimpleNamespace(GetConsoleWindow=lambda: console_hwnd),
        user32=types.SimpleNamespace(
            ShowWindow=_show_window,
            IsWindowVisible=lambda hwnd: visible_state.get(hwnd, True),
            GetClassNameW=lambda hwnd, buf, size: None,
        ),
    )
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)


def test_tray_hide_console_item_toggles_a_real_console_window_and_persists_it(
    monkeypatch, tmp_path, _config_dir
):
    show_window_calls = []
    _fake_windll(monkeypatch, console_hwnd=12345, show_window_calls=show_window_calls)
    created = _fake_pystray_and_pil(monkeypatch)

    icon = launcher._start_tray(_fake_window(), tmp_path / "missing.ico", 12345, False)
    assert icon is not None

    # `getattr`: a separator is pystray's own sentinel object, not a MenuItem.
    items = {
        getattr(item, "text", None): item for item in created["menu"].items
    }
    hide_item = items["Hide console window"]
    assert hide_item.checked(None) is False

    hide_item.action(icon, hide_item)
    assert show_window_calls == [(12345, 0)]  # SW_HIDE
    assert hide_item.checked(None) is True

    hide_item.action(icon, hide_item)
    assert show_window_calls[-1] == (12345, 5)  # SW_SHOW
    assert hide_item.checked(None) is False

    # The last toggle left it shown, that choice must survive to the next
    # launch, not just this session (asked for directly).
    from memorymap.core import deps

    assert deps.get_config().get_preference("show_console_on_startup") is True


def test_tray_hide_console_item_reflects_the_caller_s_initial_state(monkeypatch, tmp_path):
    """The window has already been hidden by _run_desktop before the tray is
    even built (the show_console_on_startup preference, applied before the
    window opens): the checkbox must start checked, not always False."""
    _fake_windll(monkeypatch, console_hwnd=12345)
    created = _fake_pystray_and_pil(monkeypatch)

    launcher._start_tray(_fake_window(), tmp_path / "missing.ico", 12345, True)

    # `getattr`: a separator is pystray's own sentinel object, not a MenuItem.
    items = {
        getattr(item, "text", None): item for item in created["menu"].items
    }
    assert items["Hide console window"].checked(None) is True


def test_tray_has_no_hide_console_item_without_a_real_console(monkeypatch, tmp_path):
    """The packaged installer's PyInstaller build sets console=False, so
    GetConsoleWindow() returns NULL there: nothing to hide, and the menu
    item asked for a way to bring back must not appear with no console to
    bring back."""
    created = _fake_pystray_and_pil(monkeypatch)

    launcher._start_tray(_fake_window(), tmp_path / "missing.ico", None, False)

    # `getattr`: a separator is pystray's own sentinel object, not a MenuItem.
    texts = [getattr(item, "text", None) for item in created["menu"].items]
    assert "Hide console window" not in texts
    # "New note" sits second on purpose: it is the only item on this menu that
    # does the app's actual job rather than manage the app, and it is the
    # reason a notebook earns a tray icon at all.
    # The order is deliberate and each group is a different kind of thing:
    # capture and ask (why a notebook earns a tray icon at all), then places
    # in the app, then managing the app itself. Reported as "the options and
    # buttons in the system tray dont fully navigate to the propper features,
    # just the tabs or settings modal", every entry between "New note" and
    # "View Logs" is the answer to that.
    assert texts == [
        "Open MemoryMap AI",
        "New note",
        "Ask a question",
        "Search everything",
        "Record a meeting",
        "Reminders",
        "Whiteboard",
        "Background tasks",
        "Settings",
        "View Logs",
        None,  # separator
        "Hide to tray",
        "Restart",
        "Quit",
    ]


def test_get_console_hwnd_returns_none_on_this_non_windows_platform():
    """No `ctypes.windll` on this sandbox, and _get_console_hwnd must
    degrade to None rather than raise, the same shape as every other
    Windows-only ctypes call in this launcher."""
    assert sys.platform != "win32", "this test's premise requires a non-Windows sandbox"
    assert launcher._get_console_hwnd() is None


def test_desktop_startup_hides_the_console_when_user_view_is_chosen(
    monkeypatch, tmp_path, _config_dir
):
    """`_run_desktop` reads show_console_on_startup and hides the console
    before the window opens when it's off ("User view"), the actual fix
    for "the terminal still shows when I run the application, I want it
    hidden." "Dev view" (console visible) is the default a fresh install
    starts on now, asked for directly, so this exercises the explicit
    User-view choice, not the out-of-the-box state.

    No pythonw.exe exists next to this sandbox's own interpreter, so
    `_maybe_relaunch_hidden` falls back to this ShowWindow attempt rather
    than actually relaunching: exercising the same fallback path a real
    Windows install without a standard CPython layout would hit."""
    from memorymap.core import deps

    deps.get_config().set_preference("show_console_on_startup", False)

    show_window_calls = []
    _fake_windll(monkeypatch, console_hwnd=99, show_window_calls=show_window_calls)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_start_tray", lambda *a, **k: None)
    _quiet_server_thread(monkeypatch)
    _fake_webview(monkeypatch)

    launcher._run_desktop()

    assert show_window_calls == [(99, 0)]  # SW_HIDE


def test_console_is_hidden_before_the_slow_server_wait_not_after(monkeypatch, tmp_path, _config_dir):
    """The console used to hide only after _wait_for_server() returned, which
    reads deps.get_config()'s singleton: safe only once create_app() has run
    on the server thread. On a slow/cold start (embeddings warmup etc.) that
    wait is exactly the multi-second gap this app is already known for, so
    the console sat fully visible for all of it, reported directly as "the
    terminal still shows on startup" despite User view being chosen. The
    fix reads preferences.json with a throwaway ConfigManager before the
    server thread even starts, so hiding no longer waits on it at all, 
    proven here by recording whether the hide already happened by the time
    _wait_for_server_with_progress is reached, not just that it eventually
    happens. (That wait, and the function that does it, both moved into
    `_boot_and_swap`, run here via `run_start_func=True`, when the
    loading-window feature stopped the window itself waiting on
    `_wait_for_server`; the guarantee this test protects is unchanged.)"""
    from memorymap.core import deps

    deps.get_config().set_preference("show_console_on_startup", False)

    show_window_calls = []
    _fake_windll(monkeypatch, console_hwnd=99, show_window_calls=show_window_calls)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_start_tray", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "_run_server", lambda: None)
    hidden_before_wait = []
    monkeypatch.setattr(
        launcher,
        "_wait_for_server_with_progress",
        lambda window, timeout=45.0: hidden_before_wait.append(list(show_window_calls)) or True,
    )
    _fake_webview(monkeypatch, run_start_func=True)

    launcher._run_desktop()

    assert hidden_before_wait == [[(99, 0)]]  # already hidden by the time we'd wait


def test_desktop_startup_leaves_the_console_shown_when_the_preference_says_so(
    monkeypatch, tmp_path, _config_dir
):
    from memorymap.core import deps

    deps.get_config().set_preference("show_console_on_startup", True)

    show_window_calls = []
    _fake_windll(monkeypatch, console_hwnd=99, show_window_calls=show_window_calls)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_start_tray", lambda *a, **k: None)
    _quiet_server_thread(monkeypatch)
    _fake_webview(monkeypatch)

    launcher._run_desktop()

    assert show_window_calls == []  # never hidden
