"""Optional extras, installed from inside the app.

Asked for directly: *"I want a way to install optional extra dependencies like
faster whisper and other things like maybe markitdown, llama.cpp or smth in the
settings."*

Every one of these is a feature the app already has a button for and cannot
run: the dictation buttons need `faster-whisper`, `python -m memorymap
--desktop` needs `pywebview`, semantic search falls back to keywords without
`sentence-transformers`. Until now the only way to turn one on was a terminal
and a README, which for a local-first app aimed at somebody who is not a
developer is the same as not having the feature.

Three properties this deliberately has:

- **An allowlist, never a free-text package name.** The name arrives from an
  HTTP request. `pip install <whatever the body said>` is arbitrary code
  execution by design, and no amount of validating the string afterwards makes
  that safe: so the request selects an *entry from this file* and the package
  spec is never anything the client sent.
- **It reports the truth about a restart.** A package installed into a running
  interpreter is not importable by it in any way worth relying on, so every
  entry says so rather than pretending the feature is now on.
- **It runs as a background job like everything else**, which means the status
  bar and Settings → Background tasks show it without either of them learning
  anything new: see `routes_tasks.py`.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import shutil
import subprocess  # noqa: S404  # fixed args, no shell; see _install below
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from memorymap.core import ocr

#: Reported: a failed install showed "pip exited with code 1. The log above
#: says why." in the Background tasks "Recently finished" history card, with
#: no log anywhere near it. Two separate bugs turned out to be behind that one
#: screenshot:
#:
#: 1. "The log above" was true of exactly one screen, Settings → Extras,
#:    which keeps `_state.log` on screen (`extras-log-wrap`) after the install
#:    stops. The history card renders `taskhistory.record`'s `detail` string
#:    alone, with no log ever attached to it, so the same sentence pointed at
#:    nothing there. Fixed below by folding the actual pip line into the
#:    message itself (`_pip_reason`), so it is self-contained wherever it is
#:    read: the same fix `search/searxng_manager._reason` already used for
#:    its own installer, mirrored here rather than reinvented.
#: 2. A first attempt at this routed pip's output through `logging` (see
#:    `core/logbuffer.py`, which backs Settings → Logs), but only in
#:    `_run_uninstall`'s `finally` block. `_run_install`, the path the report
#:    was actually about, never called `_logger` at all, so a failed install
#:    still never reached Settings → Logs no matter what the panel said.
#:    Never caught because nobody had reproduced a real failure end-to-end
#:    since the change: reproducing one (`tests/test_extras.py`) is what
#:    found it. Both worker functions call `_logger` now.
_logger = logging.getLogger("memorymap.extras")

# Lines that are never the reason something failed, however last they are.
#
# Pip's parting "[notice] To update, run: ...python.exe -m pip install
# --upgrade pip" is printed on almost every run and is always the last line, 
# taking the last line unconditionally would report that instead of the
# actual failure. Same list, same reasoning, as
# `search/searxng_manager._NOT_A_REASON`.
_NOT_A_REASON = (
    "[notice]",
    "to update, run",
    "you should consider upgrading",
    "warning: you are using pip version",
)


def _pip_reason(log: list[str], prefix: str) -> str:
    """`prefix`, plus the most useful line pip actually printed.

    Prefers a line that names an error, falls back to the last line that
    isn't boilerplate, and falls back to `prefix` alone rather than guessing.
    Mirrors `search/searxng_manager._reason`, which solved the same "the last
    line is pip's update nag, not the failure" problem for the SearXNG
    installer; extracted here rather than imported because the source is a
    line list already split into `_state.log`, not a `CompletedProcess`.
    """
    useful = [
        line for line in log if not any(marker in line.lower() for marker in _NOT_A_REASON)
    ]
    if not useful:
        return prefix
    named = [
        line
        for line in useful
        if line.lower().startswith(("error", "fatal", "exception")) or "error:" in line.lower()
    ]
    return f"{prefix}: {(named or useful)[-1]}"


def find_system_python() -> str | None:
    """A real Python interpreter to hand to `subprocess`, or `None` if
    there isn't one.

    `sys.executable` is right for this in a normal venv/source install, but
    wrong in a *frozen* build (`sys.frozen`, set by PyInstaller):
    `sys.executable` there is the packaged app's own .exe, not a Python
    interpreter, so `[sys.executable, "-m", X, ...]` actually re-launches
    the app with `-m X ...` as if they were *its* own command-line flags.
    `__main__.py`'s argparse (which only knows `--desktop`/`--reset-
    password`) rejects them: confirmed from a real Windows installer
    user's support bundle: `pip install` came back as "unrecognized
    arguments: -m pip install ...", the real answer to two earlier
    "pip exited with code 1/2, no visible output" mysteries, because there
    was never any real pip output, pip was never actually run. The same
    shape reaches `venv` creation too (`search/searxng_install.py`), not
    just pip, which is why this is a general helper rather than living
    inside `_pip_base_command` alone.

    Two callers document why failing outright in frozen mode isn't
    acceptable here: INSTALL.md promises Settings → Packages works with "no
    terminal or Python install required" from the Windows installer, and
    Managed SearXNG's from-source install is offered from that same
    packaged build. So this looks for a real Python already on PATH first
    (common: many people installing an AI-adjacent app like this already
    have one from something else) rather than refusing unconditionally.
    `None` means genuinely none was found, every caller turns that into an
    honest, actionable message instead of the argparse crash.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("python3")


def _pip_base_command() -> list[str] | None:
    """`[python, "-m", "pip"]`, or `None` if `find_system_python` found no
    real interpreter to run it with."""
    python = find_system_python()
    return [python, "-m", "pip"] if python else None


#: Shown when `_pip_base_command()` returns `None`, frozen, and no system
#: Python found. Names the actual fix (not just "something went wrong"),
#: since "install Python" is not the answer most error messages in this
#: no-terminal-required app would ever need to give.
NO_PYTHON_FOUND_MESSAGE = (
    "No Python interpreter found on this system, and the packaged app can't "
    "install a package without one. Install Python from python.org (any "
    "recent version, tick \"Add python.exe to PATH\" during setup), then "
    "try again."
)


@dataclass(frozen=True)
class Extra:
    """One optional dependency, and the honest description of what it buys."""

    #: Stable id used by the API. Never a package name from the client.
    id: str
    label: str
    #: What turns on when it is installed, in the user's terms.
    enables: str
    #: Exactly what goes to pip. A tuple because some extras are several
    #: packages that are useless apart.
    packages: tuple[str, ...]
    #: The module to import to find out whether it is already there. Import
    #: rather than `pip show`: what matters is whether *this* interpreter can
    #: use it, which is a different question from whether pip put it somewhere.
    module: str
    #: Rough download size, so nobody starts a 2 GB install by accident.
    size: str
    #: Said on the card, before the button is pressed.
    caveat: str = ""
    #: Why this cannot be installed *yet*, or "" when it can be.
    #:
    #: Two of these extras install a library the app does not call anywhere:
    #: markitdown has no import button behind it and llama-cpp-python is not
    #: wired into the chat backend. Both said so in their caveat and both still
    #: offered a working Install, which spends the user's disk and their time
    #: on a feature that does not exist, and then asks them to restart for it.
    #: A caveat under an enabled button is a warning people click past; a
    #: disabled button with the reason beside it is the same sentence made
    #: true.
    #:
    #: It is enforced in `start()` as well as drawn in the interface. The
    #: greyed-out button is a courtesy, the refusal is the rule, this file is
    #: the allowlist, so "installable" belongs here and not in `app.js`.
    #: Removal is deliberately *not* blocked: an extra installed before it was
    #: marked unavailable, or installed by hand, still needs its way out.
    unavailable: str = ""


#: The allowlist. Adding an entry here is the only way to make something
#: installable, which is the point.
EXTRAS: tuple[Extra, ...] = (
    Extra(
        id="pdfpages",
        label="Read scanned PDFs (pypdfium2)",
        enables="Turns the pages of a scanned PDF into images so your vision "
        "model can read them. Without it a PDF with no text layer can only be "
        "reported as a scan, not opened.",
        packages=("pypdfium2", "Pillow"),
        module="pypdfium2",
        size="~16 MB",
        caveat="Reading the pages still needs a vision or OCR model, see "
        "Settings → Models. This only supplies the images.",
    ),
    Extra(
        id="voice",
        label="Voice notes (faster-whisper)",
        enables="The dictation buttons: speak a note or a question and have it typed "
        "out, transcribed on this machine.",
        packages=("faster-whisper",),
        module="faster_whisper",
        size="~50 MB, plus a model on first use",
    ),
    Extra(
        id="desktop",
        label="Desktop window (pywebview)",
        enables="Runs MemoryMap in its own app window instead of a browser tab "
        ", `python -m memorymap --desktop`. On Windows this also adds a system "
        "tray icon (Open / View Logs / Restart / Quit) so closing the window "
        "minimizes it instead of ending the app; elsewhere the window still "
        "opens, it just closes for real.",
        # pystray + Pillow are the tray icon; bundled with the same button
        # because a desktop window with no tray is the "always-open terminal"
        # complaint this was built to fix (see __main__._start_tray). Neither
        # blocks the window if missing, `_start_tray` just returns None and
        # the window closes for real, same as before the tray existed.
        packages=("pywebview", "pystray", "Pillow"),
        module="webview",
        size="~5 MB",
    ),
    Extra(
        id="semantic",
        label="Search by meaning (sentence-transformers)",
        enables="Searching for what you meant rather than the words you used. "
        "Without it, search falls back to keywords and everything else works.",
        packages=("sentence-transformers",),
        module="sentence_transformers",
        size="~2 GB: it pulls in PyTorch",
        caveat="The big one. On Windows this needs the CPU build of torch; see "
        "the README's troubleshooting section if the install fails with "
        "a DLL error.",
    ),
    Extra(
        id="documents",
        label="Import documents (markitdown)",
        enables="Turns PDFs, Word files and slides into notes, the "
        "'Import a document' button in Settings → Import & export.",
        packages=("markitdown",),
        module="markitdown",
        size="~20 MB",
    ),
    Extra(
        id="ocr",
        label="Search inside images (Tesseract OCR)",
        enables="Text found in an uploaded image (a whiteboard photo, a "
        "scanned page) becomes searchable in the Library's Image Gallery: "
        "asked for directly: 'what was on that whiteboard photo from March.'",
        packages=("pytesseract", "Pillow"),
        module="pytesseract",
        size="~10 MB",
        caveat="Also needs the separate 'tesseract' program on this computer, "
        "pip can't install that part, since it isn't a Python package. This "
        "button tries to install it automatically too (winget/brew/apt/dnf/"
        "pacman, whichever this system has); if that doesn't work, install it "
        "by hand (see INSTALL.md). Without it, uploads still work, they just "
        "get no searchable text.",
    ),
    Extra(
        id="localllm",
        label="Built-in model runner (llama-cpp-python)",
        enables="Runs a GGUF model in this process, for machines where "
        "installing Ollama is not an option.",
        packages=("llama-cpp-python",),
        module="llama_cpp",
        size="~30 MB, and it compiles on some platforms",
        # Was "Not wired into the chat backend yet", false, and misleading
        # in the specific way that costs the most: it reads as "llama.cpp
        # is unsupported," when the supported route (`llama-server`, which
        # speaks the same API `ai/openai_client.py` already does) needs no
        # extra here at all. What actually isn't built is *this* extra
        # specifically: running a GGUF in-process, inside this app, rather
        # than as a separate server you point the app at. See the Models
        # screen's provider picker for the llama-server recipe.
        unavailable="llama.cpp itself is already supported, run "
        "llama-server and point Settings → Models at it as an "
        "OpenAI-compatible backend, no install here needed. This extra is "
        "specifically for running a GGUF in-process instead of as a "
        "separate server, which isn't built: it means shipping a compiled "
        "wheel per platform and accelerator (CUDA/ROCm/Metal/CPU) and "
        "owning model load/unload, for a capability llama-server already "
        "gives you today.",
    ),
)

EXTRAS_BY_ID = {extra.id: extra for extra in EXTRAS}


@dataclass
class InstallState:
    """What one install is doing, for `/tasks` and the panel."""

    running: bool = False
    extra_id: str = ""
    step: str = ""
    log: list[str] = field(default_factory=list)
    started: float = 0.0
    outcome: str = ""  # "" while running, then completed | failed
    #: The live pip process, so `cancel()` below can actually stop it. Asked
    #: for directly: "allow the quitting/killing of background tasks as well".
    #: pip has no cooperative stop, it is a subprocess spending minutes
    #: building a wheel: so the only honest way to quit one is to terminate
    #: it, which is what a user pressing Quit is asking for. Kept off the wire:
    #: `status()` and `/tasks` build their own dicts and never touch this.
    process: object | None = None
    #: True once someone asked for it to stop, so the failure that follows is
    #: reported as a cancellation rather than as pip having gone wrong.
    cancelled: bool = False


#: One at a time, process-wide. Two pips against one environment is a way to
#: corrupt it, and there is no reason to want it.
_state = InstallState()
_lock = threading.Lock()

#: Bounded, like the SearXNG installer's log: this is a progress indicator, not
#: a build record, and pip on a large wheel prints a great deal.
MAX_LOG_LINES = 200


def is_installed(extra: Extra) -> bool:
    """Can this interpreter import it *right now*?

    `find_spec` rather than a real import: importing torch to answer a status
    question would cost seconds and a great deal of memory on a screen the user
    is only looking at.
    """
    try:
        return importlib.util.find_spec(extra.module) is not None
    except (ImportError, ValueError):
        # A half-installed package can raise here rather than returning None.
        # "Not usable" is the honest answer either way.
        return False


def status() -> list[dict]:
    """Every extra, with whether it is installed and whether it is installing."""
    return [
        {
            "id": extra.id,
            "label": extra.label,
            "enables": extra.enables,
            "size": extra.size,
            "caveat": extra.caveat,
            "unavailable": extra.unavailable,
            "packages": list(extra.packages),
            "installed": is_installed(extra),
            "installing": _state.running and _state.extra_id == extra.id,
            "step": _state.step if _state.running and _state.extra_id == extra.id else "",
        }
        for extra in EXTRAS
    ]


def current() -> InstallState:
    return _state


def cancel() -> tuple[bool, str]:
    """Stop the running pip, if there is one. Returns (stopped, message).

    **Terminate, not a flag.** Everything else in this app that can be quit
    checks a cooperative `cancel_requested` between steps, because everything
    else is a loop this app wrote. pip is not: it is a child process that may
    be five minutes into compiling a wheel and will not look at anything we
    set. `terminate()` is the only stop that stops it, and it is what someone
    who pressed Quit meant.

    Safe to leave half-installed: pip installs into a staging directory and
    moves the result into place, so a terminated install leaves the
    environment as it was rather than half-written. The extras panel re-reads
    `is_installed` on its next poll and will simply still say "not installed".
    """
    process = _state.process
    if not _state.running or process is None:
        return False, "Nothing is installing."
    _state.cancelled = True
    _state.step = "Stopping…"
    try:
        process.terminate()
    except Exception as exc:  # noqa: BLE001  # an already-dead child is a win
        _logger.debug("couldn't terminate pip: %s", exc)
    return True, "Stopping the install."


def _run_uninstall(extra: Extra) -> None:
    """pip uninstall, with the same bookkeeping the install has.

    Only the packages this entry named, never their dependencies: removing
    `sentence-transformers` leaves torch behind, which is right, it is 2 GB
    that something else may be using, and a button labelled "uninstall one
    thing" must not quietly take five.
    """
    try:
        pip_base = _pip_base_command()
        if pip_base is None:
            _state.outcome = "failed"
            _state.step = NO_PYTHON_FOUND_MESSAGE
            return
        command = [
            *pip_base,
            "uninstall",
            "-y",
            "--disable-pip-version-check",
            *extra.packages,
        ]
        _state.step = f"pip uninstall {' '.join(extra.packages)}"
        process = subprocess.Popen(  # noqa: S603  # fixed args from the allowlist, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _state.process = process
        for line in process.stdout or []:
            line = line.rstrip()
            if not line:
                continue
            _state.log.append(line)
            del _state.log[:-MAX_LOG_LINES]
            _state.step = line[:120]
        code = process.wait()
        _state.outcome = "completed" if code == 0 else "failed"
        _state.step = (
            f"{extra.label} removed: restart MemoryMap to free it."
            if code == 0
            else _pip_reason(_state.log, f"pip exited with code {code}")
        )
    except (OSError, subprocess.SubprocessError):
        # The exception text can carry a filesystem path or other local detail,
        # and `_state.step` goes straight to the browser via `/extras` and
        # `/tasks`. Flagged by CodeQL as `py/stack-trace-exposure`, same shape
        # as `embedmodels.remove`. Full detail goes to the log, which only the
        # owner of the machine reads; the caller gets the fact, not the internals.
        _logger.exception("Couldn't run pip to remove %s", extra.label)
        _state.outcome = "failed"
        _state.step = "Couldn't run pip: see Settings → Logs for why."
    finally:
        _state.running = False
        _state.process = None
        if _state.cancelled:
            # Terminating pip mid-download makes it exit non-zero, which the
            # branches above have already written up as a failure. It wasn't
            # one, someone pressed Quit, and a task history full of
            # "Installing X failed" for things nobody wanted is how a history
            # stops being read.
            _state.outcome = "cancelled"
            _state.step = "Stopped before it finished."
        if _state.outcome == "failed":
            _logger.error(
                "Removing %s failed: %s\n%s",
                extra.label,
                _state.step,
                "\n".join(_state.log[-40:]),
            )
        else:
            _logger.info("Removed %s.", extra.label)


#: Matches an extras marker in a requirement line, e.g. the `[standard]` in
#: `uvicorn[standard]>=0.52.1,<1.0`. pip's `-c` constraints flag rejects
#: extras outright, "ERROR: Constraints cannot have extras", and that
#: failure is for the *whole constraints file*, not just the offending line,
#: which is why every extras install failed the same way `requirements.txt`
#: itself has two: `uvicorn[standard]`, `fsspec[http]`.
_REQUIREMENT_EXTRAS_RE = re.compile(r"\[[^\]]*\]")


def _constraints_copy(req_path: Path) -> Path | None:
    """A version of `req_path` pip will actually accept as a `-c` file.

    A constraint only needs the version bound, not the extra, so this strips
    `[...]` rather than dropping the affected lines, `uvicorn` and `fsspec`
    still get pinned, just without the part `-c` can't parse. Written to a
    temp file; the caller deletes it once pip has run.
    """
    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return None
    fd, tmp_path = tempfile.mkstemp(prefix="memorymap-pip-constraints-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_REQUIREMENT_EXTRAS_RE.sub("", text))
    return Path(tmp_path)


def _run_install(extra: Extra, reinstall: bool = False) -> None:
    """pip, in a worker thread, with its output kept for the panel."""
    constraints_copy: Path | None = None
    try:
        # `sys.executable -m pip` and never a bare `pip`, see
        # `_pip_base_command`'s own docstring for why that's not quite right
        # either once the app is a frozen build, and what this does instead.
        pip_base = _pip_base_command()
        if pip_base is None:
            _state.outcome = "failed"
            _state.step = NO_PYTHON_FOUND_MESSAGE
            return
        # Constrain every extra install against requirements.txt so an optional
        # package's own dependency resolution can't drag a base package (e.g.
        # tokenizers, numpy) to a version the rest of the app doesn't expect.
        req_path = Path(__file__).resolve().parents[3] / "requirements.txt"
        constraints_copy = _constraints_copy(req_path) if req_path.is_file() else None
        constraint = ["-c", str(constraints_copy)] if constraints_copy else []

        command = [
            *pip_base,
            "install",
            "--disable-pip-version-check",
            # A reinstall is for the case the button exists to serve: it is
            # importable but broken: a half-finished download, a wheel built
            # for the wrong platform, the Windows torch DLL the README warns
            # about. `--upgrade` would look at the version, decide it already
            # has it and do nothing at all, which is the one outcome that
            # helps nobody. `--no-cache-dir` for the same reason: a corrupt
            # cached wheel would otherwise be reinstalled faithfully.
            *(["--force-reinstall", "--no-cache-dir"] if reinstall else []),
            *extra.packages,
            *constraint,
        ]
        _state.step = f"pip install {' '.join(extra.packages)}"
        process = subprocess.Popen(  # noqa: S603  # fixed args from the allowlist, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _state.process = process
        for line in process.stdout or []:
            line = line.rstrip()
            if not line:
                continue
            _state.log.append(line)
            del _state.log[:-MAX_LOG_LINES]
            _state.step = line[:120]
        code = process.wait()
        _state.outcome = "completed" if code == 0 else "failed"
        if code != 0:
            _state.step = _pip_reason(_state.log, f"pip exited with code {code}")
        elif extra.id == "ocr":
            # The one extra with a system-binary half pip can't touch: 
            # asked for directly ("automate it if possible"). Best-effort:
            # a failed *binary* install never flips this extra's own
            # outcome to "failed", the pip packages are genuinely
            # installed and useful (ocr.py degrades cleanly without the
            # binary), so the honest outcome is still "completed", just
            # with the binary attempt's own result folded into the message.
            _state.step = "Installing the Tesseract program…"
            _, binary_message = ocr.attempt_binary_install()
            _state.log.append(binary_message)
            _state.step = f"{extra.label} installed: restart MemoryMap to use it. {binary_message}"
        else:
            _state.step = f"{extra.label} installed: restart MemoryMap to use it."
    except (OSError, subprocess.SubprocessError):
        # See `_run_uninstall`'s except block: same CodeQL
        # `py/stack-trace-exposure` shape, same fix: full detail to the log,
        # a generic fact to `_state.step`, which is what `/extras` returns.
        _logger.exception("Couldn't run pip to install %s", extra.label)
        _state.outcome = "failed"
        _state.step = "Couldn't run pip: see Settings → Logs for why."
    finally:
        _state.running = False
        _state.process = None
        if _state.cancelled:
            # Terminating pip mid-download makes it exit non-zero, which the
            # branches above have already written up as a failure. It wasn't
            # one, someone pressed Quit, and a task history full of
            # "Installing X failed" for things nobody wanted is how a history
            # stops being read.
            _state.outcome = "cancelled"
            _state.step = "Stopped before it finished."
        # See the module docstring's numbered note above `_logger`: this call
        # was missing entirely until now, which is the actual reason a failed
        # *install* never reached Settings → Logs, `_run_uninstall` had it,
        # this function did not.
        if _state.outcome == "failed":
            _logger.error(
                "Installing %s failed: %s\n%s",
                extra.label,
                _state.step,
                "\n".join(_state.log[-40:]),
            )
        else:
            _logger.info("Installed %s.", extra.label)
        from memorymap.core import taskhistory
        taskhistory.record(
            "extra",
            f"Installing {extra.label}",
            _state.outcome,
            _state.step,
            duration_ms=(time.time() - _state.started) * 1000 if _state.started else None,
        )
        if constraints_copy is not None:
            constraints_copy.unlink(missing_ok=True)


def start(extra_id: str, reinstall: bool = False) -> tuple[bool, str]:
    """Begin an install. Returns (started, message).

    Never raises on a bad id, the id comes from a request, and an unknown one
    is a thing to report rather than a stack trace.

    `reinstall` is the escape hatch for the state this cannot detect: the module
    imports, so the app reports it installed, and it does not actually work.
    Detection is `find_spec`, which answers "is it there", not "is it sound".
    """
    extra = EXTRAS_BY_ID.get(extra_id)
    if extra is None:
        return False, "No such extra."
    # Checked before the lock and before `reinstall` is considered: an extra
    # nothing calls is not made installable by asking twice.
    if extra.unavailable:
        return False, f"{extra.label} isn't ready to install yet. {extra.unavailable}"
    if reinstall:
        blocked = _loaded_in_process_reason(extra)
        if blocked:
            return False, blocked
    with _lock:
        if _state.running:
            return False, "Another install is already running."
        if is_installed(extra) and not reinstall:
            return False, f"{extra.label} is already installed."
        _state.running = True
        _state.extra_id = extra.id
        _state.outcome = ""
        _state.step = "starting pip…"
        _state.log = []
        _state.started = time.time()
        _state.cancelled = False
    threading.Thread(target=_run_install, args=(extra, reinstall), daemon=True).start()
    return True, f"{'Reinstalling' if reinstall else 'Installing'} {extra.label}."


def remove(extra_id: str) -> tuple[bool, str]:
    """Uninstall one extra. Same allowlist, same one-at-a-time rule.

    Deliberately does *not* refuse when the module is missing: an extra can be
    half-installed, pip's metadata present and the module unimportable, and
    the button that would fix that is this one.
    """
    extra = EXTRAS_BY_ID.get(extra_id)
    if extra is None:
        return False, "No such extra."
    blocked = _loaded_in_process_reason(extra)
    if blocked:
        return False, blocked
    with _lock:
        if _state.running:
            return False, "Another install is already running."
        _state.running = True
        _state.extra_id = extra.id
        _state.outcome = ""
        _state.step = "starting pip…"
        _state.log = []
        _state.started = time.time()
        _state.cancelled = False
    threading.Thread(target=_run_uninstall, args=(extra,), daemon=True).start()
    return True, f"Removing {extra.label}."


def _loaded_in_process_reason(extra: Extra) -> str:
    """Reported: faster-whisper install/reinstall/remove all silently failed
    on Windows after the dictation buttons had already been used once.

    A used model stays loaded in this process's memory for as long as it
    runs (`voice._loaded`), the whole point, since reloading one per request
    would be far too slow. Windows locks a native `.pyd`/DLL exclusively
    while any process has it mapped in, so pip can spawn, run, and still fail
    to actually replace those files; the failure then surfaces as a cryptic
    pip error in the install log rather than as this sentence. POSIX allows
    replacing a file that is still open elsewhere, which is why this was
    never seen from this sandbox.

    Only "voice" holds a native model like this today, the other extras
    either aren't native libraries or aren't cached across requests.
    """
    if extra.id != "voice":
        return ""
    from memorymap.ai import voice

    if voice._loaded is not None:  # noqa: SLF001  # this module's whole job is knowing this
        return (
            "Restart MemoryMap first. The voice model is loaded in memory from "
            "an earlier recording, and Windows can't replace those files while "
            "they're in use: a restart releases them."
        )
    return ""


def reset_for_tests() -> None:
    """Process-global state, like the job registry, tests have to clear it or
    one test's install leaks into the next one's assertions."""
    global _state
    _state = InstallState()
