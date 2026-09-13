"""Quitting background work: one job, or all of it at once.

Two requests, one mechanism, and they turned out to be the same mechanism:

- *"allow the quitting/killing of background tasks as well"*, the Tasks panel
  listed eight kinds of job and offered a Quit button on exactly two of them
  (a re-index and a model pull). Everything else: a pip install minutes into
  building a wheel, a multi-hundred-megabyte model download, a SearXNG source
  build, an autonomous pass rewriting tags, could be watched and not stopped.
- *"make sure that if the app is quit, all ai tasks and bg tasks stop as
  well"*, and nothing stopped them, because there was no shutdown handler at
  all. Daemon threads die with the process, but a pip subprocess is not a
  daemon thread: it is a child that outlives its parent, and a SearXNG
  install killed halfway by a process exit leaves a half-written checkout.

So this module is the dispatch table both need. `cancel(kind)` is one job;
`stop_all()` is every job, and is what the shutdown handler calls.

**Why a table rather than a method on each job.** The kinds do not share an
implementation and should not be made to: a pull is an HTTP stream this app
drives, an install is someone else's process, an autonomous pass is a
generator this app consumes. What they share is a *name*, the `kind` string
`/tasks` already uses: so that is what the table is keyed on. Adding a
background job means adding one line here, and the panel's Quit button starts
working without touching the frontend.

**Every canceller must be safe to call when nothing is running**, because
`stop_all` calls all of them at shutdown without checking which are live.
They return `(acted, message)`; `False` with a message is a normal answer, not
an error.

**Nothing here kills a thread.** Python cannot do it safely and this app
writes to a notebook the user cares about; a stop is always either a
cooperative flag checked at the next boundary or a `terminate()` on a child
process that owns nothing of ours. The one cost is latency, up to one model
call for an agent pass, and that is the right trade.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger("memorymap.tasks")

#: How long a *scheduled* autonomous pass stays off after a shutdown-time
#: stop. Short on purpose: quitting the app is not the same statement as
#: quitting a pass, and the next launch should behave normally.
_SHUTDOWN_SNOOZE_SECONDS = 60


def _cancel_reindex(_name: str) -> tuple[bool, str]:
    from memorymap.ai import model_manager

    if model_manager.cancel_reindex():
        return True, "Asked the re-index to stop."
    return False, "Nothing is re-indexing."


def _cancel_pull(name: str) -> tuple[bool, str]:
    from memorymap.ai import model_manager

    if not name:
        # Shutdown passes no name: stop every download rather than none.
        stopped = [n for n, job in (model_manager.pull_statuses() or {}).items()
                   if job.get("status") == "running" and model_manager.cancel_pull(n)]
        return bool(stopped), f"Stopped {len(stopped)} download(s)." if stopped else "Nothing is downloading."
    if model_manager.cancel_pull(name):
        return True, f"Asked the {name} download to stop."
    return False, "That download isn't running."


def _cancel_autonomous(_name: str) -> tuple[bool, str]:
    from memorymap.ai import autonomous

    if autonomous.request_stop():
        held = autonomous.snoozed_for()
        hours, minutes = divmod(max(1, round(held / 60)), 60)
        when = f"{hours}h" if hours and not minutes else (
            f"{hours}h {minutes}m" if hours else f"{minutes} minutes"
        )
        # Reported: *"The auto ai optimisation didnt instantly quit?? what
        # does quitting safely mean??"*, a fair complaint about both the
        # behaviour and the sentence. "The next safe point" named nothing a
        # user could picture, so a stop that took twenty seconds looked like a
        # button that had not worked.
        #
        # What actually happens: the pass is a loop of model calls, and it is
        # abandoned between them rather than killed mid-call. Nothing further
        # is asked of the model the moment you press this; what you wait for
        # is the reply already in flight to arrive and be discarded, which on
        # a local model is however long that one answer takes. It is not
        # killed mid-flight because the thread may be part-way through writing
        # to the notebook, and a half-applied edit is worse than a slow stop.
        return True, (
            "Stopping: nothing more will be asked of the model. The reply "
            "already in flight has to arrive first, so this can take a few "
            f"seconds. It won't start again for {when}."
        )
    return False, "No pass is running."


def _cancel_extra(_name: str) -> tuple[bool, str]:
    from memorymap.core import extras

    return extras.cancel()


def _cancel_embedding_model(_name: str) -> tuple[bool, str]:
    from memorymap.core import embedmodels

    return embedmodels.cancel()


def _cancel_searxng_install(_name: str) -> tuple[bool, str]:
    from memorymap.search import searxng_manager

    if not searxng_manager._install_state.get("running"):
        return False, "No SearXNG setup is running."
    searxng_manager.stop_streaming()
    return True, "Stopping the SearXNG setup."


def _cancel_searxng_start(_name: str) -> tuple[bool, str]:
    """A start that is still waiting for the service to answer.

    Stopping the *service* is the only way to stop waiting for it, and it is
    what someone pressing Quit on "Starting SearXNG" means: they want it not
    to be starting.
    """
    from memorymap.core import deps
    from memorymap.search import searxng_manager

    if not searxng_manager.starting():
        return False, "SearXNG isn't starting."
    try:
        searxng_manager.stop(deps.get_config().data_dir)
    except Exception as exc:  # noqa: BLE001  # a stop that fails is not a 500
        logger.warning("couldn't stop SearXNG: %s", exc)
        return False, "Couldn't stop it: see Settings → Logs."
    return True, "Stopped SearXNG."


#: kind (as `/tasks` reports it) → canceller. `embeddings` is deliberately
#: absent: the warmup is one blocking model load inside sentence-transformers
#: with nothing to check a flag between, so the panel says so rather than
#: offering a button that would do nothing.
CANCELLERS: dict[str, Callable[[str], tuple[bool, str]]] = {
    "reindex": _cancel_reindex,
    "pull": _cancel_pull,
    "autonomous": _cancel_autonomous,
    "extra": _cancel_extra,
    "embedding-model": _cancel_embedding_model,
    "searxng": _cancel_searxng_install,
    "searxng-start": _cancel_searxng_start,
}

#: What the Tasks panel puts a Quit button on. Derived from the table rather
#: than repeated in `routes_tasks.collect()`, where it had drifted out of date
#: twice: every job there hard-coded its own `"cancellable"` bool.
CANCELLABLE_KINDS = frozenset(CANCELLERS)


def cancel(kind: str, name: str = "") -> tuple[bool, str]:
    """Stop one job. Returns (acted, message): never raises."""
    canceller = CANCELLERS.get(kind)
    if canceller is None:
        return False, "That job can't be stopped."
    try:
        return canceller(name)
    except Exception as exc:  # noqa: BLE001  # a failed stop is a message
        # `kind` arrives in a request body, so it is untrusted text going into
        # a log line: CodeQL's py/log-injection, and a real one: a value
        # carrying a newline can forge a whole extra log record, which is
        # exactly the kind of thing the log viewer in Settings is read to
        # investigate. Stripped rather than escaped, because a job kind never
        # legitimately contains a line break.
        safe_kind = kind.replace("\r", "").replace("\n", "")
        logger.warning("couldn't stop the %s job: %s", safe_kind, exc, exc_info=True)
        return False, "Couldn't stop that job, see Settings → Logs."


def stop_all() -> list[str]:
    """Stop every background job. Returns what was actually stopped.

    Called from the app's shutdown handler, so it must be fast and must never
    raise: a shutdown that hangs on a stuck job is the thing it exists to
    prevent, and the process is going away regardless.

    The autonomous scheduler is stopped as well as its current pass, the
    thread is a daemon and would die anyway, but joining it here means a pass
    part-way through a write finishes that write rather than being cut off at
    an arbitrary bytecode.
    """
    stopped: list[str] = []
    for kind in CANCELLERS:
        acted, _ = cancel(kind)
        if acted:
            stopped.append(kind)

    try:
        from memorymap.ai import autonomous

        # A short hold, not the usual interval: see _SHUTDOWN_SNOOZE_SECONDS.
        autonomous.request_stop(snooze_seconds=_SHUTDOWN_SNOOZE_SECONDS)
        autonomous.stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("couldn't stop the autonomous scheduler: %s", exc)

    # SearXNG is the one background thing that is a real OS process this app
    # started, and leaving it behind is the orphan `/shutdown` was written to
    # avoid: a second launch then finds the port taken by the first.
    try:
        from memorymap.core import deps
        from memorymap.search import searxng_manager

        if searxng_manager.status(deps.get_config().data_dir).get("running"):
            searxng_manager.stop(deps.get_config().data_dir)
            stopped.append("searxng")
    except Exception as exc:  # noqa: BLE001
        logger.warning("couldn't stop SearXNG at shutdown: %s", exc)

    if stopped:
        logger.info("stopped background work at shutdown: %s", ", ".join(sorted(set(stopped))))
    return stopped
