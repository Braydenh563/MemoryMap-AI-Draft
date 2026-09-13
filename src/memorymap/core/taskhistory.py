"""What background work has finished, and how it went.

Settings → Background tasks showed only what was *running*, on the reasoning
that a finished job is not a task and a screen that accumulates them is a log.
That is tidy and it is wrong in one specific way, which is the way that
matters: **a job that fails disappears at the moment it becomes interesting.**

A re-index that dies halfway, a model download that 404s, a SearXNG install
that gives up: each vanished from the screen the instant it stopped, leaving
the same empty list as a job that finished perfectly. The only difference the
user could see was that the thing they were waiting for never arrived, and the
only place the reason existed was the log console, which is a different screen
and assumes you know to look.

So: a short, bounded history of what *stopped*, with the outcome and the
reason. Deliberately small in scope, 

- **In memory, not the database.** This is "what happened while the app has
  been open", which is the question people actually ask, and it costs no
  schema, no migration and no cleanup job. It goes away on restart, and that
  is the right lifetime for it.
- **Bounded hard.** A ring of the last `MAX_ENTRIES`, so a machine that
  re-indexes on a loop cannot grow this without limit.
- **One entry per finish, never per update.** The running list already reports
  progress; this records endings.

It is a module-level singleton for the same reason the log buffer is: the app
refuses to run with more than one worker (`deps.refuse_multiple_workers`), so
"the process" and "the app" are the same thing here.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

#: How many finished jobs to remember. Enough to cover a first-run sequence
#: (embedding warm-up, a model pull, a re-index, a SearXNG install) several
#: times over, and small enough that nobody has to think about the memory.
MAX_ENTRIES = 40

#: The outcomes a job can end in. `cancelled` is deliberately distinct from
#: `failed`: the user stopping something is not an error, and reporting it in
#: red teaches people to ignore red.
OUTCOMES = ("completed", "failed", "cancelled")

_lock = threading.Lock()
_finished: deque[dict] = deque(maxlen=MAX_ENTRIES)


def record(
    kind: str,
    label: str,
    outcome: str,
    detail: str = "",
    name: str = "",
    duration_ms: float | None = None,
) -> None:
    """Note that a background job ended. Never raises.

    Called from worker threads at the moment a job stops, so it must not be
    able to turn a finished job into a crashed one, a history entry is the
    least important thing happening at that point.

    `duration_ms` is optional and best-effort: most call sites already hold a
    start time for their own progress reporting (`_state.started`, a
    `Job.started_at`) and pass `(time.monotonic() - start) * 1000` through;
    a few do not, and a history entry with no timing is still better than one
    dropped for lacking it. `/debug/health`'s p50/p95 (PLAN B9) is computed
    only over entries that carry a number, per `kind`.
    """
    try:
        with _lock:
            _finished.append(
                {
                    "kind": kind,
                    "name": name,
                    "label": label,
                    "outcome": outcome if outcome in OUTCOMES else "completed",
                    "detail": (detail or "")[:400],
                    "at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": (
                        round(duration_ms, 1)
                        if isinstance(duration_ms, (int, float)) and duration_ms >= 0
                        else None
                    ),
                }
            )
    except Exception:  # noqa: BLE001  # bookkeeping must never break the job
        pass


def recent(limit: int = MAX_ENTRIES) -> list[dict]:
    """The most recently finished jobs, newest first."""
    with _lock:
        return list(_finished)[-limit:][::-1]


def clear() -> None:
    """Forget the history: used by the UI's clear button, and between tests."""
    with _lock:
        _finished.clear()


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list. No numpy: the
    ring buffer this reads is bounded at `MAX_ENTRIES`, so there is never
    enough data here to justify the dependency."""
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, int(round(pct / 100 * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def latency_percentiles() -> dict[str, dict[str, float | int]]:
    """p50/p95 latency (ms) per task `kind`, over whatever finished jobs in
    the ring buffer recorded a `duration_ms`. Jobs that never measured their
    own time (see `record`'s docstring) are excluded rather than counted as
    zero, which would understate every percentile silently.

    Used only by `GET /debug/health` (PLAN B9); this is `O(n log n)` over at
    most `MAX_ENTRIES` (40) entries, so it never threatens the endpoint's
    <20ms budget.
    """
    by_kind: dict[str, list[float]] = {}
    with _lock:
        entries = list(_finished)
    for entry in entries:
        duration = entry.get("duration_ms")
        if duration is None:
            continue
        by_kind.setdefault(entry["kind"], []).append(duration)
    result: dict[str, dict[str, float | int]] = {}
    for kind, values in by_kind.items():
        values.sort()
        result[kind] = {
            "p50_ms": round(_percentile(values, 50), 1),
            "p95_ms": round(_percentile(values, 95), 1),
            "count": len(values),
        }
    return result
