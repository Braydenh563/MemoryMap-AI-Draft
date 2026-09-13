"""`GET /debug/health`, observability that costs nothing (PLAN.md B9).

Every number here already exists somewhere: `routes_tasks.collect()` already
builds the running-jobs list, `taskhistory` already remembers how each job
ended, `logbuffer` already tails the app log. This route is deliberately not
a new subsystem, just a single cheap read across the ones that exist,
because the thing being asked for is a page that answers "is this notebook
okay" in one glance: a support-bundle-sized diagnostic would defeat that.

**The <20ms budget is the whole design constraint.** Every count below is a
`COUNT(*)` filtered only by an indexed `workspace_id` (`WorkspaceMixin`
gives every one of these tables that index), nothing here does the thing
`support_bundle` can afford to (`entries_deleted`, `entries_private`, a
second query per flag): those extra WHERE clauses are still full scans of
the same rows without a matching composite index, and irrelevant to "is
this notebook alive", so they were deliberately left out of this endpoint
and left in that one, which has no latency budget at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap import __version__
from memorymap.api import routes_tasks
from memorymap.core import deps, logbuffer, taskhistory
from memorymap.core.database import Attachment, Document, Entry, MediaUpload, Reminder
from memorymap.core.deps import get_session

router = APIRouter(prefix="/debug", tags=["debug"])

#: How many recent error/warning lines to surface, enough to see whether
#: something is actively wrong without turning this into the Logs viewer
#: (which already exists, and pages).
ERROR_TAIL = 20

#: The levels a person means by "errors" here. `logbuffer` also carries INFO
#: and DEBUG lines, which would drown the two levels anyone actually opens
#: this page to check for.
_ERROR_LEVELS = frozenset({"ERROR", "WARNING"})


@router.get("/health")
def debug_health(session: Session = Depends(get_session)) -> dict:
    """One page's worth of "is this notebook okay", Settings › About reads
    this to draw its Health block, and it is meant to be safe to hit from a
    bug report too: nothing here is note content, nothing here writes.
    """
    config = deps.get_config()
    try:
        db_size_bytes = config.db_path.stat().st_size
    except OSError:
        # A brand new notebook, or a data dir moved out from under the
        # process: 0 is the honest answer, not a 500 over a stat() call.
        db_size_bytes = 0

    counts = {
        "entries": session.scalar(
            select(func.count(Entry.id)).where(Entry.is_deleted == False)  # noqa: E712
        )
        or 0,
        "documents": session.scalar(select(func.count(Document.id))) or 0,
        "media": session.scalar(select(func.count(MediaUpload.id))) or 0,
        "attachments": session.scalar(select(func.count(Attachment.id))) or 0,
        "reminders": session.scalar(select(func.count(Reminder.id))) or 0,
    }

    running_jobs = routes_tasks.collect()
    error_lines = [
        record
        for record in logbuffer.recent(limit=logbuffer.MAX_RECORDS)
        if record.get("level") in _ERROR_LEVELS
    ][-ERROR_TAIL:]

    return {
        "app_version": __version__,
        "data_dir": str(config.data_dir),
        "db": {"path": str(config.db_path), "size_bytes": db_size_bytes},
        "counts": counts,
        "jobs": {"queue_depth": len(running_jobs), "running": running_jobs},
        "latency_ms_by_kind": taskhistory.latency_percentiles(),
        "recent_errors": error_lines,
    }
