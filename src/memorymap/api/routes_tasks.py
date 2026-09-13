"""What is running in the background, in one place.

Settings → Background tasks used to build its own list in `app.js` out of the
two jobs that happened to be in `/models/status`, a re-index and a model
download. Everything else the app does on a worker thread was invisible
there: the embedding model loading at startup (~90 MB on first use), and the
SearXNG install, which is the longest-running job in the whole app at several
minutes and the one most likely to be what a user came to this screen to ask
about.

So the list is assembled here instead, and the frontend renders whatever it is
given. The point is the next job: anything long enough to need a background
thread should be added to `collect()` and it appears on the screen, rather
than being invisible until someone remembers to teach the UI about it.

Running work is listed first, and what recently *stopped* below it. The second
half was added after the first proved to hide the one case anyone cares about:
a job that fails vanishes at the instant it becomes interesting, leaving the
same empty list as a job that succeeded. The history is in-memory, bounded,
and records endings only, see `core/taskhistory.py`.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from memorymap.ai import embeddings as embeddings_module
from memorymap.ai import model_manager as jobs
from memorymap.core import bgtasks, deps, embedmodels, extras, filejobs, taskhistory

router = APIRouter(tags=["tasks"])


def _percent(done: int, total: int) -> float | None:
    """A fraction, or None when the total isn't known yet: a progress bar
    that guesses is worse than one that admits it can't say."""
    if not total or total <= 0:
        return None
    return max(0.0, min(1.0, done / total))


