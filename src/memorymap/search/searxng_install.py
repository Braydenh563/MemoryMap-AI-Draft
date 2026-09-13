"""Fetch SearXNG into a virtualenv of its own, the non-Docker install path.

Split out of `searxng_manager.py` (see that module for the two backends this
feeds). SearXNG is a Python app, so on a machine without Docker it runs from
a source checkout in a virtualenv under the data directory instead. This
module owns that checkout: downloading and unpacking the archive (not `git
clone`, see SOURCE_TARBALL below for why that cannot work on Windows),
running the pip install SearXNG's own `manage` script uses, tracking install
progress for the settings screen to poll, and wiping a broken install so the
next one starts clean.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

from memorymap.core.extras import find_system_python
from memorymap.search import searxng_manager
from memorymap.search.searxng_manager import (
    COMMAND_TIMEOUT,
    SearxngError,
    _pid_file,
    _reason,
    _source_dir,
    _venv_dir,
)
from memorymap.search.searxng_settings import _searxng_env, _write_pwd_shim

# `_run`, `_run_streaming` and `_venv_python` are deliberately not imported by
# name above, and `_download`/`_fetch_source`/`_remove_tree`/`install_source`
# below call *each other* through `searxng_manager.<name>` too, even though
# they live in this same file: the test suite monkeypatches all of them as
# `searxng_manager.<name>`, which rebinds that attribute on the
# `searxng_manager` module object only: a name bound here at import time, or
# a same-file call resolved through this module's own globals, would never
# see the patch. Going through `searxng_manager.<name>` looks the attribute up
# fresh on every call, matching what happened when this was one file.

# The source, as an archive we download and unpack ourselves.
#
# Not a `git clone`, and not `pip install <tarball-url>` either, because
# **SearXNG's repository cannot be written to a Windows filesystem**. Four of
# its files carry a colon in the name:
#
#     utils/templates/etc/nginx/default.apps-available/searxng.conf:socket
#     utils/templates/etc/httpd/sites-available/searxng.conf:socket
#     utils/templates/etc/uwsgi/apps-available/searxng.ini:socket
#     utils/templates/etc/uwsgi/apps-archlinux/searxng.ini:socket
#
# A colon separates a drive letter (and names an alternate data stream), so
# Windows refuses those names outright. git fetches every object happily and
# then dies at the last step, *"error: invalid path …searxng.conf:socket /
# fatal: unable to checkout working tree"*, which is what the user reported, 
# leaving a half-written checkout behind, which is where the earlier "does
# not appear to be a Python project" came from. Retrying could never work:
# nothing about it is transient. Unpacking the tarball with pip fails the same
# way for the same reason, so "install without git" was equally broken there.
#
# We therefore unpack it ourselves and skip the handful of members Windows
# can't represent. They are nginx and uwsgi deployment templates for
# installing SearXNG on a server, nothing the app runs.
SOURCE_TARBALL = "https://github.com/searxng/searxng/archive/refs/heads/master.tar.gz"
DOWNLOAD_TIMEOUT = 300
INSTALL_TIMEOUT = 900  # a cold pip install builds a few wheels


def source_available() -> bool:
    """True if we could build a virtualenv and fetch SearXNG into it.

    Always true. It used to require the `git` binary, which meant a machine
    with neither Docker nor git could not install SearXNG at all, "I can't
    download searxng", with the UI offering a button that could never work.
    The only real requirements are Python (we are running on it) and a network
    connection, which any install needs anyway. git is not used at all now;
    see SOURCE_TARBALL for why cloning cannot work on Windows.

    Deliberately not a `pip install searxng` from PyPI: SearXNG does not
    publish itself there, so that name is somebody else's package, and
    installing it would be running an unknown author's code because the name
    looked right.
    """
    return True


# --- running from source ------------------------------------------------------

# Progress for the one install that can be running at a time. The install is
# minutes long, so it happens on a worker thread and the settings screen polls
# status() rather than holding a request open.
_install_lock = threading.Lock()

# Reported: "the searxng reinstall doesn't have a progress bar so idk if it
# has frozen or is working". A step name that sits unchanged for four minutes
# while pip builds lxml is indistinguishable from a hang, and the install is
# the longest thing this app does.
#
# So the state carries three things a step name cannot: which numbered stage
# of the install we are in (a bar that moves), a fraction inside the stage
# where one is knowable (the download has a content-length; the unpack has a
# member count), and the last few lines the tools themselves printed, which
# is the only real evidence that something is still happening.
INSTALL_STAGES = 5
_LOG_LINES = 12
_install_state: dict = {
    "running": False,
    "step": "",
    "error": "",
    "stage": 0,
    "stages": INSTALL_STAGES,
    "progress": None,  # 0..1 within the whole install, or None if unknowable
    "log": [],
}


def _install_log(line: str) -> None:
    """Keep the last few lines of what the install is actually doing."""
    text = str(line).strip()
    if not text:
        return
    lines = _install_state["log"]
    lines.append(text)
    del lines[:-_LOG_LINES]


def _install_stage(stage: int, step: str) -> None:
    """Move to a numbered stage. Progress is the stage boundary until
    something inside the stage knows better."""
    _install_state.update(
        {"stage": stage, "step": step, "progress": (stage - 1) / INSTALL_STAGES}
    )
    _install_log(f", {step}")


def _install_progress(stage: int, fraction: float) -> None:
    """Progress *within* a stage, mapped onto the whole install."""
    fraction = max(0.0, min(1.0, fraction))
    _install_state["progress"] = (stage - 1 + fraction) / INSTALL_STAGES


def is_checkout(path: Path) -> bool:
    """Does this directory hold a Python project pip could install?

    A directory being *there* was the test, and it is not the same question.
    Reported: "Couldn't install SearXNG: ERROR: file:///…/data/searxng/src does
    not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml'
    found.", a leftover `src` that no longer contained a checkout, handed
    straight to `pip install -e` because it existed.
    """
    path = Path(path)
    return (path / "setup.py").exists() or (path / "pyproject.toml").exists()


# `import searx` costs a Python interpreter start, and the settings screen
# polls status() every few seconds. Once it has succeeded it stays true until
# something removes the install, so only the affirmative answer is kept.
_import_ok: set[str] = set()


def source_installed(data_dir: Path) -> bool:
    """Is SearXNG present in its own virtualenv?

    The checkout directory only exists on the git path, a tarball install
    puts `searx` straight into the venv's site-packages and never creates
    one. So the question that actually matters is whether the venv can
    import `searx`, not whether a source folder is sitting there.

    And a folder that is there but empty is *worse* than one that is missing:
    it used to answer "installed" for both this question and the one
    `install_source` asks, so the app tried to start something that was never
    built and reinstalling skipped the download.
    """
    python = searxng_manager._venv_python(data_dir)
    if not python.exists():
        return False
    if str(Path(data_dir)) in _import_ok:
        return True
    if is_checkout(_source_dir(data_dir)):
        return True
    result = searxng_manager._run([str(python), "-c", "import searx"], timeout=COMMAND_TIMEOUT)
    if result.returncode == 0:
        _import_ok.add(str(Path(data_dir)))
        return True
    return False


# Characters Windows will not accept in a filename, plus the control range.
# Filtered on every platform, not only Windows: an install should contain the
# same files everywhere, and a path we would refuse on one OS is not one to
# rely on from another.
_UNSAFE_CHARS = set('<>:"|?*') | {chr(c) for c in range(32)}


def _unsafe_member(name: str) -> bool:
    """Is this archive member one we refuse to write?

    Two separate concerns, both fatal in their own way:
    - **path traversal**: an absolute path or a `..` hop writes outside the
      directory we were asked to fill;
    - **names Windows cannot represent**, see SOURCE_TARBALL. Skipping these
      is what makes the install possible there at all.
    """
    if name.startswith("/") or name.startswith("\\") or ":" in name.split("/")[0]:
        return True
    parts = name.split("/")
    if any(part == ".." for part in parts):
        return True
    return any(char in _UNSAFE_CHARS for part in parts for char in part)


def _download(url: str, destination: Path, on_progress=None) -> None:
    """Fetch the archive to disk. Streamed: it is tens of megabytes.

    `on_progress(done_bytes, total_bytes)` is called as it goes. GitHub sends
    a content-length here, so this is the one stage of the install with a
    genuinely knowable percentage.
    """
    import requests  # local: the module is importable without a network stack

    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except requests.RequestException as exc:
        raise SearxngError(f"Couldn't download SearXNG: {exc}") from exc


def _unpack(archive: Path, into: Path) -> list[str]:
    """Unpack the archive into `into`, dropping its single top-level folder.

    Returns the names that were skipped, so the install can say so rather than
    quietly shipping a different set of files than the archive held.
    """
    import tarfile

    skipped: list[str] = []
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = []
            for member in tar.getmembers():
                # A GitHub archive wraps everything in "searxng-master/".
                relative = member.name.split("/", 1)[1] if "/" in member.name else ""
                if not relative:
                    continue
                if not (member.isfile() or member.isdir()) or _unsafe_member(relative):
                    skipped.append(relative)
                    continue
                member.name = relative
                members.append(member)
            # filter="data" refuses absolute paths, links and device nodes in
            # 3.12+; the check above is what covers 3.11 and Windows names.
            if sys.version_info >= (3, 12):
                tar.extractall(into, members=members, filter="data")
            else:  # pragma: no cover - 3.11 only
                tar.extractall(into, members=members)  # noqa: S202  # members vetted above
    except (tarfile.TarError, OSError) as exc:
        raise SearxngError(f"Couldn't unpack SearXNG: {exc}") from exc
    return skipped


def _fetch_source(src: Path, state: dict) -> None:
    """Download and unpack SearXNG into `src`, replacing whatever was there."""
    problem = searxng_manager._remove_tree(src)
    if problem:
        raise SearxngError(f"Couldn't clear the old copy of SearXNG: {problem}")
    archive = src.parent / "searxng-source.tar.gz"
    try:
        _install_stage(2, "Downloading SearXNG…")

        def downloaded(done: int, total: int) -> None:
            if total:
                _install_progress(2, done / total)
            _install_state["step"] = (
                f"Downloading SearXNG… {done // 1_000_000} MB"
                + (f" of {total // 1_000_000} MB" if total else "")
            )

        searxng_manager._download(SOURCE_TARBALL, archive, on_progress=downloaded)
        _install_stage(3, "Unpacking SearXNG…")
        skipped = _unpack(archive, src)
        _install_log(f"Unpacked into {src.name}")
        if skipped:
            _install_log(f"Skipped {len(skipped)} file(s) this filesystem can't hold")
            logging.getLogger("memorymap.searxng").info(
                "Skipped %d file(s) this filesystem can't hold: %s",
                len(skipped),
                ", ".join(skipped[:4]),
            )
    finally:
        archive.unlink(missing_ok=True)
    if not is_checkout(src):
        raise SearxngError(
            "SearXNG downloaded, but no setup.py or pyproject.toml turned up "
            f"in {src}. Try again, or reinstall."
        )


def _install_steps(python: str, src: Path) -> list[tuple[int, str, list[str]]]:
    """The pip commands that install SearXNG, in the order they must run.

    `pip install -e .` on its own **cannot work**, and never could: SearXNG's
    `setup.py` imports `searx` to read its version, `searx/__init__.py`
    imports `msgspec`, and pip builds in an isolated environment where no
    runtime dependency exists yet. It fails with `ModuleNotFoundError: No
    module named 'msgspec'` before it can declare anything, reproduced here,
    not deduced.

    So the requirements go in first and the package is then built against the
    virtualenv rather than an isolated one. This is what SearXNG's own
    `manage` script does (`pip install --use-pep517 --no-build-isolation
    -e .`), and following it is the whole reason it works.
    """
    return [
        (
            4,
            "Installing dependencies (the long one: a few minutes)…",
            [python, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel", "tzdata"],
        ),
        (
            4,
            "Installing dependencies (the long one: a few minutes)…",
            [python, "-m", "pip", "install", "-r", str(src / "requirements.txt")],
        ),
        (
            5,
            "Installing SearXNG itself…",
            [
                python, "-m", "pip", "install",
                "--use-pep517", "--no-build-isolation", "-e", str(src),
            ],
        ),
    ]


def install_source(data_dir: Path, on_ready=None) -> None:
    """Fetch SearXNG into a virtualenv of its own. Minutes, not seconds.

    With `on_ready` given, a successful install is followed by a start, and
    `on_ready(url)` is called once SearXNG answers. That makes install a
    one-press affair: "press Start, wait minutes, press Start again" asked
    the user to babysit the longest wait in the app, and the second press
    was the step people missed.
    """
    with _install_lock:
        if _install_state["running"]:
            raise SearxngError("An install is already running.")
        _install_state.update(
            {
                "running": True,
                "step": "",
                "error": "",
                "log": [],
                "progress": 0.0,
                "auto_start": on_ready is not None,
            }
        )
    _install_stage(1, "Creating a virtualenv…")
    install_started = time.monotonic()

    def work() -> None:
        try:
            src = _source_dir(data_dir)
            src.parent.mkdir(parents=True, exist_ok=True)
            _import_ok.discard(str(Path(data_dir)))
            venv = _venv_dir(data_dir)
            if not searxng_manager._venv_python(data_dir).exists():
                # Not `sys.executable` directly: see `core.extras.
                # find_system_python`'s own docstring: in a frozen (packaged)
                # build, `sys.executable` is the app's own .exe, and
                # `[that, "-m", "venv", ...]` re-launches the app with
                # "-m venv ..." as if they were its own flags, which its
                # argparse rejects. Same bug the pip installer had, same fix.
                python = find_system_python()
                if python is None:
                    raise SearxngError(
                        "No Python interpreter found on this system, and a "
                        "packaged app can't create a virtualenv without one. "
                        "Install Python from python.org (any recent version, "
                        'tick "Add python.exe to PATH" during setup), then '
                        "try again: or use the Docker-based install instead."
                    )
                searxng_manager._run([python, "-m", "venv", str(venv)], timeout=180)
                _install_log(f"Virtualenv created at {venv}")
                if not searxng_manager._venv_python(data_dir).exists():
                    raise SearxngError(
                        "Couldn't create a virtualenv for SearXNG at "
                        f"{venv}: check there is space and that the folder "
                        "is writable."
                    )
            # One path for everyone, git or no git: fetch the archive and
            # unpack it ourselves. Both of the old paths, `git clone` and
            # `pip install <tarball-url>`, write every file in the archive,
            # and four of them cannot exist on Windows.
            searxng_manager._fetch_source(src, _install_state)
            python = str(searxng_manager._venv_python(data_dir))
            for stage, step, args in _install_steps(python, src):
                _install_stage(stage, step)
                # Streamed, not captured: pip prints steadily for minutes here,
                # and those lines are the only evidence the install is alive.
                result = searxng_manager._run_streaming(args, INSTALL_TIMEOUT, _install_log)
                if result.returncode != 0:
                    raise SearxngError(_reason(result, "Couldn't install SearXNG"))
            # pip exiting 0 is not the same as SearXNG being runnable, a
            # half-installed venv otherwise reads as installed and dies at
            # start, which is the state the reinstall button exists to escape.
            _install_state["step"] = "Checking the install…"
            _install_state["progress"] = 0.98
            if _write_pwd_shim(python):
                _install_log("Added a `pwd` compatibility module for this platform.")
            # `import searx` was too shallow: it passed on Windows and the
            # start then died importing `searx.webapp`, which is the module
            # that actually runs. Check the thing that runs.
            check = searxng_manager._run(
                [python, "-c", "import searx.webapp"],
                timeout=INSTALL_TIMEOUT,
                env=_searxng_env(data_dir),
            )
            if check.returncode != 0:
                raise SearxngError(
                    _reason(check, "SearXNG installed but can't be started")
                )
            _import_ok.add(str(Path(data_dir)))
            _install_log("SearXNG installed and importable.")
            _install_state.update({"step": "", "progress": 1.0, "stage": INSTALL_STAGES})
        except SearxngError as exc:
            _install_state["error"] = str(exc)
            _install_log(f"Failed: {exc}")
        except Exception as exc:  # noqa: BLE001  # a worker thread must not die silently
            _install_state["error"] = f"Install failed: {exc}"
            _install_log(f"Failed: {exc}")
        finally:
            _install_state["running"] = False
            from memorymap.core import taskhistory
            outcome = "failed" if _install_state.get("error") else "completed"
            taskhistory.record(
                "searxng",
                "Installing SearXNG",
                outcome,
                _install_state.get("error", "Install finished successfully."),
                duration_ms=(time.monotonic() - install_started) * 1000,
            )
        if on_ready is None or _install_state.get("error"):
            return
        # The follow-on start, still on the worker thread. `running` is
        # False by now, so the start path doesn't mistake its own install
        # for one that is still going.
        try:
            _install_log("Install done: starting SearXNG…")
            # `start` is `searxng_manager`'s own top-level orchestrator, 
            # called via `searxng_manager.start` like everything else this
            # file reaches back into that module for (see the note by this
            # file's imports).
            result = searxng_manager.start(data_dir)
            _install_log("SearXNG is up and answering.")
        except SearxngError as exc:
            _install_state["error"] = (
                f"SearXNG installed, but the automatic start failed: {exc}"
            )
            _install_log(f"Automatic start failed: {exc}")
            return
        try:
            on_ready(result["url"])
        except Exception:  # noqa: BLE001  # the instance is up; a callback must not undo that
            logging.getLogger("memorymap.searxng").warning(
                "SearXNG started at %s but the on_ready callback failed.",
                result["url"],
                exc_info=True,
            )

    threading.Thread(target=work, name="searxng-install", daemon=True).start()


def _drop_readonly(func, path, _exc) -> None:
    """rmtree's retry hook: clear the read-only bit and go again.

    git marks everything under `.git/objects` read-only, and Windows refuses
    to delete a read-only file however the permissions read elsewhere. With
    `ignore_errors=True` that silently produced the half-deleted tree behind
    the reported error: the loose files went, `.git` stayed, and `src` was
    still *there* with nothing installable in it.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass  # reported by the caller, which checks whether the path survived


