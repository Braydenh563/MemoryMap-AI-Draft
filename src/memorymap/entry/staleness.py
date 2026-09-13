"""Notes nobody has touched in a long time, with nothing else pointing at them.

Detection here is deliberately arithmetic, the same reasoning `duplicates.py`
gives for staying off AI on its own task: age and connectedness are both
plain columns and joins, already exact, and asking a model to guess which
notes feel "forgotten" would be slower, less explainable, and no more
correct than just reading the columns that already say so.

Kept intentionally conservative: every signal has to agree before a note
qualifies. A false positive here means nagging someone about a note they
deliberately keep untouched (a reference note, a finished project write-up),
which is the same cost `duplicates.py` weighs against a wrongly-matched pair.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import Entry, EntryLink

#: A note untouched for less than this is just quiet, not forgotten.
DEFAULT_STALE_DAYS = 90


def find_stale_orphaned_notes(
    session: Session, days: int = DEFAULT_STALE_DAYS
) -> list[Entry]:
    """Notes untouched for `days`, with no link, no thread, and not pinned.

    All four have to hold at once:

    - **Old** (`updated_at` older than the cutoff), a note edited last week
      isn't "forgotten" no matter how disconnected it is.
    - **No link**, in either direction, a linked note is already found
      through whatever it's linked to, whatever its own age.
    - **No thread**: neither a reply (`parent_id` set) nor has any reply of
      its own. A reply is reachable from the note it answers; a note with
      replies is reachable from them.
    - **Not pinned**: pinning is the user already saying "keep this close,"
      which is the opposite of a note this function exists to surface.

    Private notes are included (unlike `duplicates.find_duplicates`,
    ROADMAP.md item 31 asks for notes to be *tagged* here, not their content
    read or shown anywhere), but the caller doing the tagging still has to
    go through `_require_note`/`manager.update_entry` the same as any other
    write to a private note.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = list(
        session.scalars(
            select(Entry).where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.archived_at.is_(None),
                Entry.pinned == False,  # noqa: E712
                Entry.updated_at < cutoff,
            )
        )
    )
    if not entries:
        return []

    ids = {e.id for e in entries}
    linked_ids: set[int] = set()
    for source_id, target_id in session.execute(
        select(EntryLink.source_entry_id, EntryLink.target_entry_id).where(
            EntryLink.source_entry_id.in_(ids) | EntryLink.target_entry_id.in_(ids)
        )
    ):
        linked_ids.add(source_id)
        linked_ids.add(target_id)

    parents_with_replies: set[int] = set(
        session.scalars(
            select(Entry.parent_id).where(
                Entry.parent_id.in_(ids),
                Entry.is_deleted == False,  # noqa: E712
            )
        )
    )

    return [
        entry
        for entry in entries
        if entry.id not in linked_ids
        and entry.id not in parents_with_replies
        and entry.parent_id is None
    ]