def collect() -> list[dict]:
    """Every background job currently running, newest concern first."""
    tasks: list[dict] = []

    reindex = jobs.reindex_status()
    if reindex and reindex["status"] == "running":
        tasks.append(
            {
                "kind": "reindex",
                "name": "",
                "label": "Re-indexing your notes",
                "detail": f"{reindex['done']} of {reindex['total']}",
                "progress": _percent(reindex["done"], reindex["total"]),
                                "log": [],
            }
        )

    for name, job in (jobs.pull_statuses() or {}).items():
        if job["status"] != "running":
            continue
        fraction = _percent(job["done"], job["total"])
        tasks.append(
            {
                "kind": "pull",
                "name": name,
                "label": f"Downloading {name}",
                "detail": f"{round(fraction * 100)}%" if fraction is not None else "starting…",
                "progress": fraction,
                                "log": [],
            }
        )

    # The embedding model loads in a background thread at startup so the first
    # search isn't slow. On a fresh install that includes a ~90 MB download,
    # which is a long silence to explain with nothing on screen.
    if embeddings_module.warmup_running():
        tasks.append(
            {
                "kind": "embeddings",
                "name": deps.get_model_manager().embedding_model(),
                "label": "Loading the embedding model",
                "detail": "The first run downloads it (~90 MB). Search falls "
                "back to keywords until it's ready. This one can't be "
                "stopped part-way: it is a single load with nothing to "
                "interrupt between.",
                "progress": None,
                                "log": [],
            }
        )

    # A vision-model caption in flight (ROADMAP §89.6). Not cancellable: 
    # same reasoning as the embedding warmup above: one blocking model call
    # with nothing to check a flag between.
    from memorymap.ai import captioning

    for job in captioning.running_captions():
        tasks.append(
            {
                "kind": "caption",
                "name": str(job["upload_id"]),
                "label": f"Captioning {job['name']}",
                "detail": "A vision model is describing this image.",
                "progress": None,
                "log": [],
            }
        )

    # A PDF page being read in the OCR workspace (`_read_page`). Not
    # cancellable from here for the same reason the two above are not: it is
    # one blocking model (or Tesseract) call with nothing to check a flag
    # between. The workspace's own Stop button abandons the *request*, which is
    # what the person pressing it actually wants.
    from memorymap.ai import vision_ocr as _vision_ocr

    for job in _vision_ocr.running_page_reads():
        tasks.append(
            {
                "kind": "page-read",
                "name": str(job["token"]),
                "label": job["label"],
                "detail": f"{job['model']} is reading this page."
                if job["model"]
                else "A vision model is reading this page.",
                "progress": None,
                "log": [],
            }
        )

    # Reading an attached file: "Describe with AI", the local OCR pass, and
    # the vision read. Same not-cancellable reasoning as the three above.
    tasks.extend(filejobs.running())

    # Autonomous optimization task
    from memorymap.ai import autonomous
    if autonomous.is_running():
        tasks.append(
            {
                "kind": "autonomous",
                "name": "",
                "label": "Autonomous optimization",
                "detail": "Analysing your notes in the background. Quitting "
                "stops it at the next safe point and keeps it from starting "
                "again for a while.",
                "progress": None,
                                "log": [],
            }
        )

    # Minutes long, on a worker thread, and previously visible only on the Web
    # search screen: so "is it still doing anything?" had no answer anywhere
    # else. Imported here rather than at module level: it pulls in the search
    # stack, and this endpoint is polled.
    from memorymap.search import searxng_manager

    # A start is not an install, and it is the longer silence of the two from
    # the user's side: it waits up to START_TIMEOUT for the service to answer
    # and shows nothing while it does.
    starting = searxng_manager.starting()
    if starting:
        waited = int(time.time() - (starting.get("since") or time.time()))
        tasks.append(
            {
                "kind": "searxng-start",
                "name": "",
                "label": "Starting SearXNG",
                "detail": (
                    f"Waiting for it to answer ({waited}s of "
                    f"{searxng_manager.START_TIMEOUT}s): "
                    f"{starting.get('backend') or 'source'} backend."
                ),
                "progress": min(waited / max(searxng_manager.START_TIMEOUT, 1), 1.0),
                                "log": [],
            }
        )

    # Downloading an embedding model (Settings → Extras, the "Search by
    # meaning" models list). Its own `DownloadState` docstring already says
    # "for /tasks and the panel", the panel half was built, this half never
    # was, so a multi-hundred-MB download with its own dropped-connection
    # retry logic was visible only while that one exact settings screen
    # happened to be open (`renderEmbedModels`'s own poll gates on
    # `currentSettingsSection === "extras"`), and invisible everywhere else
    # in the app the instant you clicked away. Tier 1 §6.
    embed_download = embedmodels.current()
    if embed_download.running:
        model = embedmodels.EMBED_MODELS_BY_ID.get(embed_download.model_id)
        tasks.append(
            {
                "kind": "embedding-model",
                "name": embed_download.model_id,
                "label": f"Downloading {model.label}" if model else "Downloading an embedding model",
                "detail": embed_download.step or "starting…",
                # No fraction reported for the same reason pip's isn't below:
                # snapshot_download doesn't hand back one worth trusting.
                "progress": None,
                                "log": list(embed_download.log),
            }
        )

    # Installing an optional extra (Settings → Extras). Here rather than on its
    # own screen for the reason this module exists: anything long enough to
    # need a background thread belongs in one list, and the status bar and the
    # Tasks panel then show it without learning anything new.
    pip = extras.current()
    if pip.running:
        tasks.append(
            {
                "kind": "extra",
                "name": pip.extra_id,
                "label": f"Installing {extras.EXTRAS_BY_ID[pip.extra_id].label}"
                if pip.extra_id in extras.EXTRAS_BY_ID
                else "Installing an optional extra",
                "detail": pip.step or "starting pip…",
                # pip does not report a fraction it is worth believing, and a
                # bar that guesses is worse than one that admits it can't say.
                "progress": None,
                                "log": list(pip.log),
            }
        )

    install = searxng_manager._install_state
    if install["running"]:
        stage = install.get("stage") or 1
        tasks.append(
            {
                "kind": "searxng",
                "name": "",
                "label": f"Setting up SearXNG: step {stage} of {install['stages']}",
                "detail": install["step"] or "This takes a few minutes the first time.",
                "progress": install.get("progress"),
                                # The lines the tools themselves printed. Reported directly:
                # "the searxng reinstall doesn't have a progress bar so idk if
                # it has frozen or is working", a bar answers that only while
                # it moves, and pip building lxml can sit on one number for a
                # while. Its output is the thing that keeps changing.
                "log": list(install.get("log") or []),
            }
        )

    # **One table decides, not eight hard-coded booleans.** Every entry above
    # used to carry its own `"cancellable": True/False`, and six of them said
    # False because nothing could stop them, which was true when they were
    # written and stopped being true when `core/bgtasks.py` gave each one a
    # canceller. A flag repeated at eight call sites is a flag that drifts;
    # this reads the same table the cancel endpoint dispatches through, so the
    # button appears exactly where pressing it does something.
    for task in tasks:
        task["cancellable"] = task["kind"] in bgtasks.CANCELLABLE_KINDS
    return tasks


@router.get("/tasks")
def list_tasks() -> dict:
    """What is running, and what has recently stopped.

    The history is the half that was missing, and the reason is narrow: a job
    that *fails* used to disappear at the moment it became interesting. A
    re-index that died halfway left exactly the same empty list as one that
    finished, and the only record of why was the log console, a different
    screen that you have to know to look at.
    """
    return {"tasks": collect(), "history": taskhistory.recent()}


class CancelTaskBody(BaseModel):
    """Which job to stop. `kind` is what `/tasks` reported for it."""

    kind: str = Field(min_length=1, max_length=40)
    #: Only `pull` needs one (a model name); empty means "all of that kind",
    #: which is what shutdown wants and what a panel with one download means.
    name: str = Field(default="", max_length=200)


