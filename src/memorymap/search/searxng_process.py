"""Run SearXNG as a local subprocess, the non-Docker (from-source) runtime.

Split out of `searxng_manager.py` (see that module for the two backends this
feeds). This module owns the actual child process once `searxng_install` has
put a virtualenv in place: spawning it, remembering its PID, telling whether
it is still alive without disturbing it (the Windows half of that is its own
small trap: see `_alive_windows`), stopping it, and the port-retry loop that
drives a from-source start end to end.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from memorymap.search import searxng_manager, websearch
from memorymap.search.searxng_install import _install_state, is_checkout
from memorymap.search.searxng_manager import (
    FALLBACK_PORTS,
    SOURCE_START_TIMEOUT,
    SearxngError,
    _pid_file,
    _port_clash,
    _settle_on,
    _source_dir,
    base_url,
    host_port,
)

# `source_installed`, `install_source`, `_venv_python` and `_wait_until_ready`
# are deliberately *not* imported by name above: the test suite monkeypatches
# them as `searxng_manager.<name>` (module-attribute replacement), which only
# rebinds that attribute on the `searxng_manager` module object: a name
# pulled in here with `from ... import name` would keep pointing at the
# original function forever. Calling them as `searxng_manager.<name>(...)`
# below looks the attribute up fresh every time, so a patched or a real
# implementation is picked up exactly as it was when this was one file.
from memorymap.search.searxng_settings import _searxng_env


def _read_pid(data_dir: Path) -> int | None:
    try:
        record = json.loads(_pid_file(data_dir).read_text(encoding="utf-8"))
        return int(record.get("pid")) or None
    except (OSError, ValueError, TypeError):
        return None


_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _alive_windows(pid: int) -> bool:
    """Ask Windows whether the process is still running, without signalling it.

    `os.kill(pid, 0)` is the POSIX idiom and it is actively destructive here:
    on Windows any signal that isn't CTRL_C_EVENT or CTRL_BREAK_EVENT is
    handed to `TerminateProcess`, so "is it alive?" *killed the instance*,
    with exit code 0, and then answered yes. The settings screen polls
    status(), status() asks `_source_state`, and `_source_state` asked this: 
    so a SearXNG that had just started was shot within a couple of seconds of
    starting, every time, and the app then reported that it "started but never
    answered". That is the §8b symptom.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means something is there; anything else means it isn't.
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        # A process that genuinely exited with 259 reads as alive. That is the
        # documented cost of this check and it beats terminating the process.
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _alive(pid: int) -> bool:
    """Is this PID still around, without disturbing it?"""
    if os.name == "nt":
        try:
            return searxng_manager._alive_windows(pid)
        except (OSError, AttributeError, ValueError):
            return False
    try:
        os.kill(pid, 0)  # POSIX only: signal 0 checks, it does not deliver
    except OSError:
        return False
    return True


def _terminate(pid: int) -> None:
    """End the process. Raises OSError if it can't be reached."""
    # On Windows os.kill hands the signal number to TerminateProcess, which is
    # what we want *here*, abrupt, but SearXNG has nothing to flush.
    os.kill(pid, signal.SIGTERM)


def _source_state(data_dir: Path) -> str:
    """'running', 'stopped', or 'absent' for the from-source instance."""
    if not searxng_manager.source_installed(data_dir):
        return "absent"
    pid = _read_pid(data_dir)
    return "running" if pid and _alive(pid) else "stopped"


def log_path(data_dir: Path) -> Path:
    """Where SearXNG's own output goes.

    It used to go to DEVNULL, and that is why "SearXNG started but never
    answered. Check the port isn't in use." was the only thing this could ever
    say. A process that dies a second after spawning, a missing dependency, a
    settings file it won't parse, a port already bound, left no trace
    whatsoever, so the message had to guess, and it guessed the same thing
    every time regardless of what actually happened.
    """
    return Path(data_dir) / "searxng" / "searxng.log"


def recent_output(data_dir: Path, lines: int = 12) -> str:
    """The tail of that log, for a failure message and the Logs screen."""
    path = log_path(data_dir)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = [line for line in text.strip().splitlines() if line.strip()][-lines:]
    return "\n".join(tail)


