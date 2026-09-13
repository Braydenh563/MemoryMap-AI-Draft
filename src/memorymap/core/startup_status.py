"""A single current-phase string, set by `create_app()` and read by the
desktop launcher's loading window (`__main__.py`).

Exists for one reason: for most of startup, uvicorn has not bound its
listening socket yet (`_wait_for_server`'s own docstring explains why), so
there is no HTTP endpoint the loading window could poll even if it wanted
one. But the launcher and `create_app()` run in the same process, the
server starts on a background thread, not a subprocess, so a plain
in-memory variable, guarded the same way any other cross-thread state in
this codebase is, reaches the launcher thread directly with no server, no
socket and no polling endpoint required.

Not meant for anything else: this is not a job-progress system for the API
(`core/logbuffer.py`/background-tasks already own that), just a single
"what is `create_app()` doing right now" string for the one reader that
needs it before there is any other way to ask.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_phase = "Starting…"


def set_phase(text: str) -> None:
    global _phase
    with _lock:
        _phase = text


def get_phase() -> str:
    with _lock:
        return _phase