@router.post("/tasks/cancel")
def cancel_task(body: CancelTaskBody) -> dict:
    """Quit one background job.

    Asked for directly: "allow the quitting/killing of background tasks as
    well". There was a `/models/jobs/cancel` before this, and it knew about
    exactly two of the eight kinds `/tasks` reports: so the panel showed a
    Quit button on a re-index and a model pull and nothing else, including on
    the jobs that take longest and are most worth stopping.

    Never 404s on an unknown kind and never 409s on a job that has already
    finished: both are answers, not errors, and the panel is polling, by the
    time a click arrives the job it was about may genuinely be over. The
    honest response is `stopped: false` and a sentence saying so.
    """
    stopped, detail = bgtasks.cancel(body.kind.strip(), body.name.strip())
    return {"status": "ok", "stopped": stopped, "detail": detail}


@router.post("/tasks/trigger-autonomous")
def trigger_autonomous() -> dict:
    """Run the background librarian now, rather than waiting for its interval.

    Returns `started: false` rather than 409-ing when one is already going:
    pressing "Run now" while it runs is not an error, it is impatience, and the
    honest answer is "it's already going". The guard itself matters, without
    it each press started another agent loop against the same notebook.

    Reported: a "completed" notification for a pass the user "didn't have
    enabled". `trigger_now` itself has never checked the master
    `autonomous_tasks_enabled` toggle: only the scheduled loop did, before
    ever calling it: so this endpoint ran the real pass regardless of the
    toggle; the "Run now" button just happens to be hidden while it's off,
    which is a UI convenience, not an authorization check. Checked here,
    before `trigger_now`, rather than inside it: `trigger_now`'s own job is
    the concurrency guard above, and folding a second, unrelated reason to
    refuse into the same bool return would make "false" ambiguous between
    "busy" and "disabled" for every existing caller of that function.
    """
    from memorymap.ai import autonomous

    if not deps.get_config().get_preference("autonomous_tasks_enabled", False):
        return {
            "status": "ok",
            "started": False,
            "detail": "Autonomous background workers are switched off in Settings.",
        }

    started = autonomous.trigger_now()
    return {
        "status": "ok",
        "started": started,
        "detail": "" if started else "A pass is already running.",
    }


@router.get("/tasks/autonomous/last")
def last_autonomous_pass() -> dict:
    """What the background librarian changed last time it ran (§40 item 2).

    The honest answer to "you are asking me to let an agent edit my notebook
    unattended". A true preview is not available, the model chooses each call
    from the result of the previous one, so a pass with the writes stubbed out
    stops resembling the pass that would really happen, but every change
    carries the tool call that reverses it, and the browser hands those back to
    `POST /chat/tools/execute`, which is the same path the chat's own Undo
    buttons already use.
    """
    from memorymap.ai import autonomous

    return autonomous.last_pass()


@router.post("/tasks/autonomous/last/clear")
def clear_last_autonomous_pass() -> dict:
    """Dismiss the review list once it has been read."""
    from memorymap.ai import autonomous

    autonomous.forget_last_pass()
    return {"status": "ok"}


@router.post("/tasks/history/clear")
def clear_history() -> dict:
    """Forget the finished-job list.

    It is in-memory and bounded, so this is a tidiness button rather than a
    maintenance one: but a screen you cannot clear is a screen people stop
    reading.
    """
    taskhistory.clear()
    return {"cleared": True}


# --- shutting the app down cleanly -------------------------------------------


@router.post("/shutdown")
def shutdown() -> dict:
    """Stop the server on purpose, from inside the app.

    Asked for: *"a way to cleanly exit the program and quit the backend."*
    Until now the only ways out were Ctrl+C in a terminal window the launcher
    hides, or closing the window and leaving the server running, which is why
    a second start could find the port taken by the first.

    Three properties this deliberately has:

    - **It is a POST behind the unlock gate and the origin check.** A GET would
      be reachable from a link, and "the app quit when I clicked something in
      another tab" is a bug report nobody enjoys writing.
    - **It replies first, then exits.** Signalling the process inline means the
      browser gets a dropped connection and shows an error for a thing that
      worked. The signal goes out on a short timer so the response is already
      on the wire.
    - **SIGINT, not `os._exit`.** It is the same signal Ctrl+C sends, so
      uvicorn runs its normal shutdown: in-flight requests finish, lifespan
      handlers run, and the SearXNG subprocess this app may own is torn down
      by the code that already knows how. A hard exit would skip all of that
      and leave the orphan it was trying to avoid.
    """
    import os
    import signal
    import threading

    def _stop() -> None:
        os.kill(os.getpid(), signal.SIGINT)

    threading.Timer(0.35, _stop).start()
    return {"stopping": True}