def _start_source(data_dir: Path) -> dict:
    """Spawn SearXNG from its virtualenv and remember the PID."""
    if not searxng_manager.source_installed(data_dir):
        raise SearxngError("SearXNG isn't installed yet.")
    env = _searxng_env(data_dir)
    output = log_path(data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Truncated per start, not appended to: the only question this file
        # answers is "why did *this* attempt fail", and a growing file makes
        # that harder to read, not easier.
        handle = output.open("w", encoding="utf-8")
    except OSError as exc:
        raise SearxngError(f"Couldn't open {output.name} to record output: {exc}") from exc
    try:
        process = subprocess.Popen(  # noqa: S603  # fixed args, no shell
            [str(searxng_manager._venv_python(data_dir)), "-m", "searx.webapp"],
            # Only the git path has a checkout to run from; a tarball install
            # lives in site-packages, and passing a directory that isn't there
            # makes Popen fail with a FileNotFoundError that reads as "SearXNG
            # is missing" rather than "that folder is". A leftover folder that
            # is no longer a checkout is not somewhere to run from either.
            cwd=str(src) if is_checkout(src := _source_dir(data_dir)) else None,
            env=env,
            # Both streams into one file, in the order they were written, 
            # SearXNG's startup errors go to whichever it feels like.
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SearxngError(f"Couldn't start SearXNG: {exc}") from exc
    finally:
        # The child holds its own duplicate of the descriptor, so closing
        # this one doesn't cut off its output, it just stops us leaking one
        # handle per start.
        handle.close()
    _pid_file(data_dir).write_text(
        json.dumps({"pid": process.pid, "backend": "source"}), encoding="utf-8"
    )
    return {"url": base_url(), "started": True, "backend": "source"}


def _stop_source(data_dir: Path) -> dict:
    pid = _read_pid(data_dir)
    _pid_file(data_dir).unlink(missing_ok=True)
    if not pid or not _alive(pid):
        return {"stopped": False}
    try:
        _terminate(pid)
    except OSError as exc:
        raise SearxngError(f"Couldn't stop SearXNG: {exc}") from exc
    # Give it a moment to close its socket before anything rebinds the port.
    for _ in range(20):
        if not _alive(pid):
            break
        time.sleep(0.25)
    return {"stopped": True}


def _start_from_source(data_dir: Path, on_ready=None) -> dict:
    """Install on first use (in the background), then spawn the process."""
    if _install_state["error"]:
        error = _install_state["error"]
        _install_state["error"] = ""
        raise SearxngError(error)
    if _install_state["running"]:
        raise SearxngError(
            f"Still setting SearXNG up, {_install_state['step']} "
            + (
                "It will start on its own when the install finishes."
                if _install_state.get("auto_start")
                else "Press Start again when it finishes."
            )
        )
    if not searxng_manager.source_installed(data_dir):
        searxng_manager.install_source(data_dir, on_ready=on_ready)
        raise SearxngError(
            "Setting SearXNG up in its own virtualenv. This takes a few minutes "
            "the first time"
            + (
                ", and it will start on its own when the install finishes."
                if on_ready is not None
                else "; press Start again when it's done."
            )
        )
    if searxng_manager._source_state(data_dir) == "running" and websearch.probe_searxng(base_url()):
        return {"url": base_url(), "started": False, "backend": "source"}
    # The settled port first, then every fallback. choose_port() already
    # avoids ports it can see are taken, but seeing is racy, the honest
    # check is SearXNG itself failing to bind, and that failure is fixed by
    # moving along, not by handing the user a port number to go free up.
    remaining = list(dict.fromkeys((host_port(), *FALLBACK_PORTS)))
    tried: list[int] = []
    while True:
        port = remaining.pop(0)
        tried.append(port)
        _settle_on(port)
        result = searxng_manager._start_source(data_dir)
        pid = _read_pid(data_dir)
        if searxng_manager._wait_until_ready(
            SOURCE_START_TIMEOUT,
            still_starting=lambda: pid is not None and _alive(pid),
        ):
            return result
        # Read what it said *before* stopping it, a SIGTERM adds its own
        # lines, and the interesting ones are the earlier ones.
        said = searxng_manager.recent_output(data_dir)
        searxng_manager._stop_source(data_dir)
        if _port_clash(said):
            if remaining:
                logging.getLogger("memorymap.searxng").info(
                    "Port %s was taken after all, trying %s.", port, remaining[0]
                )
                continue
            raise SearxngError(
                "Every port MemoryMap knows to try was taken: "
                + ", ".join(str(p) for p in tried)
                + ". Set MEMORYMAP_SEARXNG_PORT to a free one and press Start "
                "again."
            )
        logging.getLogger("memorymap.searxng").warning(
            "SearXNG didn't answer within %ss. Its own output was:\n%s",
            SOURCE_START_TIMEOUT,
            said or "(nothing: it wrote no output at all)",
        )
        if said:
            raise SearxngError(
                "SearXNG started but never answered. It said:\n\n"
                f"{said}\n\n"
                f"The full log is at {log_path(data_dir)}."
            )
        raise SearxngError(
            "SearXNG started but wrote nothing and never answered, which "
            "usually means the process died immediately. Check that port "
            f"{host_port()} is free. The log is at {log_path(data_dir)}."
        )
