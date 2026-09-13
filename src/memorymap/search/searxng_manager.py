"""Run a SearXNG instance for the user (optional).

SearXNG is a separate service, it can't be imported into this process, but
the app can still own its lifecycle so "use SearXNG" is a button rather than a
setup guide. We generate a settings file that enables the JSON API (the one
step people always miss), start it, wait for it to answer, and hand back the
URL.

There are two ways to run it, and Docker is only the tidier one:

- **docker**: pull the official image and run a container. Preferred when
  Docker is installed, because upgrades and isolation come for free.
- **source**: SearXNG is a Python app, so it also runs in a virtualenv of its
  own under the data directory, started as a child process. Slower to set up
  (a pip install from git) and it needs `git`, but it needs no Docker at all.

Everything degrades: no backend available, or a failed start, returns a plain
reason and leaves web search on DuckDuckGo.

This module is the orchestrator: it owns the shared primitives every backend
needs (the port that was settled on, `SearxngError`, the generic subprocess
runners, where a source install's files live) and the top-level "start
whichever backend this machine can" / "stop it" / "describe it" entry points.
The four concerns underneath live in their own modules, split out because this
file had grown to soak up all of them at once:

- `searxng_docker.py`, the Docker container lifecycle.
- `searxng_install.py`, downloading and installing SearXNG from source.
- `searxng_process.py`, running the source install as a child process.
- `searxng_settings.py`, the settings.yml MemoryMap generates, and the
  environment (including the Windows `pwd` shim) it runs SearXNG in.

Everything those modules exposed before the split is still reachable as
`searxng_manager.<name>`, this file imports it back in, so nothing outside
this package needs to change what it imports.
"""

from __future__ import annotations

import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from memorymap.search import websearch

# The port SearXNG listens on. 8888 by default, but that is a popular number
# and "something is using port 8888" was a dead end for the user: the advice
# was to go and close whatever had it, which is not always a thing you can do.
# So it is settable, and if the wanted one is taken by something that is not a
# SearXNG, `choose_port()` moves along to one that is free.
DEFAULT_PORT = 8888
HOST_PORT = DEFAULT_PORT  # the default, and what a fresh install will use
# 8080 first because that is what the user suggested, and what SearXNG itself
# listens on inside its own container.
FALLBACK_PORTS = (8080, 8081, 8890, 8899)
# 127.0.0.1, never localhost: SearXNG is told to bind exactly
# SEARXNG_BIND_ADDRESS=127.0.0.1, and on Windows `localhost` often resolves
# to IPv6 ::1 first, so a probe of "localhost" knocked on a door SearXNG
# was not behind, timed out the whole start, and blamed whatever noise sat
# in the log. The address we dial must be the address we bind.
BASE_URL = f"http://127.0.0.1:{HOST_PORT}"

# The port this run settled on, once it has. Sticky for the process, so a
# started SearXNG is still findable by every later status and probe call.
_chosen_port: int | None = None


def _settle_on(port: int) -> None:
    """Make `port` the one every url, probe and settings file agrees on."""
    global _chosen_port
    _chosen_port = port


def host_port() -> int:
    """The port to use: whatever was settled on, else what was asked for."""
    if _chosen_port is not None:
        return _chosen_port
    wanted = os.environ.get("MEMORYMAP_SEARXNG_PORT", "").strip()
    if wanted.isdigit() and 1 <= int(wanted) <= 65535:
        return int(wanted)
    return DEFAULT_PORT


def base_url() -> str:
    # See BASE_URL for why this is an IP literal rather than localhost.
    return f"http://127.0.0.1:{host_port()}"