def _remove_tree(path: Path) -> str:
    """Delete a directory. Returns "" on success, else why it is still around.

    A tree we cannot delete is moved aside instead. Being unable to remove an
    old install is not a reason to be unable to make a new one, and "go and
    delete this folder by hand" is the advice this whole module exists to
    stop giving.
    """
    path = Path(path)
    if not path.exists():
        return ""
    if not path.is_dir():
        try:
            path.unlink()
        except OSError as exc:
            return f"{path} is a file and couldn't be removed ({exc})"
        return ""
    # onexc replaced onerror in 3.12; both call the same hook here.
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_drop_readonly)
    else:  # pragma: no cover - 3.11 only
        shutil.rmtree(path, onerror=_drop_readonly)
    if not path.exists():
        return ""
    aside = path.with_name(f"{path.name}.old-{int(time.time())}")
    try:
        path.rename(aside)
    except OSError as exc:
        return f"{path} could not be removed ({exc})"
    logging.getLogger("memorymap.searxng").warning(
        "Couldn't delete %s, so it was moved to %s. It can be deleted by hand.",
        path,
        aside,
    )
    return ""


def uninstall_source(data_dir: Path) -> dict:
    """Delete the virtualenv and checkout so the next start installs fresh.

    A part-finished install: pip interrupted, a half-cloned checkout, a venv
    built against a Python that has since been upgraded, leaves
    `source_installed` saying yes and the process dying instantly, which reads
    as "it just doesn't work" with nothing to act on. There was no way to get
    back to a clean state short of deleting folders by hand.

    The generated settings.yml is deliberately kept: it holds the instance's
    secret key and any edits the user has made, and it is not what breaks.
    """
    data_dir = Path(data_dir)
    try:
        # `_stop_source` is `searxng_process`'s, called via `searxng_manager.`
        # like every other name the test suite can monkeypatch there (see the
        # note by this file's imports): a plain `from ... import` would have
        # its own additional problem too, an import cycle, since that module
        # imports `source_installed`/`install_source` from this one.
        searxng_manager._stop_source(data_dir)
    except SearxngError:
        pass  # nothing to stop, or it was already gone, either way, carry on
    _pid_file(data_dir).unlink(missing_ok=True)
    _import_ok.discard(str(data_dir))

    removed, failed = [], []
    for path in (_venv_dir(data_dir), _source_dir(data_dir)):
        if not path.exists():
            continue
        problem = searxng_manager._remove_tree(path)
        (failed if problem else removed).append(problem or path.name)
    searxng_manager.log_path(data_dir).unlink(missing_ok=True)
    if failed:
        # Reporting a wipe that didn't happen is what let the next install
        # walk into the same broken folder and blame pip for it.
        raise SearxngError(
            "Couldn't clear the old SearXNG install: "
            + "; ".join(failed)
            + ". Close anything using those folders (a file explorer counts) "
            "and try again."
        )
    return {"removed": removed}


def reinstall_source(data_dir: Path, on_ready=None) -> dict:
    """Wipe the install and start a fresh one in the background.

    `on_ready` is handed to `install_source`: with it, the rebuilt SearXNG
    starts itself when the install lands, so reinstall is one press rather
    than reinstall-wait-Start.
    """
    if _install_state["running"]:
        raise SearxngError("An install is already running, let it finish first.")
    result = uninstall_source(data_dir)
    searxng_manager.install_source(data_dir, on_ready=on_ready)
    return {**result, "installing": True}
