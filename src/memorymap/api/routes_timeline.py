"""The notebook on a time axis (roadmap §10B).

Asked for repeatedly, and with more shape each time: *"I want a note timeline
where I can see notes visually by what time they were made. Maybe I can even
group them by events or related places etc."* The axis is time; the **bands**
are what makes it a map of what happened rather than a sorted list.

Two decisions worth knowing:

**A note can appear at a date it was not written on.** §10A resolved the
relative time in note text, "the deadline is next Friday" knows which Friday
- so a note plots at what it is *about* when it says something, and at when it
was written otherwise. That is the whole reason the timeline is more than
`ORDER BY created_at`, and every placed note says which of the two it used so
the view can be honest about it.

**Bands come from what is already stored**, category, tag, or a note thread
(`Entry.parent_id`, §87.6): rather than from an `events` table that does not
exist yet. Grouping by event is still the goal (§10), and this is the shape
it will slot into: one more `group` value.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import Entry, EntryDate, Space, utcnow
from memorymap.core.deps import get_session
from memorymap.entry import manager

router = APIRouter(prefix="/timeline", tags=["timeline"])

# How the axis is bucketed. Anything longer than a year in days would be a
# scatter of one-note columns; anything shorter than a day is not a thing a
# notebook has enough of.
SCALES = {"day": 1, "week": 7, "month": 30, "year": 365}

# One band per category or tag, plus "everything else", a chart with forty
# lanes is not a chart. The cut-off is by note count, so the bands are the
# ones the user actually writes in.
MAX_BANDS = 8
OTHER_BAND = "Everything else"

PREVIEW_CHARS = 120
MAX_NOTES = 1500  # a hard ceiling: this is drawn, not paged


def _clip(text: str, limit: int = PREVIEW_CHARS) -> str:
    """A preview that says it's a preview. A bare `text[:limit]` slice: 
    what this used to be, cuts a note off mid-word with nothing to say so,
    which is the "no ellipsis" the grid view was reported for: the card
    genuinely had less text than the note, and nothing on screen said that.
    """
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _bucket_start(when: datetime, scale: str) -> str:
    """The label of the bucket this moment belongs to."""
    if scale == "day":
        return when.date().isoformat()
    if scale == "week":
        return (when.date() - timedelta(days=when.weekday())).isoformat()
    if scale == "month":
        return when.date().replace(day=1).isoformat()
    return when.date().replace(month=1, day=1).isoformat()


@router.get("")
def timeline(
    # Days by default: a month bucket puts a whole month of notes in one
    # column, which is the shape the Timeline exists to break up.
    scale: str = "day",
    group: str = "category",
    # 0 means "everything" (see below) and is a real, used value, the lower
    # bound has to allow it. The upper bound exists because `timedelta(days=…)`
    # raises OverflowError past ~999999999 days, which an unvalidated `days`
    # let straight through as an unhandled 500 instead of a clean 422; ~110
    # years is generously past any real notebook's age.
    days: int = Query(default=365, ge=0, le=40000),
    start: str | None = None,
    end: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """Notes on a time axis, in bands.

    `scale` buckets the axis (day/week/month/year), `group` chooses the bands
    (category/tag/thread/none), `days` is how far back to look, 0 for everything.
    """
    if scale not in SCALES:
        raise HTTPException(
            status_code=422, detail=f"scale must be one of {', '.join(SCALES)}"
        )
    if group not in ("category", "tag", "thread", "none"):
        raise HTTPException(
            status_code=422, detail="group must be category, tag, thread or none"
        )

    query = select(Entry).where(
        Entry.is_deleted == False,  # noqa: E712
        Entry.is_private == False,  # noqa: E712  # private text stays out of a view
    )
    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            query = query.where(Entry.created_at >= start_dt, Entry.created_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date format for start/end")
    elif days > 0:
        query = query.where(Entry.created_at >= utcnow() - timedelta(days=days))
    entries = list(session.scalars(query.order_by(Entry.created_at.desc()).limit(MAX_NOTES)))

    # What each note is *about*, where it said so. One query rather than one
    # per note: a timeline over a year of notes would otherwise be hundreds.
    resolved: dict[int, EntryDate] = {}
    if entries:
        rows = session.scalars(
            select(EntryDate)
            .where(EntryDate.entry_id.in_([entry.id for entry in entries]))
            .order_by(EntryDate.id)
        )
        for row in rows:
            resolved.setdefault(row.entry_id, row)

    categories = manager.bulk_category_names(session, entries)

    # The table view's columns (TIMELINE_PLAN decision 6): which space a note
    # is in, how long it is and how many notes it is joined to. All three are
    # one query each for the whole page rather than one per row, the same
    # batching `resolved` above uses: a timeline over a year of writing is
    # hundreds of rows and this endpoint is drawn on every visit to the tab.
    spaces = {space.id: space.name for space in session.scalars(select(Space))}
    links = manager.links_for_entries_bulk(session, [entry.id for entry in entries])

    placed = []
    for entry in entries:
        mention = resolved.get(entry.id)
        at = mention.at if mention else entry.created_at
        text = manager.readable_content(entry)
        placed.append(
            {
                "id": entry.id,
                "at": at.isoformat(),
                "bucket": _bucket_start(at, scale),
                # Said out loud so the view can be honest: this note is here
                # because of what it talks about, not when it was typed.
                "placed_by": "mentioned" if mention else "written",
                "phrase": mention.phrase if mention else "",
                "written_at": entry.created_at.isoformat(),
                "category": categories.get(entry.category_id, manager.UNCATEGORISED),
                "tags": manager.entry_tags(entry),
                # Only read by `_thread_bands` (group=thread): carried for
                # every note regardless of the chosen group so switching to
                # "Thread" never needs a second fetch.
                "parent_id": entry.parent_id,
                "pinned": entry.pinned,
                # The space's own name, not its id: the id is a slug nobody
                # named, and the column has to be readable. It falls back to
                # the id for a space that has been deleted out from under its
                # notes, which is more honest than an empty cell.
                "space": spaces.get(entry.workspace_id, entry.workspace_id),
                # A word count, not a character count: it is the number people
                # think in, and `_clip` has already thrown the characters away.
                "words": len(text.split()),
                "links": len(links.get(entry.id, [])),
                "preview": _clip(text),
            }
        )

    return {
        "scale": scale,
        "group": group,
        "notes": placed,
        "bands": _bands(placed, group),
        "buckets": sorted({note["bucket"] for note in placed}),
    }


def _bands(notes: list[dict], group: str) -> list[dict]:
    """The lanes, biggest first, with a lane for the long tail."""
    if group == "none":
        return [{"name": "All notes", "count": len(notes), "ids": [n["id"] for n in notes]}]
    if group == "thread":
        return _thread_bands(notes)

    members: dict[str, list[int]] = defaultdict(list)
    for note in notes:
        if group == "category":
            members[note["category"]].append(note["id"])
        else:
            for tag in note["tags"] or ["untagged"]:
                members[tag].append(note["id"])

    ranked = sorted(members.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    bands = [
        {"name": name, "count": len(ids), "ids": ids} for name, ids in ranked[:MAX_BANDS]
    ]
    tail = ranked[MAX_BANDS:]
    if tail:
        ids = sorted({note_id for _, group_ids in tail for note_id in group_ids})
        bands.append({"name": OTHER_BAND, "count": len(ids), "ids": ids})
    return bands


THREAD_BAND = "Single notes & smaller threads"


def _thread_bands(notes: list[dict]) -> list[dict]:
    """One lane per thread, a root note and everything that continues it
    (`Entry.parent_id`), the one grouping a grid genuinely cannot show at
    all: a conversation with itself, spread across days or months (§87.6: 
    IDEAS.md's "branching line with offshoots", joined with the thread
    structure `parent_id` already stores). A parent outside the currently
    loaded window (out of the date range, private, or deleted) makes its
    child a root of its own rather than a second query reaching further
    back: the same honest simplification the `days` filter already asks
    the rest of this view to accept.

    A note with no children is not a thread, so it does not get its own
    lane: every such note, plus any real thread beyond the lane cap,
    folds into one shared band, the same shape category/tag grouping
    already uses for its own long tail.
    """
    by_id = {note["id"]: note for note in notes}

    def root_of(note: dict) -> dict:
        seen = {note["id"]}
        current = note
        # A parent chain is at most as deep as the notebook has notes; this
        # caps the walk defensively rather than trusting that shape holds.
        for _ in range(200):
            parent = by_id.get(current.get("parent_id"))
            if parent is None or parent["id"] in seen:
                return current
            seen.add(parent["id"])
            current = parent
        return current

    members: dict[int, list[int]] = defaultdict(list)
    roots: dict[int, dict] = {}
    for note in notes:
        root = root_of(note)
        members[root["id"]].append(note["id"])
        roots[root["id"]] = root

    threads = sorted(
        (item for item in members.items() if len(item[1]) > 1),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )
    bands = [
        {"name": _clip(roots[root_id]["preview"], 40) or f"Note #{root_id}", "count": len(ids), "ids": ids}
        for root_id, ids in threads[:MAX_BANDS]
    ]
    solo_ids = {i for root_id, ids in members.items() if len(ids) == 1 for i in ids}
    overflow_ids = {i for _, ids in threads[MAX_BANDS:] for i in ids}
    other = solo_ids | overflow_ids
    if other:
        bands.append({"name": THREAD_BAND, "count": len(other), "ids": sorted(other)})
    return bands