def _port_free(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR: the question is whether a *live* listener holds it.
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def choose_port() -> int:
    """Settle on a port, now, before starting.

    A port already answering as SearXNG is *better* than a free one, that is
    our own instance from a previous run, and taking a different port would
    start a second copy beside it. Anything else holding the port is a reason
    to move along rather than to fail, which is what used to happen.
    """
    global _chosen_port
    wanted = host_port()
    for port in (wanted, *(p for p in FALLBACK_PORTS if p != wanted)):
        if websearch.probe_searxng(f"http://127.0.0.1:{port}") or _port_free(port):
            _chosen_port = port
            return port
    # Everything is taken. Keep the one that was asked for so the error names
    # the port the user actually configured.
    _chosen_port = wanted
    return wanted


START_TIMEOUT = 90  # image pulls can be slow the first time
# A first from-source start is slower than any Docker start: it imports a few
# hundred modules into a cold interpreter, and on Windows the antivirus reads
# over every one of them on the way. 90 seconds is genuinely not always
# enough, and calling a start that was going to succeed a failure, then
# SIGTERMing it: is the worst outcome available. The wait bails out early
# when the process dies, so the higher ceiling costs nothing when something
# is actually wrong.
SOURCE_START_TIMEOUT = 180
COMMAND_TIMEOUT = 20


class SearxngError(RuntimeError):
    """Something stopped us managing the instance."""


def _source_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "searxng" / "src"


def _venv_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "searxng" / "venv"


def _venv_python(data_dir: Path) -> Path:
    venv = _venv_dir(data_dir)
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _pid_file(data_dir: Path) -> Path:
    return Path(data_dir) / "searxng" / "run.json"


#: Set to stop whatever `_run_streaming` is currently running. One event for
#: all of them because only one SearXNG setup ever runs at a time (the install
#: takes a lock). Asked for directly: "allow the quitting/killing of
#: background tasks as well", and this is the task with the longest silence
#: of any of them: a source install compiles wheels for minutes.
_stop_streaming = threading.Event()


def stop_streaming() -> None:
    """Ask the running setup command to stop. Idempotent."""
    _stop_streaming.set()


def _run_streaming(
    args: list[str], timeout: int, on_line
) -> subprocess.CompletedProcess:
    """Run a command, handing each line to `on_line` as it is printed.

    `_run` captures output and returns it when the command finishes, which is
    right for a two-second command and useless for a four-minute one: pip
    building lxml prints steadily for minutes and the user saw none of it, so
    a working install and a hung one looked identical. The lines are the
    evidence that something is happening.

    Reads the pipe from a background thread rather than the caller's `for
    line in process.stdout`: that loop's own deadline check only runs
    *between* lines, so a child that goes quiet without exiting, a stalled
    network mid-download, a hung subprocess, blocked here forever no matter
    what `timeout` said. A daemon thread feeding a queue lets the main thread
    poll with a real timeout even while nothing is being read.
    """
    output: list[str] = []
    try:
        process = subprocess.Popen(  # noqa: S603  # fixed args, no shell
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SearxngError(f"Couldn't run {args[0]}: {exc}") from exc

    lines: queue.Queue[str | None] = queue.Queue()

    def _pump() -> None:
        try:
            for line in process.stdout or []:
                lines.put(line)
        finally:
            lines.put(None)  # sentinel: the pipe is closed, one way or another

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()

    _stop_streaming.clear()
    deadline = time.time() + timeout
    try:
        while True:
            if _stop_streaming.is_set():
                # Killed rather than asked: pip and git have no cooperative
                # stop, and the loop already polls at 1s so this is felt
                # within a second of the button being pressed.
                process.kill()
                raise SearxngError(f"{args[0]} was stopped.")
            remaining = deadline - time.time()
            if remaining <= 0:
                process.kill()
                raise SearxngError(
                    f"{args[0]} took longer than {timeout}s and was stopped."
                )
            try:
                line = lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue  # still within the deadline, just nothing new yet
            if line is None:
                break
            output.append(line)
            on_line(line)
        process.wait(timeout=max(1, int(deadline - time.time())))
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise SearxngError(f"{args[0]} timed out after {timeout}s.") from exc
    finally:
        if process.stdout:
            process.stdout.close()
        reader.join(timeout=5)  # the close() above unblocks the pump's read
    return subprocess.CompletedProcess(
        args, process.returncode, stdout="".join(output), stderr=""
    )


def _run(
    args: list[str], timeout: int = COMMAND_TIMEOUT, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run a setup command. Fixed argument lists only, never a shell."""
    try:
        return subprocess.run(  # noqa: S603  # fixed args, no shell
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SearxngError(f"Couldn't run {args[0]}: {exc}") from exc


def _wait_until_ready(timeout: int = START_TIMEOUT, still_starting=None) -> bool:
    """Poll until SearXNG answers JSON, the process dies, or time runs out.

    `still_starting`, when given, is asked between polls whether the thing
    being waited for is still there to wait for. A process that has died
    cannot become ready, and waiting the full window on it only delays the
    error message its log already holds.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if websearch.probe_searxng(base_url()):
            return True
        if still_starting is not None and not still_starting():
            return False
        time.sleep(2)
    return False


# The log lines that mean "the port, not SearXNG, is the problem", one
# spelling per platform. POSIX raises EADDRINUSE ("Address already in use"),
# Windows raises WinError 10048 ("Only one usage of each socket address …").
_PORT_CLASH_MARKS = (
    "address already in use",
    "eaddrinuse",
    "winerror 10048",
    "only one usage of each socket address",
)


def _port_clash(output: str) -> bool:
    """Did this start die because something else holds the port?"""
    lowered = output.lower()
    return any(mark in lowered for mark in _PORT_CLASH_MARKS)


# Lines that are never the reason something failed, however last they are.
#
# Reported with a screenshot: "Couldn't install SearXNG: [notice] To update,
# run: …python.exe -m pip install --upgrade pip". That notice is pip's parting
# advice, it is printed on almost every run, and it is always the last line, 
# so taking the last line meant reporting it instead of the actual failure,
# every single time an install went wrong. The user is then sent to fix pip,
# which was never the problem.
_NOT_A_REASON = (
    "[notice]",
    "to update, run",
    "you should consider upgrading",
    "warning: you are using pip version",
)


def _reason(result: subprocess.CompletedProcess, prefix: str) -> str:
    """`prefix`, plus the most useful line the command actually printed.

    Prefers a line that names an error, falls back to the last line that isn't
    boilerplate, and says nothing rather than something misleading.
    """
    lines = [
        line.strip()
        for line in (result.stderr or result.stdout or "").strip().splitlines()
        if line.strip()
    ]
    useful = [
        line
        for line in lines
        if not any(marker in line.lower() for marker in _NOT_A_REASON)
    ]
    if not useful:
        return prefix

    # A line that names the failure beats the last line, pip prints the real
    # cause and then several lines of hint after it.
    named = [
        line
        for line in useful
        if line.lower().startswith(("error", "fatal", "exception"))
        or "error:" in line.lower()
    ]
    return f"{prefix}: {(named or useful)[-1]}"


# --- the four concerns, resolved lazily so `searxng_manager.<name>` keeps
# working exactly as it did before the split, without this file importing any
# of them back at module level. It used to: each of those four modules
# imports the shared primitives defined above back from this one, and this
# file returned the favour with a plain `from ... import (...)` block here: 
# which is a real cyclic import (CodeQL: py/import-cycle), even though careful
# ordering made it work. PEP 562's module `__getattr__` gets the same
# attribute lookup: `searxng_manager.docker_available`, `from
# memorymap.search.searxng_manager import install_source`, all of it: but
# resolved (and cached into this module's namespace) on first use instead of
# at import time, so there is no longer an edge from this file back to them.
_FACADE_NAMES: dict[str, tuple[str, ...]] = {
    "searxng_settings": (
        "REMOVED_ENGINES",
        "SETTINGS_TEMPLATE",
        "_engines_sharing_removed_networks",
        "_existing_secret_key",
        "_extra_removes",
        "_PWD_SHIM",
        "_restrict",
        "_searxng_env",
        "_write_pwd_shim",
        "ensure_settings",
        "settings_path",
    ),
    "searxng_docker": (
        "CONTAINER_NAME",
        "DAEMON_PROBE_TIMEOUT",
        "IMAGE",
        "_docker_publishes_beyond_localhost",
        "_docker_state",
        "_publish_spec",
        "_remove_container",
        "_start_docker",
        "docker_available",
        "docker_installed",
    ),
    "searxng_install": (
        "DOWNLOAD_TIMEOUT",
        "INSTALL_STAGES",
        "INSTALL_TIMEOUT",
        "SOURCE_TARBALL",
        "_download",
        "_drop_readonly",
        "_fetch_source",
        "_import_ok",
        "_install_lock",
        "_install_log",
        "_install_progress",
        "_install_stage",
        "_install_state",
        "_install_steps",
        "_LOG_LINES",
        "_remove_tree",
        "_UNSAFE_CHARS",
        "_unpack",
        "_unsafe_member",
        "install_source",
        "is_checkout",
        "reinstall_source",
        "source_available",
        "source_installed",
        "uninstall_source",
    ),
    "searxng_process": (
        "_PROCESS_QUERY_LIMITED_INFORMATION",
        "_STILL_ACTIVE",
        "_alive",
        "_alive_windows",
        "_read_pid",
        "_source_state",
        "_start_from_source",
        "_start_source",
        "_stop_source",
        "_terminate",
        "log_path",
        "recent_output",
    ),
}


def __getattr__(name: str):
    import importlib

    for module_name, names in _FACADE_NAMES.items():
        if name in names:
            value = getattr(importlib.import_module(f"memorymap.search.{module_name}"), name)
            globals()[name] = value  # cache: only the first lookup pays for the import
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


# This module's own live object, so the functions below can reach the four
# concerns' names through `_self.<name>`, genuine attribute access, which
# `__getattr__` above handles: rather than as bare names. A bare reference
# (`docker_available()` instead of `_self.docker_available()`) compiles to
# LOAD_GLOBAL, which reads this module's `__dict__` directly and never calls
# `__getattr__`; it would also be indistinguishable from a typo to a linter,
# since nothing establishes those names at module scope any more.
_self = sys.modules[__name__]

# Every name the four modules above exposed before the split, so ruff doesn't
# flag this facade's whole reason for existing as "unused imports", and so
# the list doubles as a manifest of what moved out of this file.
#
# **Built from `_FACADE_NAMES` rather than typed out again, and that is a fix
# rather than a tidy-up.** The lazily-resolved half used to be repeated here
# as a second literal list, which CodeQL read as ~50 separate
# `py/undefined-export` alerts ("Explicit export is not defined"): the query
# looks for a module-level binding with that name and PEP 562's `__getattr__`
# is invisible to it, so every facade name was flagged. Deriving the list from
# the same dict the resolver uses removes the duplication *and* the alerts, 
# there is no longer a list of string literals naming things this module does
# not define, and a name added to a concern above can no longer be forgotten
# here.
__all__ = [
    "SearxngError",
    "DEFAULT_PORT",
    "HOST_PORT",
    "FALLBACK_PORTS",
    "BASE_URL",
    "START_TIMEOUT",
    "SOURCE_START_TIMEOUT",
    "COMMAND_TIMEOUT",
    "host_port",
    "base_url",
    "stop_streaming",
    "choose_port",
    "preferred_backend",
    "port_report",
    "status",
    "starting",
    "start",
    "stop",
    # Not called directly in this file any more (docker_installed's
    # `shutil.which` and _remove_tree's `shutil.rmtree` moved to
    # searxng_docker/searxng_install) but the test suite still patches
    # `searxng_manager.shutil.which`/`.rmtree` directly, so the name has to
    # stay bound here. A prior `# noqa: F401  # codeql[py/unused-import]`
    # inline suppression on the import line did not stop CodeQL flagging
    # it: listing it in `__all__` is a real reference (pyflakes/ruff and
    # CodeQL both treat `__all__` membership as usage), not a suppression,
    # so it resolves the alert rather than asking a tool to ignore it.
    "shutil",
]

# `+=` rather than one expression: ruff only recognises a *literal*
# `__all__` list when deciding whether an import is used, and `shutil` above
# is imported solely so the tests can patch it through this module. Written
# as a computed list, the literal disappears and F401 fails the build.
__all__ += [name for names in _FACADE_NAMES.values() for name in names]


def preferred_backend() -> str | None:
    """Which way we'd run it: docker if present, else from source."""
    if _self.docker_available():
        return "docker"
    if _self.source_available():
        return "source"
    return None


def port_report() -> dict:
    """Who, if anyone, is holding the port SearXNG wants.

    "Check the port isn't in use" is advice that assumes the person can check.
    This checks: it binds the port, and if it can't, asks whatever is there
    whether it speaks SearXNG. Those are three genuinely different situations
    - free, occupied by a working SearXNG, occupied by something else, and
    only the last one is a problem the user has to go and solve.
    """
    free = True
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR: the question is whether a *live* listener holds the
        # port, and reuse would let this bind alongside one on some platforms.
        probe.bind(("127.0.0.1", host_port()))
        probe.close()
    except OSError:
        free = False

    if free:
        return {
            "port": host_port(),
            "free": True,
            "held_by_searxng": False,
            "detail": f"Port {host_port()} is free.",
        }

    answering = websearch.probe_searxng(base_url())
    return {
        "port": host_port(),
        "free": False,
        "held_by_searxng": answering,
        "detail": (
            f"A working SearXNG is already answering on port {host_port()}, "
            "MemoryMap can use it as it is."
            if answering
            else f"Something is using port {host_port()}, and it isn't answering "
            "as SearXNG. Starting will move to the next free port on its own "
            f"(it tries {', '.join(str(p) for p in FALLBACK_PORTS)}); set "
            "MEMORYMAP_SEARXNG_PORT to pick one yourself."
        ),
    }


def status(data_dir: Path | None = None) -> dict:
    """Everything the settings screen needs to describe the instance."""
    backend = preferred_backend()
    install_state = _self._install_state
    base = {
        "docker": _self.docker_available(),
        "docker_installed": _self.docker_installed(),
        "source": _self.source_available(),
        "backend": backend,
        "url": base_url(),
        "installing": install_state["running"],
        "install_step": install_state["step"],
        "install_error": install_state["error"],
        # An install runs for minutes; a step name that doesn't change for
        # four of them is indistinguishable from a hang. The stage numbers
        # give a bar something to move along, and the log is what the tools
        # are printing right now.
        "install_stage": install_state["stage"],
        "install_stages": install_state["stages"],
        "install_progress": install_state["progress"],
        "install_log": list(install_state["log"]),
        "detail": "",
        # Answered rather than suggested: "check the port isn't in use" is
        # advice that assumes the person can check.
        "port": port_report(),
    }
    if backend is None:
        # "Docker is installed but not started" is a different problem from
        # "Docker isn't installed", and only one of them is fixed by starting
        # Docker Desktop. Saying which saves a pointless install.
        # Defensive: source installs no longer need anything beyond Python, so
        # this is only reached if `source_available` has been overridden.
        detail = (
            "Docker is installed but its daemon isn't running: start Docker "
            "Desktop, or MemoryMap will set SearXNG up in a virtualenv instead."
            if _self.docker_installed()
            else "SearXNG can't be set up automatically here. Point MemoryMap "
            "at a SearXNG you run yourself."
        )
        return {
            **base,
            "state": "absent",
            "responding": False,
            "docker_installed": _self.docker_installed(),
            "detail": detail,
        }
    if backend == "docker":
        state = _self._docker_state()
    else:
        state = _self._source_state(Path(data_dir)) if data_dir else "absent"
        if state == "absent" and not base["installing"]:
            base["detail"] = (
                "Docker is installed but not running, so SearXNG will be set "
                "up in a virtualenv of its own instead. The first start takes "
                "a few minutes: or start Docker Desktop and try again."
                if _self.docker_installed()
                else "Docker isn't installed, so SearXNG will be set up in a "
                "virtualenv of its own. The first start takes a few minutes."
            )
    return {
        **base,
        "state": state,
        "responding": websearch.probe_searxng(base_url()) if state == "running" else False,
    }


# A start runs in the request thread and waits up to START_TIMEOUT for the
# service to answer: a minute and a half of nothing, and the one wait a user
# is most likely to open Background tasks to ask about. The install was listed
# there and this was not, which is what "the bg tasks still isn't working"
# turned out to be: the longest visible wait in the app had nothing to show.
_start_state: dict = {"running": False, "backend": "", "since": 0.0}


def starting() -> dict | None:
    """The start in flight, if there is one."""
    return dict(_start_state) if _start_state["running"] else None


def start(data_dir: Path, on_ready=None) -> dict:
    """Start SearXNG whichever way this machine can, and wait for JSON.

    `on_ready` only matters when nothing is installed yet: the install this
    kicks off runs for minutes in the background, and with a callback it
    finishes by starting SearXNG and reporting the URL, instead of asking
    the user to come back and press Start a second time.
    """
    backend = preferred_backend()
    if backend is None:
        raise SearxngError(
            "SearXNG can't be set up automatically here. Point MemoryMap at a "
            "SearXNG you run yourself."
        )
    # Settle the port before anything binds it, so the settings file, the
    # child process and every later probe all agree on one number.
    choose_port()
    _start_state.update({"running": True, "backend": backend, "since": time.time()})
    try:
        if backend == "source":
            return _self._start_from_source(data_dir, on_ready=on_ready)
        return _self._start_docker(data_dir)
    finally:
        _start_state["running"] = False


def stop(data_dir: Path | None = None) -> dict:
    """Stop the instance but keep it (and its settings) for next time."""
    backend = preferred_backend()
    if backend is None:
        raise SearxngError("There is no SearXNG here that MemoryMap started.")
    if backend == "source":
        if data_dir is None:
            raise SearxngError("Couldn't find the SearXNG install.")
        return _self._stop_source(Path(data_dir))
    if _self._docker_state() == "absent":
        return {"stopped": False}
    result = _run(["docker", "stop", _self.CONTAINER_NAME], timeout=40)
    if result.returncode != 0:
        raise SearxngError(_reason(result, "Couldn't stop the container"))
    return {"stopped": True}
