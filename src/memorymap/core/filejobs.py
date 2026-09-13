"""Which files the models are reading right now, so the Tasks panel can say so.

Asked for twice: *"the describe with ai feature needs to show in background
process, same for all ocr processes"*. Before this, describing a file or
reading one with a vision model was invisible: the button went quiet, the
panel that lists background work showed nothing, and on a slow local model
the only evidence anything was happening was that the app had not answered
yet. A job you cannot see is a job the user assumes has failed.

**Why a registry rather than a real background job.** `/files/{id}/analyse`
is synchronous: it runs the model on the request's own thread and returns the
reading in the response, which is what the frontend is built around. That is
worth keeping (the caller gets the caption it asked for, with no polling and
no second round trip), and it does not stop the work being *reported*: FastAPI
serves `/tasks` on a different worker thread, so a request that is busy inside
a model call can still be listed by one that is not. So this is deliberately
not a job queue. It is a note on the wall saying which files are being read,
written when the work starts and rubbed out when it ends.

**Cancellation is not offered, and that is honest rather than lazy.** Every
kind in `bgtasks` can be stopped because each owns something interruptible: a
flag checked between steps, or a child process. A single blocking call into a
local model owns neither. `bgtasks` requires that a registered kind can be
stopped, so these are reported by `/tasks` and deliberately not registered
there: a Quit button that did nothing would be worse than no button.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator

#: What each kind is called on screen. The panel shows the verb, because the
#: file's own name is the `detail` line underneath it.
LABELS = {
    "describe": "Describing a file",
    "ocr": "Reading text from a file",
    "vision": "Reading a file with the vision model",
}

_lock = threading.Lock()
#: `(kind, attachment_id)` -> what the panel needs to draw a row. Keyed on the
#: pair rather than the id alone: describing a scan and OCR-ing it are two
#: different readings of one file and a person can start both.
_running: dict[tuple[str, int], dict] = {}


@contextmanager
def reading(kind: str, attachment_id: int, filename: str, model: str = "") -> Iterator[None]:
    """Announce that `kind` is running on this file for as long as the block.

    `finally`, not a plain pair of calls: a model that raises (no Ollama, a
    file the reader cannot open, a cancelled request) must not leave a row on
    the panel for the rest of the session. That is the failure mode this kind
    of registry always has, and the reason every exit path has to remove the
    entry rather than only the happy one.
    """
    key = (kind, int(attachment_id))
    entry = {
        "kind": kind,
        "attachment_id": int(attachment_id),
        "filename": filename or "",
        "model": model or "",
        "started": time.time(),
    }
    with _lock:
        _running[key] = entry
    try:
        yield
    finally:
        with _lock:
            _running.pop(key, None)


def running() -> list[dict]:
    """Every reading in flight, oldest first, as `/tasks` rows.

    Oldest first because the panel reads as a queue: the thing that has been
    waiting longest is the one a person is wondering about.
    """
    with _lock:
        entries = sorted(_running.values(), key=lambda item: item["started"])
    rows = []
    for entry in entries:
        name = entry["filename"] or f"file {entry['attachment_id']}"
        rows.append(
            {
                "kind": f"file-{entry['kind']}",
                "name": name,
                "label": LABELS.get(entry["kind"], "Reading a file"),
                #: The model is worth naming: on a local machine "which model
                #: is this going through" is most of the answer to "why is it
                #: taking so long".
                "detail": f"{name} ({entry['model']})" if entry["model"] else name,
                #: A single model call reports no progress. `None` is the
                #: panel's own "running, no percentage" state, which is the
                #: truth here; a fake bar would be worse than none.
                "progress": None,
                "log": [],
            }
        )
    return rows
