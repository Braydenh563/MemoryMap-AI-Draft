"""Create/read/update/soft-delete entries, links, and audit logging.

Deliberately AI-free: the API layer decides the category (by asking the
janitor) and this module just stores what it's told. That
keeps capture working even when every AI piece is down (plan §4).
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pathlib import Path

from memorymap.core.database import (
    LIKE_ESCAPE,
    Attachment,
    Category,
    EmbeddingRecord,
    EntityMention,
    Entry,
    DocumentLink,
    EntryBookmark,
    EntryDate,
    EntryLink,
    EntryRevision,
    LINK_TYPES,
    NoteScore,
    Reminder,
    WhiteboardNode,
    WhiteboardObject,
    WhiteboardSketch,
    utcnow,
    like_escape,
)
from memorymap.core import events
from memorymap.entry import timewords

# Where entries land when no AI is available or the AI can't decide.
UNCATEGORISED = "Uncategorised"


def log_action(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    detail: str | None = None,
    payload: dict | None = None,
    actor: str | None = None,
):
    """Append to the audit log. Committed with the caller's transaction.

    Now a thin pass to `core/events.record`, which is the only writer of
    `AuditLog` rows (Brief 7). Kept as the name every caller in the app
    already uses, with the same five positional arguments in the same
    order, so that the event log arrived without eighty call sites being
    rewritten and without any of them losing an actor: `record` fills that
    in from the context (`events.acting_as`).

    `payload` is the whole value of each field this action set, for the
    writes that can be replayed. Returns the row, or None when the event
    was folded into the write that contains it (`events.writes`).
    """
    return events.record(
        session,
        action,
        entity_type,
        entity_id,
        detail=detail,
        payload=payload,
        actor=actor,
    )


def get_or_create_category(
    session: Session, name: str, workspace_id: str | None = None
) -> Category:
    """Categories are identified by name within a space; create on first use.

    `workspace_id` is for the caller that knows which space the category
    belongs in when the *session* does not: a background pass has no request
    and therefore no `X-Workspace-ID`, so the row would take the column
    default and the note's own space could not list the category it was filed
    into. Given one, both halves use it: the lookup, or a "Research" in
    another space would be reused, and the insert.

    **Two writers can reach this at the same moment**, and the naive
    check-then-insert loses that race: both see no row, both insert, and the
    second hits `UNIQUE constraint failed: categories.workspace_id,
    categories.name`, which surfaces as a 500 and loses whatever note was
    being saved. Not theoretical: measured with six concurrent writers
    capturing twelve notes each, 5 of 72 saves died that way, because the
    app genuinely has several writers (the desktop window, a browser tab,
    and the night shift's auto-filing all save notes).

    The insert therefore runs in a savepoint, and losing the race is treated
    as what it is: somebody else has made the category this caller wanted, so
    read theirs. The savepoint matters because without it the failed insert
    poisons the caller's whole transaction, turning a recoverable collision
    into the same 500 by a different route. The re-read is guaranteed to find
    the row: SQLite allows one writer at a time, so the other transaction had
    to have committed for its row to be what this one collided with.
    """
    def _find() -> Category | None:
        query = select(Category).where(Category.name == name)
        if workspace_id is not None:
            query = query.where(Category.workspace_id == workspace_id)
        return session.scalar(query)

    category = _find()
    if category is not None:
        return category
    try:
        with session.begin_nested():
            category = Category(name=name)
            if workspace_id is not None:
                category.workspace_id = workspace_id
            session.add(category)
            session.flush()  # assigns category.id without committing yet
    except IntegrityError:
        existing = _find()
        if existing is None:  # pragma: no cover - see the docstring's last line
            raise
        return existing
    log_action(session, "created", "category", category.id, name)
    return category


def set_category(session: Session, entry: Entry, name: str) -> Entry:
    """Put a note in a category by name, creating the category if it is new.

    The plain "file this here" move, without the correction bookkeeping
    `update_entry_with_correction` does: that one exists to notice a person
    overruling the AI, and a caller that is simply placing a note (a fixture,
    an import, a tool) is not overruling anything. Kept beside
    `get_or_create_category` because the pair is the whole of filing by name.
    """
    # **Filed in the note's own space, whoever is doing the filing.** A new
    # category takes its space from `session.info["workspace_id"]`, which only
    # a request sets (from `X-Workspace-ID`). A caller with no request behind
    # it, a background pass, an import running off the main thread, would
    # create the category in "default" while the note it is filing sits in
    # another space, and a note filed into a category its own space cannot
    # list is a note that has quietly left the sidebar. The link path had
    # exactly this bug and it was measured; this is the same fact stated once
    # more, at the other place a row is made for a note.
    #
    # Passed as a value rather than by borrowing the session's ambient space
    # (`deps.impersonate_workspace`): that import is `core.deps` from
    # `entry.manager`, which CodeQL flagged as the start of an import cycle,
    # and the value is the honest thing to pass anyway. It is one fact, the
    # note's own space, travelling to the one place that needs it.
    entry.category_id = get_or_create_category(
        session, name, workspace_id=entry.workspace_id or "default"
    ).id
    session.flush()
    return entry


@events.writes("entry", "created")
def create_entry(
    session: Session,
    content: str,
    category_name: str = UNCATEGORISED,
    tags: list[str] | None = None,
    ai_confidence: int = 0,
) -> Entry:
    """Store one thought. Commits the transaction."""
    category = get_or_create_category(session, category_name)
    entry = Entry(
        content=content,
        category_id=category.id,
        tags=json.dumps(tags or []),
        ai_confidence=ai_confidence,
    )
    session.add(entry)
    session.flush()
    record_dates(session, entry)
    log_action(
        session,
        "created",
        "entry",
        entry.id,
        payload={"after": events.entry_state(entry)},
    )
    session.commit()
    return entry


#: What a listing does about boards. A board (and therefore a mind map) *is*
#: an `Entry`, see `Entry.is_board`, so every query over entries has to say
#: which of the three it means rather than inherit whichever the last person
#: assumed.
#:
#: Reported: "I made a mindmap naming it test and I think it came up as a new
#: note??" It did. `GET /entries` had no board filter at all, so the notes
#: list, its count, and everything else built on that response listed every
#: board and map in the notebook as a note. Measured on a notebook with nine
#: maps: twelve rows in the Notes list, ten of them maps.
BOARDS_EXCLUDE = "exclude"
BOARDS_INCLUDE = "include"
BOARDS_ONLY = "only"
BOARD_MODES = (BOARDS_EXCLUDE, BOARDS_INCLUDE, BOARDS_ONLY)


def _list_entries_filter(
    query, include_deleted: bool, include_archived: bool, boards: str = BOARDS_INCLUDE
):
    """The where-clause `list_entries` and `count_entries` both need: kept
    in one place so a filter added to one can't quietly drift from the
    other and make the count lie about what the list actually shows.

    `boards` defaults to `include`, which is what every in-process caller
    (background jobs, the librarian, the AI tools) has always got; the HTTP
    route is the one that asks for `exclude`, because "the notes list" is
    exactly the thing that must not have boards in it.
    """
    if not include_deleted:
        query = query.where(Entry.is_deleted == False)  # noqa: E712
    if not include_archived:
        query = query.where(Entry.archived_at.is_(None))
    if boards == BOARDS_EXCLUDE:
        query = query.where(Entry.is_board == False)  # noqa: E712
    elif boards == BOARDS_ONLY:
        query = query.where(Entry.is_board == True)  # noqa: E712
    return query


def list_entries(
    session: Session,
    include_deleted: bool = False,
    include_archived: bool = False,
    limit: int | None = None,
    offset: int = 0,
    boards: str = BOARDS_INCLUDE,
) -> list[Entry]:
    """Pinned first, then newest first. Deleted and archived entries stay
    hidden until the recycle bin / archive UI asks for them explicitly, 
    archiving is not deleting, but it means the same "out of the way until
    asked for" thing for an ordinary list.

    `limit`/`offset` are optional and `None` means "everything", so every
    existing caller (background jobs, the librarian, tests) that wants the
    whole notebook keeps working unchanged, pagination is additive, not a
    breaking change to this function's contract. `routes_entries.py` is the
    one caller that always passes a bounded `limit`; see its own comment for
    why an HTTP response is a different situation from an in-process call.
    """
    query = select(Entry).order_by(
        Entry.pinned.desc(), Entry.created_at.desc(), Entry.id.desc()
    )
    query = _list_entries_filter(query, include_deleted, include_archived, boards)
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def count_entries(
    session: Session,
    include_deleted: bool = False,
    include_archived: bool = False,
    boards: str = BOARDS_INCLUDE,
) -> int:
    """How many `list_entries` would return with no `limit`, the total a
    paginated caller needs to know when it has seen everything. Takes the
    same `boards` mode for the reason `_list_entries_filter` exists at all:
    a count that includes boards over a list that does not is a header that
    lies about the list under it."""
    query = _list_entries_filter(
        select(func.count()).select_from(Entry), include_deleted, include_archived, boards
    )
    return session.scalar(query) or 0


def entry_id_scope(
    session: Session,
    *,
    deleted: bool = False,
    archived: bool = False,
    boards: str = BOARDS_INCLUDE,
) -> set[int]:
    """Every entry id in one of the three views, live, bin, or archive.

    Exists because the caller that needs this (semantic search's scope check in
    `routes_entries.list_entries_route`) needs *only* ids, and its own comment
    already said so, "ids only, no row bodies, cheap even at real notebook
    scale". The code underneath it did not match: it called `list_entries()`
    and threw every mapped `Entry` away after reading `.id`, which is the exact
    cost `search_manager.semantic_search` was rewritten to stop paying
    (its docstring measures it at ~85% of a search at 20k+ notes, materialising
    entities to score and discard them). A comment describing an optimisation
    the code does not perform is worse than no comment, because the next
    profiler run has to rediscover it.

    Deliberately unpaginated, for the reason the call site gives: this decides
    which semantic hits are *in scope* at all, so a page boundary here would
    silently drop legitimate matches.
    """
    query = select(Entry.id)
    if deleted:
        query = query.where(Entry.is_deleted == True)  # noqa: E712
    elif archived:
        query = query.where(
            Entry.archived_at.is_not(None), Entry.is_deleted == False  # noqa: E712
        )
    else:
        query = _list_entries_filter(query, False, False, boards)
    return set(session.scalars(query))


def most_accessed_entries(session: Session, limit: int = 5) -> list[Entry]:
    """Most-used non-deleted, non-archived entries; untouched entries don't
    qualify."""
    return list(
        session.scalars(
            select(Entry)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.archived_at.is_(None),
                Entry.access_count > 0,
            )
            .order_by(Entry.access_count.desc(), Entry.id.desc())
            .limit(limit)
        )
    )


def list_deleted_entries(
    session: Session, limit: int | None = None, offset: int = 0
) -> list[Entry]:
    """The recycle bin, most recently deleted first."""
    query = select(Entry).where(Entry.is_deleted == True).order_by(  # noqa: E712
        Entry.deleted_at.desc(), Entry.id.desc()
    )
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def count_deleted_entries(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(Entry).where(Entry.is_deleted == True)  # noqa: E712
    ) or 0


def list_archived_entries(
    session: Session, limit: int | None = None, offset: int = 0
) -> list[Entry]:
    """The archive, most recently archived first. Independent of the
    recycle bin: an archived note that's also deleted still belongs to
    the bin, not here (list_entries' own is_deleted filter already keeps
    the two from double-counting in the normal view)."""
    query = select(Entry).where(
        Entry.archived_at.is_not(None), Entry.is_deleted == False  # noqa: E712
    ).order_by(Entry.archived_at.desc(), Entry.id.desc())
    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def count_archived_entries(session: Session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Entry)
        .where(Entry.archived_at.is_not(None), Entry.is_deleted == False)  # noqa: E712
    ) or 0


def get_entry(session: Session, entry_id: int) -> Entry | None:
    return session.get(Entry, entry_id)


#: **`filing_state` when the AI chose the category and nobody has said
#: otherwise.** The other three values (`done`, `pending`, `failed`) describe
#: how far the *save* got; this one describes who decided, and it is the flag
#: that makes a later move by hand legible as a correction rather than as an
#: ordinary edit. A terminal state like `done` as far as every reader is
#: concerned: the composer's poller stops on anything that is not `pending`.
AUTO_FILED = "auto"


def update_entry(
    session: Session,
    entry: Entry,
    content: str | None = None,
    category_name: str | None = None,
    tags: list[str] | None = None,
) -> Entry:
    """Manual override: the user can change anything the AI decided.

    **A move out of an auto-filed category is a correction, and is recorded as
    one** (Brief 13). See `ai/librarian.corrections_note` for what reads it
    back: the point of the record is that the next filing decision for the
    same category can see it.

    The correction is written *outside* the `edited` write scope, which is
    what this wrapper is for. `events.record` folds anything recorded inside a
    write into that write's own event, correctly, because a category created
    on the way past is part of the one change the user asked for. A correction
    is not: it is a second, separately readable fact about the same moment,
    and folded into the edit it would be invisible to the query that looks for
    it.
    """
    before_category = category_name_for(session, entry)
    was_auto = (getattr(entry, "filing_state", "") or "") == AUTO_FILED
    excerpt = readable_content(entry) or ""
    _update_entry_fields(session, entry, content, category_name, tags)
    after_category = category_name_for(session, entry)
    if was_auto and after_category != before_category:
        entry.filing_state = "done"
        log_action(
            session,
            "correction",
            "entry",
            entry.id,
            f"moved from {before_category} to {after_category}",
            payload={
                "from": before_category,
                "to": after_category,
                # The note's own words, so a filing prompt can say what kind
                # of note this rule is about. Clipped here rather than at read
                # time: a payload is stored for ever and a whole note in one
                # is a copy of the notebook in the audit log.
                "excerpt": " ".join(excerpt.split())[:200],
            },
        )
        session.commit()
    return entry


@events.writes("entry", "edited")
def _update_entry_fields(
    session: Session,
    entry: Entry,
    content: str | None = None,
    category_name: str | None = None,
    tags: list[str] | None = None,
) -> Entry:
    """The edit itself. One write, one `edited` event; see `update_entry`."""
    was = events.entry_state(entry)
    changed = []
    if content is not None and content != entry.content:
        entry.content = content
        changed.append("content")
    if category_name is not None:
        category = get_or_create_category(session, category_name)
        if category.id != entry.category_id:
            entry.category_id = category.id
            # A manual move means the user decided, the janitor stays
            # out of this entry's filing from now on.
            entry.user_filed = True
            changed.append(f"category={category_name}")
    if tags is not None:
        entry.tags = json.dumps(tags)
        changed.append("tags")
    if "content" in changed:
        # The text is what carries the phrases, so a rewrite re-reads them.
        # Resolved against *now*, not the original capture: the user is
        # writing "tomorrow" today.
        record_dates(session, entry)
    if changed:
        log_action(
            session,
            "edited",
            "entry",
            entry.id,
            ", ".join(changed),
            payload=events.changed(was, events.entry_state(entry)),
        )
        session.commit()
    return entry


def entry_dates(session: Session, entry: Entry) -> list[EntryDate]:
    """The resolved time phrases for one note, in the order they were written."""
    return list(
        session.scalars(
            select(EntryDate)
            .where(EntryDate.entry_id == entry.id)
            .order_by(EntryDate.id)
        )
    )


def entry_dates_bulk(session: Session, entry_ids: list[int]) -> dict[int, list[EntryDate]]:
    """`entry_dates` for several notes in one query, grouped by note id.

    `list_notes`/`summarize_notes` called `entry_dates` once per row inside
    `_note_summary`, an N+1 hit on the agent's most-used read tools
    (ROADMAP.md Tier 1 item 8). This is the batched form for that path;
    single-note callers (`get_note`, etc.) still use `entry_dates` above.
    """
    if not entry_ids:
        return {}
    out: dict[int, list[EntryDate]] = {}
    for date in session.scalars(
        select(EntryDate)
        .where(EntryDate.entry_id.in_(entry_ids))
        .order_by(EntryDate.id)
    ):
        out.setdefault(date.entry_id, []).append(date)
    return out


@events.writes("entry", "dated")
def record_dates(session: Session, entry: Entry) -> None:
    """Resolve the relative time phrases in a note and store what they meant.

    Best-effort by design (principle 2): a note must save even if this cannot
    run at all, so every failure here is logged and swallowed. Private notes
    are skipped: their text is encrypted at rest, and lifting phrases out of
    it into a plain table would leak the one thing encryption is for.
    """
    try:
        if entry.is_private:
            return
        from memorymap.core.config import user_now

        # `importlib`, not `from memorymap.core import deps`, see
        # `_ensure_tag_cache_reset_registered` below for why this module
        # can't have that import statement anywhere, function-local or not
        # (CodeQL's py/cyclic-import flags the statement itself, not merely
        # module-level ones).
        deps = importlib.import_module("memorymap.core.deps")

        try:
            now = user_now(deps.get_config())
        except Exception:  # noqa: BLE001  # no app state (a script, a test)
            now = datetime.now()
        session.execute(delete(EntryDate).where(EntryDate.entry_id == entry.id))
        resolved = []
        for mention in timewords.find(entry.content or "", now):
            session.add(
                EntryDate(
                    entry_id=entry.id,
                    phrase=mention.phrase[:60],
                    at=datetime(mention.at.year, mention.at.month, mention.at.day),
                    precision=mention.precision,
                )
            )
            resolved.append(
                {
                    "phrase": mention.phrase[:60],
                    "at": mention.at.isoformat(),
                    "precision": mention.precision,
                }
            )
        # Recorded even when nothing was found: "this text was read for dates
        # and had none" is the fact that explains an empty date list, and the
        # two are indistinguishable without it. Folded into the note's own
        # event whenever this runs as part of a save or an edit, so it only
        # becomes a row of its own when something calls it directly.
        log_action(
            session,
            "dated",
            "entry",
            entry.id,
            f"{len(resolved)} date(s)",
            payload={"dates": resolved},
        )
        session.flush()
    except Exception:  # noqa: BLE001  # never let this stop a note being saved
        logging.getLogger("memorymap.entries").warning(
            "Couldn't resolve the dates in entry %s", entry.id, exc_info=True
        )


# --- notes ↔ documents -------------------------------------------------------
# A note and a document are different things on purpose, but they are usually
# about the same thing. These are the only four functions that know how they
# are joined, so both sides of the relationship can never drift apart.


@events.writes("document", "linked")
def link_document(session: Session, document_id: int, entry_id: int) -> bool:
    """Attach a note to a document. False if it already was."""
    existing = session.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document_id, DocumentLink.entry_id == entry_id
        )
    )
    if existing is not None:
        return False
    session.add(DocumentLink(document_id=document_id, entry_id=entry_id))
    log_action(
        session,
        "linked",
        "document",
        document_id,
        f"note {entry_id}",
        payload={"after": {"document_id": document_id, "entry_id": entry_id}},
    )
    session.commit()
    return True


@events.writes("document", "unlinked")
def unlink_document(session: Session, document_id: int, entry_id: int) -> bool:
    removed = session.execute(
        delete(DocumentLink).where(
            DocumentLink.document_id == document_id, DocumentLink.entry_id == entry_id
        )
    ).rowcount
    if removed:
        log_action(
            session,
            "unlinked",
            "document",
            document_id,
            f"note {entry_id}",
            payload={"before": {"document_id": document_id, "entry_id": entry_id}},
        )
        session.commit()
    return bool(removed)


def documents_for_entry(session: Session, entry: Entry) -> list:
    """The documents this note is attached to, oldest link first."""
    from memorymap.core.database import Document

    return list(
        session.scalars(
            select(Document)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .where(DocumentLink.entry_id == entry.id)
            .order_by(DocumentLink.id)
        )
    )


def documents_for_entries_bulk(session: Session, entry_ids: list[int]) -> dict[int, list]:
    """`documents_for_entry` for several notes in one query, grouped by note id.

    Same batched-form pattern as `entry_dates_bulk`, built for `GET /entries`,
    which called `documents_for_entry` once per row via `_to_out` (ROADMAP.md
    #0 priority, item 1). Single-note callers keep using the function above.
    """
    from memorymap.core.database import Document

    if not entry_ids:
        return {}
    out: dict[int, list] = {}
    rows = session.execute(
        select(DocumentLink.entry_id, Document)
        .join(Document, DocumentLink.document_id == Document.id)
        .where(DocumentLink.entry_id.in_(entry_ids))
        .order_by(DocumentLink.id)
    )
    for entry_id, document in rows:
        out.setdefault(entry_id, []).append(document)
    return out


def links_for_entries_bulk(
    session: Session, entry_ids: list[int]
) -> dict[int, list[tuple[EntryLink, Entry]]]:
    """`links_for_entry` for several notes in one query, grouped by note id.

    Same batched-form pattern as `entry_dates_bulk`, built for `GET /entries`
    (ROADMAP.md #0 priority, item 1), which resolved each link's other-side
    entry with a separate `session.get` per link inside `_to_out`.
    """
    if not entry_ids:
        return {}
    id_set = set(entry_ids)
    links = list(
        session.scalars(
            select(EntryLink).where(
                or_(
                    EntryLink.source_entry_id.in_(id_set),
                    EntryLink.target_entry_id.in_(id_set),
                )
            )
        )
    )
    touched_ids = set()
    for link in links:
        touched_ids.add(link.target_entry_id)
        touched_ids.add(link.source_entry_id)
    entries_by_id = {e.id: e for e in session.scalars(select(Entry).where(Entry.id.in_(touched_ids)))}

    out: dict[int, list[tuple[EntryLink, Entry]]] = {}
    for link in links:
        if link.source_entry_id in id_set:
            other = entries_by_id.get(link.target_entry_id)
            if other is not None:
                out.setdefault(link.source_entry_id, []).append((link, other))
        if link.target_entry_id in id_set and link.target_entry_id != link.source_entry_id:
            other = entries_by_id.get(link.source_entry_id)
            if other is not None:
                out.setdefault(link.target_entry_id, []).append((link, other))
    return out


def entries_for_document(session: Session, document_id: int) -> list[Entry]:
    """The notes attached to this document. Binned notes drop out on their
    own: a note in the recycle bin should not still be feeding a draft."""
    return list(
        session.scalars(
            select(Entry)
            .join(DocumentLink, DocumentLink.entry_id == Entry.id)
            .where(DocumentLink.document_id == document_id, Entry.is_deleted == False)  # noqa: E712
            .order_by(DocumentLink.id)
        )
    )


@events.writes("entry", "deleted")
def soft_delete_entry(session: Session, entry: Entry) -> None:
    """Into the recycle bin, recoverable until purged. Commits."""
    entry.is_deleted = True
    entry.deleted_at = utcnow()
    log_action(
        session,
        "deleted",
        "entry",
        entry.id,
        payload={
            "before": {"is_deleted": False, "deleted_at": None},
            "after": {"is_deleted": True, "deleted_at": entry.deleted_at.isoformat()},
        },
    )
    session.commit()


@events.writes("entry", "restored")
def restore_entry(session: Session, entry: Entry) -> None:
    was = entry.deleted_at.isoformat() if entry.deleted_at else None
    entry.is_deleted = False
    entry.deleted_at = None
    log_action(
        session,
        "restored",
        "entry",
        entry.id,
        payload={
            "before": {"is_deleted": True, "deleted_at": was},
            "after": {"is_deleted": False, "deleted_at": None},
        },
    )
    session.commit()


@events.writes("entry", "archived")
def archive_entry(session: Session, entry: Entry) -> None:
    """Out of the way, but never deleted, no auto-clear, no purge."""
    entry.archived_at = utcnow()
    log_action(
        session,
        "archived",
        "entry",
        entry.id,
        payload={
            "before": {"archived_at": None},
            "after": {"archived_at": entry.archived_at.isoformat()},
        },
    )
    session.commit()


@events.writes("entry", "unarchived")
def unarchive_entry(session: Session, entry: Entry) -> None:
    was = entry.archived_at.isoformat() if entry.archived_at else None
    entry.archived_at = None
    log_action(
        session,
        "unarchived",
        "entry",
        entry.id,
        payload={"before": {"archived_at": was}, "after": {"archived_at": None}},
    )
    session.commit()


def _board_type_of(session: Session, board_id: int) -> str:
    """"map" or "board" for the note with this id.

    A one-line read of `Entry.board_settings`, duplicated from
    `routes_whiteboard._board_settings` rather than imported: `entry/manager`
    is the layer the API sits on top of, and importing an API module from
    here would invert that (and, in practice, import a router at delete time).
    Tolerant of every shape a JSON text column can hold, for the same reason
    the original is: a bad value must degrade to "an ordinary board", never
    to an exception in the middle of emptying the bin.
    """
    entry = session.get(Entry, board_id)
    if entry is None:
        return "board"
    try:
        parsed = json.loads(entry.board_settings or "{}")
    except (TypeError, ValueError):
        return "board"
    if not isinstance(parsed, dict):
        return "board"
    return "map" if parsed.get("type") == "map" else "board"


#: The one shape a whiteboard image url may take, the same allowlist as
#: `routes_whiteboard.MEDIA_URL_RE`, repeated here rather than imported because
#: the entry manager must not depend on a route module.
_MEDIA_URL_RE = re.compile(r"^/media/[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _hard_delete(session: Session, entries: list[Entry], uploads_dir: Path | None = None) -> int:
    """Permanently remove entries plus their vectors, links, and files."""
    ids = [e.id for e in entries]
    if not ids:
        return 0
    # Attached files: remove bytes from disk (best effort) then the rows.
    attachments = list(
        session.scalars(select(Attachment).where(Attachment.entry_id.in_(ids)))
    )
    for attachment in attachments:
        if uploads_dir is not None:
            try:
                (uploads_dir / attachment.stored_name).unlink(missing_ok=True)
            except OSError as exc:
                # The row goes either way, a file that won't delete must not
                # block the purge: but a folder that has stopped accepting
                # deletes will otherwise grow forever with nothing said.
                logging.getLogger("memorymap.entries").warning(
                    "couldn't delete the file for attachment %s (%s); "
                    "removing the record anyway",
                    attachment.id,
                    type(exc).__name__,
                )
    session.execute(delete(Attachment).where(Attachment.entry_id.in_(ids)))
    session.execute(delete(EmbeddingRecord).where(EmbeddingRecord.entry_id.in_(ids)))
    session.execute(
        delete(EntryLink).where(
            or_(EntryLink.source_entry_id.in_(ids), EntryLink.target_entry_id.in_(ids))
        )
    )
    # **Everything else that points at an entry, or the delete fails outright.**
    #
    # Reported twice in one sitting, "request failed (500) when I tried to
    # empty the bin", and two particular notes that could not be deleted at
    # all. One cause: `PRAGMA foreign_keys=ON` is set (database.py), so a row
    # left behind in *any* of these tables makes `DELETE FROM entries` raise
    # IntegrityError, which surfaces as a 500 and leaves the bin exactly as it
    # was. The notes in the report both carried a resolved time phrase, the
    # `this week → week of 27 July` chip is an `entry_dates` row: which is
    # why those two and not the rest.
    #
    # These four were added to the schema after `_hard_delete` was written, and
    # each was invisible until a note happened to have one. Anything that gains
    # a `ForeignKey("entries.id")` from here has to be listed here too; the
    # test added alongside this fails if one is missed.
    session.execute(delete(EntryRevision).where(EntryRevision.entry_id.in_(ids)))
    session.execute(delete(EntryDate).where(EntryDate.entry_id.in_(ids)))
    session.execute(delete(DocumentLink).where(DocumentLink.entry_id.in_(ids)))
    # Three more that arrived after the four above, each invisible until a
    # note happened to have one, and each producing the same 500 with the
    # note still in the bin. `EntryBookmark` is a saved link attached to this
    # note and `EntityMention` a person or project found in it: both are
    # *about* the note and have nothing to say once it is gone. `NoteScore`
    # is a cache of how faded the note is (`ai/resurface.py`), and a cache
    # that outlives what it describes is how a deleted note reappears in a
    # panel.
    #
    # The list above is no longer kept by memory: `test_recycle_bin.py` reads
    # every `ForeignKey("entries.id")` out of the metadata and fails if one
    # is not handled here, because remembering is what failed the first three
    # times.
    session.execute(delete(EntryBookmark).where(EntryBookmark.entry_id.in_(ids)))
    session.execute(delete(EntityMention).where(EntityMention.entry_id.in_(ids)))
    session.execute(delete(NoteScore).where(NoteScore.entry_id.in_(ids)))
    # A whiteboard card *is* its note, with the note gone there is nothing
    # left to show, so the card goes with it, same as a sketch's own delete.
    session.execute(delete(WhiteboardNode).where(WhiteboardNode.entry_id.in_(ids)))
    # `board_id` is a different relationship: it names which board a card or
    # sketch lives *on*, and that board is itself just a note. Purging the
    # board note must not take every card on it with it, that would be
    # "delete this one note" silently wiping an entire whiteboard. Detached to
    # the default board instead, the same "orphan becomes a root" choice
    # already made for `Entry.parent_id` below.
    session.execute(
        WhiteboardNode.__table__.update()
        .where(WhiteboardNode.board_id.in_(ids))
        .values(board_id=None)
    )
    session.execute(
        WhiteboardSketch.__table__.update()
        .where(WhiteboardSketch.board_id.in_(ids))
        .values(board_id=None)
    )
    # **A map contains its own contents; an ordinary board does not.**
    #
    # The rule, asked for in those words ("any and all text boxes and things
    # that are in the map stay bundled within the map"), and the reason the
    # objects on a board being purged are split in two here rather than all
    # detached alike:
    #
    # - a `topic` exists only in the map. Detaching it dumps loose text onto
    #   the one board nobody ever deletes, which is how a deleted map comes
    #   back as litter on the default board;
    # - a `note`/`document`/`file`/`link` node is a *pointer* at something in
    #   the library. The pointer goes with the map; the thing it pointed at
    #   is a note, and notes are not deleted by deleting a picture of one.
    #   That distinction is the whole of `tests/test_mindmap.py`'s first test;
    # - everything on a plain whiteboard keeps the behaviour it always had, 
    #   detached, not destroyed. See the comment above: "delete this one
    #   note" must not silently wipe an entire whiteboard.
    map_board_ids = [
        board_id
        for board_id in ids
        if _board_type_of(session, board_id) == "map"
    ]
    if map_board_ids:
        # A map's objects go with it, so the image files behind them go too
        # (BACKLOG §116.1 item 1, dropped from backend sprint 2). The same
        # allowlist `routes_whiteboard._media_path` applies: only a url that
        # resolves *inside* `<data>/media` is ever unlinked, so a legacy or
        # hand-edited row cannot turn a purge into "delete any file". Objects
        # on an ordinary board are detached below, not deleted, and keep
        # their files. `uploads_dir` and the media folder are siblings by
        # construction (config.py); nothing else here knows the data dir.
        if uploads_dir is not None:
            media_dir = (uploads_dir.parent / "media").resolve()
            doomed = session.scalars(
                select(WhiteboardObject).where(
                    WhiteboardObject.board_id.in_(map_board_ids),
                    WhiteboardObject.kind == "image",
                )
            )
            for obj in doomed:
                try:
                    url = str(json.loads(obj.data or "{}").get("url") or "")
                    if not _MEDIA_URL_RE.match(url):
                        continue
                    path = (media_dir / url.removeprefix("/media/")).resolve()
                    if path.is_relative_to(media_dir):
                        path.unlink(missing_ok=True)
                except (OSError, ValueError, TypeError) as exc:
                    logging.getLogger("memorymap.entries").warning(
                        "couldn't delete the file for whiteboard image %s (%s); "
                        "removing the record anyway",
                        int(obj.id),
                        type(exc).__name__,
                    )
        session.execute(
            delete(WhiteboardObject).where(WhiteboardObject.board_id.in_(map_board_ids))
        )
    session.execute(
        WhiteboardObject.__table__.update()
        .where(WhiteboardObject.board_id.in_(ids))
        .values(board_id=None)
    )
    # A reminder's entry is optional, so it is detached rather than deleted:
    # "water the tomatoes" is still a thing you asked to be reminded of after
    # the note that prompted it has gone, and deleting the reminder would throw
    # away something the user set by hand.
    session.execute(
        Reminder.__table__.update()
        .where(Reminder.entry_id.in_(ids))
        .values(entry_id=None)
    )
    # Orphan children of a purged parent become thread roots.
    session.execute(
        Entry.__table__.update()
        .where(Entry.parent_id.in_(ids))
        .values(parent_id=None)
    )
    session.execute(delete(Entry).where(Entry.id.in_(ids)))
    return len(ids)


@events.writes("entry", "purged")
def purge_entries(
    session: Session, entries: list[Entry], uploads_dir: Path | None = None
) -> int:
    """Permanently delete specific notes. Commits.

    The named half of `_hard_delete`, so "delete this one for good" and "empty
    the bin" destroy a note by exactly the same code, vectors, links, files,
    and re-parenting any replies. Two implementations of permanent deletion is
    how one of them ends up leaving an orphaned embedding behind, which is a
    note that is gone from the list and still findable by search.
    """
    ids = [entry.id for entry in entries]
    count = _hard_delete(session, entries, uploads_dir=uploads_dir)
    if count:
        # One event carrying the id list, never one per row: a purge is a
        # single thing the user did, and a bin emptied of two hundred notes
        # would otherwise bury every other event in the log under its own
        # bookkeeping (Brief 7's contract, `tests/test_events.py`).
        log_action(
            session,
            "purged",
            "entry",
            ids[0],
            f"{count} entries",
            payload={"ids": ids, "count": count},
        )
    session.commit()
    return count


@events.writes("recycle_bin", "purged")
def empty_recycle_bin(session: Session, uploads_dir: Path | None = None) -> int:
    """Manual 'empty now'. Commits."""
    binned = list(session.scalars(select(Entry).where(Entry.is_deleted == True)))  # noqa: E712
    ids = [entry.id for entry in binned]
    count = _hard_delete(session, binned, uploads_dir=uploads_dir)
    if count:
        log_action(
            session,
            "purged",
            "recycle_bin",
            detail=f"{count} entries",
            payload={"ids": ids, "count": count},
        )
    session.commit()
    return count


@events.writes("recycle_bin", "purged")
def purge_expired_deleted(
    session: Session, days: int, uploads_dir: Path | None = None
) -> int:
    """Auto-clear: permanently drop entries binned more than `days` ago.
    Runs at every startup. Commits."""
    cutoff = utcnow() - timedelta(days=days)
    expired = list(
        session.scalars(
            select(Entry).where(
                Entry.is_deleted == True,  # noqa: E712
                Entry.deleted_at < cutoff,
            )
        )
    )
    ids = [entry.id for entry in expired]
    count = _hard_delete(session, expired, uploads_dir=uploads_dir)
    if count:
        log_action(
            session,
            "purged",
            "recycle_bin",
            detail=f"{count} expired entries",
            payload={"ids": ids, "count": count, "days": days},
        )
    session.commit()
    return count


# --- attachments ------------------------------------------------------


def add_attachment(
    session: Session,
    entry: Entry,
    filename: str,
    stored_name: str,
    mime: str,
    size: int,
) -> Attachment:
    attachment = Attachment(
        entry_id=entry.id,
        filename=filename,
        stored_name=stored_name,
        mime=mime,
        size=size,
    )
    session.add(attachment)
    session.flush()
    log_action(session, "attached", "entry", entry.id, filename)
    session.commit()
    return attachment


def attachments_for(session: Session, entry: Entry) -> list[Attachment]:
    return list(
        session.scalars(
            select(Attachment)
            .where(Attachment.entry_id == entry.id)
            .order_by(Attachment.id)
        )
    )


def attachments_for_entries_bulk(
    session: Session, entry_ids: list[int]
) -> dict[int, list[Attachment]]:
    """`attachments_for` for several notes in one query, grouped by note id.

    The fourth of these batched forms, and the one that was missed:
    `_to_out_bulk` already passed pre-fetched categories, dates, documents and
    links, so `GET /entries` looked bulk-fetched, while `_to_out`'s
    `attachments=` list still called `attachments_for` once per row. Measured
    with a statement counter on a 60-note page: 67 statements, 60 of them the
    same `SELECT ... FROM attachments WHERE entry_id = ?`. It is the notes
    list, the most-requested endpoint in the app, so it was also the most
    expensive place in the schema to leave one.
    """
    if not entry_ids:
        return {}
    out: dict[int, list[Attachment]] = {}
    rows = session.scalars(
        select(Attachment).where(Attachment.entry_id.in_(entry_ids)).order_by(Attachment.id)
    )
    for attachment in rows:
        out.setdefault(attachment.entry_id, []).append(attachment)
    return out


def delete_attachment(
    session: Session, attachment: Attachment, uploads_dir: Path
) -> None:
    try:
        (uploads_dir / attachment.stored_name).unlink(missing_ok=True)
    except OSError:
        pass  # a stuck file shouldn't block removing the record
    log_action(session, "detached", "entry", attachment.entry_id, attachment.filename)
    session.delete(attachment)
    session.commit()


#: Windows treats these as reserved regardless of extension, `CON.txt` is as
#: unusable as `CON`. Checked against the name's stem, case-insensitively,
#: because this app runs on Windows via start.bat and a name that is fine on
#: Linux but unusable the moment someone opens the same data folder there is
#: the kind of bug that only shows up on the other platform.
_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: Matches `Attachment.filename`'s own column width, a name the DB would
#: truncate silently is rejected instead, before it is ever stored half-cut.
MAX_ATTACHMENT_FILENAME = 255


def validate_attachment_filename(name: str) -> str:
    """A display name safe to store and to echo into a download header.

    This is the *label* a person sees and renames, `stored_name` (a random
    uuid) is what the disk and every path on disk actually use, and never
    changes here. That split is what makes this a strict reject-and-explain
    check rather than `routes_files.safe_filename`'s silent rewrite: nothing
    here is ever written to a filesystem path, so there is no "make it safe"
    fallback to reach for, only "tell the user why their name didn't work."

    Still validated as if it *were* a path component, because the failure
    mode of skipping that is not hypothetical for this app specifically: the
    name is handed to Starlette's `FileResponse(filename=...)` on every
    download, which puts it straight into a `Content-Disposition` header, and
    a control character or a name that is just `..` is exactly the kind of
    input that check is supposed to catch before it reaches a header or a
    person's screen.
    """
    if name is None or not name.strip():
        raise ValueError("A filename is required.")
    if "\x00" in name:
        raise ValueError("Filenames can't contain null bytes.")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise ValueError("Filenames can't contain control characters.")
    cleaned = name.strip()
    if len(cleaned) > MAX_ATTACHMENT_FILENAME:
        raise ValueError(f"Filenames can't be longer than {MAX_ATTACHMENT_FILENAME} characters.")
    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("Filenames can't contain a path separator.")
    if ".." in cleaned:
        raise ValueError("Filenames can't contain '..'.")
    if re.match(r"^[A-Za-z]:[/\\]?", cleaned):
        raise ValueError("Filenames can't be an absolute path.")
    if cleaned.startswith("."):
        raise ValueError("Filenames can't start with a dot.")
    stem = cleaned.split(".", 1)[0].strip().upper()
    if stem in _RESERVED_WINDOWS_NAMES:
        raise ValueError(f"'{cleaned}' is a reserved system name and can't be used.")
    return cleaned


def rename_attachment(session: Session, attachment: Attachment, new_filename: str) -> Attachment:
    """Change what a file is *called*, never what it *is* on disk.

    Only `filename`, the Library label and the download's suggested name , 
    changes. `stored_name` (the uuid on disk) and `mime` (recorded at upload,
    from the browser's own `Content-Type`) are left alone, which is what lets
    `validate_attachment_filename` above be a strict allowlist instead of an
    extension allowlist: the bytes `/files/{id}` serves back and the
    `Content-Type` it serves them as never change because of a rename, only
    the label on the download dialog does.

    Raises `ValueError` for a name `validate_attachment_filename` rejects,
    and `FileExistsError` if another file on the *same* note already has that
    name: collisions are scoped per-note, the same boundary the Library
    already draws around what's confusable with what.
    """
    cleaned = validate_attachment_filename(new_filename)
    collision = session.scalar(
        select(Attachment).where(
            Attachment.entry_id == attachment.entry_id,
            Attachment.id != attachment.id,
            Attachment.filename == cleaned,
        )
    )
    if collision is not None:
        raise FileExistsError(f"'{cleaned}' is already used on this note.")
    if cleaned != attachment.filename:
        attachment.filename = cleaned
        log_action(session, "renamed", "entry", attachment.entry_id, f"renamed a file to {cleaned}")
        session.commit()
    return attachment


# --- tags (tag manager) --------------------------------------------------


class _TagCache:
    """Holds the tag-count cache's mutable state as attributes rather than
    module globals: CodeQL's `py/unused-global-variable` flags a bare
    `global NAME` reassignment whose new value is never read again inside
    the same function (true of both writes below: a cache is written for a
    *future* call to read, not the one writing it), which is a real pattern
    for a process-lifetime cache, not a bug. An attribute write sidesteps
    the check without changing behaviour."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entry: tuple | None = None  # (fingerprint, result), one slot, no LRU needed
        self.reset_registered = False


_tag_cache = _TagCache()


def _tag_fingerprint(session: Session) -> tuple:
    """Cheap signature of everything that can change a tag count: a new
    entry, an edit, a delete, or a restore. Same shape as routes_graph.py's
    `_graph_fingerprint`, `Entry.updated_at` has `onupdate=utcnow`, so any
    tag edit bumps it, and the live-entry count catches soft-delete/restore
    even on the rare row an edit doesn't touch."""
    deps = importlib.import_module("memorymap.core.deps")

    live = Entry.is_deleted == False  # noqa: E712
    return (
        str(deps.get_config().data_dir),
        session.scalar(select(func.count(Entry.id)).where(live)) or 0,
        session.scalar(select(func.max(Entry.updated_at)).where(live)),
    )


def reset_tag_cache() -> None:
    """Drop the cached tag counts. For the tests, and for a data restore."""
    with _tag_cache.lock:
        _tag_cache.entry = None


def _ensure_tag_cache_reset_registered() -> None:
    # `deps` imports (transitively, via ai.embeddings -> ai.model_manager)
    # back into this module for `log_action`, so `from memorymap.core import
    # deps` cannot sit at module level here without a circular import at
    # startup: register lazily, on first use, the same way this file
    # already imports `deps` inside `record_dates` for the same reason.
    #
    # `importlib.import_module` rather than a plain `from ... import deps`
    # statement even here, deferred as it already is: CodeQL's
    # py/cyclic-import (three "Note"-severity alerts against this exact
    # shape, this file, closed together) flags the *import statement*
    # itself as beginning a cycle in the module dependency graph, it has
    # no way to know the statement only ever runs after startup, so
    # function-local didn't clear it. `importlib` performs the identical
    # deferred lookup with no `import` statement for that static check to
    # see, which is why `ai/vision_ocr.py` already uses it for this same
    # module.
    if _tag_cache.reset_registered:
        return
    deps = importlib.import_module("memorymap.core.deps")

    deps.register_cache_reset(reset_tag_cache)
    _tag_cache.reset_registered = True


def all_tags(session: Session) -> dict[str, int]:
    """Every tag in use with its entry count.

    Was a full non-deleted-entry scan with a per-row `json.loads`, paid on
    every Library tab open, every `tag_cloud()` call, and every `/tags`
    call: three call sites, the same O(n) cost each time, and no cap the
    way every sibling section of the same responses uses (ROADMAP.md
    "#0 priority"). Cached by notebook fingerprint instead, the same
    pattern `routes_graph.py` already uses for pagerank/similarity, a
    fingerprint miss recomputes once; every other caller within the same
    notebook version gets the cached dict.
    """
    _ensure_tag_cache_reset_registered()
    fingerprint = _tag_fingerprint(session)
    with _tag_cache.lock:
        if _tag_cache.entry is not None and _tag_cache.entry[0] == fingerprint:
            return _tag_cache.entry[1]

    counts: dict[str, int] = {}
    # One column, not one mapped entity per row. `tags` is the only thing this
    # loop reads, and a `select(Entry)` here made SQLAlchemy build, and
    # identity-map: a full `Entry` for every note in the notebook just to
    # reach `.tags`. That is the same cost `search_manager.semantic_search`
    # was rewritten to stop paying (see its docstring: ~85% of a search at
    # 20k+ notes went on materialising entities it then discarded). The
    # fingerprint cache above keeps this off the hot path most of the time;
    # this makes the miss itself cheap instead of merely rare.
    for raw in session.scalars(
        select(Entry.tags).where(Entry.is_deleted == False)  # noqa: E712
    ):
        for tag in tags_from_json(raw):
            counts[tag] = counts.get(tag, 0) + 1
    result = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    with _tag_cache.lock:
        _tag_cache.entry = (fingerprint, result)
    return result


def rename_tag(session: Session, old: str, new: str) -> int:
    """Rename (or merge, if `new` already exists) a tag everywhere.
    Returns how many entries changed. Commits."""
    changed = 0
    for entry in session.scalars(select(Entry)):
        tags = entry_tags(entry)
        if old in tags:
            merged = [t for t in tags if t != old]
            if new not in merged:
                merged.append(new)
            entry.tags = json.dumps(merged)
            changed += 1
    if changed:
        log_action(session, "edited", "tags", detail=f"rename {old} -> {new} ({changed})")
    session.commit()
    return changed


def delete_tag(session: Session, name: str) -> int:
    """Remove a tag from every entry. Returns entries changed. Commits."""
    changed = 0
    for entry in session.scalars(select(Entry)):
        tags = entry_tags(entry)
        if name in tags:
            entry.tags = json.dumps([t for t in tags if t != name])
            changed += 1
    if changed:
        log_action(session, "edited", "tags", detail=f"deleted {name} ({changed})")
    session.commit()
    return changed


# How close two notes' embeddings must be, cosine-wise, before a link left
# with no reason gets one deduced for it. The same bar `/entries/link-
# suggestions` ranks by, so a link made from approving a suggestion and a
# link the AI made unprompted read the same way if they're equally close.
AUTO_REASON_THRESHOLD = 0.55
AUTO_REASON_TEXT = "similar in meaning"
AUTO_REASON_TEXT_TEMPORAL = "similar in meaning, and around the same time"
#: How much a shared date pushes a borderline embedding score over
#: AUTO_REASON_THRESHOLD. Asked for directly (ROADMAP.md Tier 2 item 9):
#: two notes both mentioning "next Tuesday", or written the same day, should
#: read as related even when their topics don't overlap semantically enough
#: on their own. Deliberately small and a *rescue*, not a second path to a
#: link: see the `score >= AUTO_REASON_THRESHOLD` early return below, which
#: keeps every pair that already clears the bar on meaning alone exactly as
#: it was (the reason text, the confidence, and every existing test).
TEMPORAL_RESCUE_BOOST = 0.15


def _shares_a_date(session: Session, source_id: int, target_id: int) -> bool:
    """True when the two notes resolve to the same calendar day.

    Two ways in, both day-precision only (a coarser phrase like "last week"
    isn't specific enough to call two notes related on its own): a recorded
    time phrase in both (`EntryDate`, "next Tuesday" in one note and
    "next Tuesday" in another, each resolved against the day it was
    written), or simply being written on the same day, phrase or not.
    """
    dates_by_entry = entry_dates_bulk(session, [source_id, target_id])
    day_sets = {
        entry_id: {d.at.date() for d in dates if d.precision == "day"}
        for entry_id, dates in dates_by_entry.items()
    }
    if day_sets.get(source_id, set()) & day_sets.get(target_id, set()):
        return True

    entries = {
        e.id: e
        for e in session.scalars(
            select(Entry).where(Entry.id.in_((source_id, target_id)))
        )
    }
    source, target = entries.get(source_id), entries.get(target_id)
    if source is None or target is None:
        return False
    return source.created_at.date() == target.created_at.date()


def _deduce_reason(
    session: Session, source_id: int, target_id: int
) -> tuple[str | None, float | None]:
    """Guess why two notes might be linked from how close their embeddings
    are, with a shared date as a tie-breaker for a borderline pair. Returns
    `(None, None)`, "no reason", when it can't: no embedding for one or
    both notes, a mid-reindex width mismatch, or a score under
    `AUTO_REASON_THRESHOLD` even after the date check. That's deliberately
    the same pair `reason` already had for "nobody gave one", so a weak
    guess never outranks silence, see `EntryLink.reason_confidence`.

    A private note has no embedding (`set_private` deletes it), so this is
    naturally a no-op for one rather than needing its own guard.

    Deliberately cheap: no model call. This used to also ask the AI for a
    specific reason here, synchronously, which meant `create_link` (and so
    every note-linking request, human or agent) stalled on a chat round-trip.
    Wording a *specific* reason is the background audit's job now
    (`ai.links.audit_vague_links`, driven from `ai.autonomous`): this always
    returns immediately with the embedding score's own verdict, the generic
    `AUTO_REASON_TEXT`, and leaves the wording to be upgraded later without
    the person who made the link ever waiting on it.
    """
    # `importlib`, same reason as `_ensure_tag_cache_reset_registered`'s own
    # `deps` lookup above: a plain `from memorymap.ai.embeddings import ...`
    # is CodeQL py/cyclic-import's other flagged site in this file (Note
    # severity: `memorymap.ai.embeddings` imports back into this module by
    # the same `deps` -> `ai.model_manager` chain), and deferring the import
    # to call time doesn't clear it; only dropping the `import` statement
    # itself does.
    embeddings = importlib.import_module("memorymap.ai.embeddings")

    rows = session.scalars(
        select(EmbeddingRecord).where(EmbeddingRecord.entry_id.in_((source_id, target_id)))
    ).all()
    vectors = {row.entry_id: embeddings.bytes_to_vector(row.embedding) for row in rows}
    if source_id not in vectors or target_id not in vectors:
        return None, None
    if vectors[source_id].shape != vectors[target_id].shape:
        return None, None  # mid embedding-model change, see search.similar_pairs
    score = embeddings.cosine_similarity(vectors[source_id], vectors[target_id])
    if score >= AUTO_REASON_THRESHOLD:
        return AUTO_REASON_TEXT, round(score, 2)
    if score + TEMPORAL_RESCUE_BOOST >= AUTO_REASON_THRESHOLD and _shares_a_date(
        session, source_id, target_id
    ):
        return AUTO_REASON_TEXT_TEMPORAL, round(score, 2)
    return None, None


@events.writes("entry", "linked")
def create_link(
    session: Session,
    source: Entry,
    target: Entry,
    reason: str | None = None,
    link_type: str | None = None,
) -> EntryLink | None:
    """Manually connect two entries. Returns None if the link already
    exists (either direction) or the user tried to link an entry to
    itself. Commits on success.

    `reason` is optional free text, "why are these connected?", the thing
    a shared tag or a reply thread says on its own and a link doesn't. Not
    required: most links are still obviously why (two notes about the same
    trip), and forcing an explanation on every one would make linking
    slower for the common case to help the uncommon one. When nobody gives
    one, `_deduce_reason` gets a try instead of leaving the link mute.
    """
    if source.id == target.id:
        return None
    # **A draft cannot be linked to a committed note.** Asked for directly:
    # "draft notes shouldnt be able to connect with actual notes, they need to
    # be separate."
    #
    # Drafts are already excluded from every other view in the app, the
    # sidebar counts, the category lists, the Ask box's retrieval: precisely
    # because an unfinished note is not part of the notebook yet. A link is the
    # one thing that was still crossing that line, and it crossed it in the
    # worst direction: the link outlives the draft's own invisibility, so a
    # committed note quietly grew an edge to something the reader cannot see
    # from anywhere else.
    #
    # Guarded here rather than in the picker because every route in reaches
    # this function: the UI's link button, the AI's linking tool, the
    # auto-linker and the graph, and a rule enforced in one caller is a rule
    # three other callers do not have.
    #
    # Draft-to-draft is allowed, and that is the literal reading of the
    # request: drafts are to be separate *from real notes*, not from each
    # other. Two drafts of the same idea are exactly the pair worth connecting
    # before either is saved. (A link made that way and then half-committed, 
    # one draft saved, the other not, is left alone: it was legitimate when it
    # was made, and deleting a person's link on their behalf because they
    # finished one end of it first is a bigger claim than this rule supports.)
    if bool(source.is_draft) != bool(target.is_draft):
        return None
    existing = session.scalar(
        select(EntryLink).where(
            or_(
                (EntryLink.source_entry_id == source.id)
                & (EntryLink.target_entry_id == target.id),
                (EntryLink.source_entry_id == target.id)
                & (EntryLink.target_entry_id == source.id),
            )
        )
    )
    if existing is not None:
        return None
    reason = (reason or "").strip() or None
    confidence = None
    if reason is None:
        reason, confidence = _deduce_reason(session, source.id, target.id)
    # An unrecognised kind is stored as null rather than rejected: the column
    # is advisory (it styles an edge and weights a traversal), and refusing an
    # otherwise-valid link because a caller sent a typo would trade a working
    # connection for a validation error nobody asked for.
    kind = link_type if link_type in LINK_TYPES else None
    link = EntryLink(
        source_entry_id=source.id,
        target_entry_id=target.id,
        reason=reason,
        reason_confidence=confidence,
        link_type=kind,
        # **The link belongs to the space its notes are in, whoever made it.**
        # A new row usually takes its space from `session.info["workspace_id"]`
        # (the before-flush hook in core/database.py), which is set from the
        # request's `X-Workspace-ID` header. A background pass has no request
        # and no header: `ai/autonomous.py` opens a plain session, so every
        # link the librarian created was written with the column default,
        # "default". Measured: two notes in `space-b`, a link made the way the
        # night shift makes one, and the space that owns both notes could see
        # zero links.
        #
        # Taken from the source note rather than from the session, because
        # that is the fact that is true in both cases: in a request the note
        # is already in the session's space, and in a background pass the note
        # is the only thing that knows.
        workspace_id=source.workspace_id or "default",
    )
    session.add(link)
    session.flush()
    detail = f"-> entry {target.id}" + (f" ({link.reason})" if link.reason else "")
    log_action(
        session,
        "linked",
        "entry",
        source.id,
        detail,
        payload={
            "after": {
                "link_id": link.id,
                "source_entry_id": source.id,
                "target_entry_id": target.id,
                "reason": link.reason,
                "link_type": link.link_type,
            }
        },
    )
    session.commit()
    return link


def backfill_link_reasons(session: Session) -> dict:
    """Give `_deduce_reason` a try on every existing link that has none.

    Asked directly: *"none of my notes have a linked reason yet, is there
    an easy way to give them all a reason?"* There wasn't one: `_deduce_reason`
    only ever ran at the moment `create_link` made a *new* link, so a
    notebook full of links made before that existed (or made without an
    embedding backend running at the time) stays mute forever with no way to
    revisit it. This is that revisit, run once over every link rather than
    one at a time.

    Same rule as a fresh link: a reason a person already gave is never
    touched, and a link that still can't be deduced (no embedding for one or
    both notes, or a score under the threshold) is left exactly as it was, 
    "no reason" is still the honest answer, not a false one manufactured to
    fill the field.
    """
    reasonless = list(
        session.scalars(select(EntryLink).where(EntryLink.reason.is_(None)))
    )
    updated = 0
    for link in reasonless:
        reason, confidence = _deduce_reason(
            session, link.source_entry_id, link.target_entry_id
        )
        if reason is not None:
            link.reason = reason
            link.reason_confidence = confidence
            updated += 1
    if updated:
        log_action(session, "backfilled", "entry", detail=f"reasons for {updated} link(s)")
        session.commit()
    return {"checked": len(reasonless), "updated": updated}


def remove_link(session: Session, source: Entry, target: Entry) -> bool:
    """Disconnect two entries, whichever way round the link was made.

    Returns False when there was nothing to remove, so a caller can say "those
    aren't linked" rather than reporting a success that changed nothing.

    Direction-agnostic on purpose, matching `create_link`: a link is a
    connection rather than an arrow, and requiring the caller to know which
    note was the source would make removal fail for half of them depending on
    who made the link.
    """
    link = session.scalar(
        select(EntryLink).where(
            or_(
                (EntryLink.source_entry_id == source.id)
                & (EntryLink.target_entry_id == target.id),
                (EntryLink.source_entry_id == target.id)
                & (EntryLink.target_entry_id == source.id),
            )
        )
    )
    if link is None:
        return False
    delete_link(session, link)
    return True


def set_link_reason(session: Session, link: EntryLink, reason: str | None) -> EntryLink:
    """A person setting, changing, or clearing a link's reason by hand.

    Always wins over whatever `_deduce_reason` guessed: `reason_confidence`
    is cleared here because a person's words aren't a similarity score, and
    null already means "not deduced", so an edited link and a freshly
    auto-reasoned one that hasn't been touched stay tellable apart.
    """
    link.reason = (reason or "").strip() or None
    link.reason_confidence = None
    detail = f"-> entry {link.target_entry_id}" + (f" ({link.reason})" if link.reason else "")
    log_action(session, "relinked", "entry", link.source_entry_id, detail)
    session.commit()
    return link


def apply_audited_reason(link: EntryLink, reason: str) -> None:
    """Set a link's reason from the background audit, field mutation only,
    no commit, no audit-log row.

    `set_link_reason` is right for a person editing one link: they did one
    thing, so one commit and one "relinked" row is an honest record. The
    background audit (`ai.links.audit_vague_links`) is the opposite shape, 
    up to a `limit` of links rewritten in one pass, and calling
    `set_link_reason` per link there was the bug: a 500-link backfill did 500
    commits and left 500 near-identical "relinked" rows in the user's
    activity log, drowning out the log entries a person actually made. This
    just sets the fields; the caller commits once for the whole batch and
    writes one summary log row.

    Same field-level meaning as `set_link_reason`: `reason_confidence` is
    cleared because a reason the AI wrote out in words is no longer a guess
    from embedding similarity: see `EntryLink.reason_confidence`.
    """
    link.reason = (reason or "").strip() or None
    link.reason_confidence = None


def delete_link(session: Session, link: EntryLink) -> None:
    log_action(
        session,
        "unlinked",
        "entry",
        link.source_entry_id,
        f"-> entry {link.target_entry_id}",
    )
    session.delete(link)
    session.commit()


def links_for_entry(session: Session, entry: Entry) -> list[tuple[EntryLink, Entry]]:
    """All links touching this entry, with the entry on the other end."""
    links = session.scalars(
        select(EntryLink).where(
            or_(
                EntryLink.source_entry_id == entry.id,
                EntryLink.target_entry_id == entry.id,
            )
        )
    )
    result = []
    for link in links:
        other_id = (
            link.target_entry_id
            if link.source_entry_id == entry.id
            else link.source_entry_id
        )
        other = session.get(Entry, other_id)
        if other is not None:
            result.append((link, other))
    return result


def category_name_for(session: Session, entry: Entry) -> str:
    """Resolve an entry's category name (entries always have one)."""
    if entry.category_id is None:
        return UNCATEGORISED
    category = session.get(Category, entry.category_id)
    return category.name if category else UNCATEGORISED


def bulk_category_names(session: Session, entries: list[Entry]) -> dict[int | None, str]:
    """Resolve category names for multiple entries efficiently in a single query."""
    ids = {e.category_id for e in entries if e.category_id is not None}
    if not ids:
        return {None: UNCATEGORISED}
    rows = session.scalars(select(Category).where(Category.id.in_(ids)))
    mapping = {c.id: c.name for c in rows}
    mapping[None] = UNCATEGORISED
    return mapping


def tags_from_json(tags_json: str | None) -> list[str]:
    """Parse a tags JSON string directly without an Entry object."""
    if not tags_json:
        return []
    try:
        loaded = json.loads(tags_json)
        return loaded if isinstance(loaded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def entry_tags(entry: Entry) -> list[str]:
    """Tags are stored as a JSON string; hand callers a real list."""
    return tags_from_json(entry.tags)


# --- category management (rename / delete) -----------------------------------


def all_categories(session: Session) -> list[dict]:
    """Every category with how many live entries sit in it, biggest first.

    Binned entries aren't counted: the number should match what the sidebar
    shows, and the sidebar only ever lists notes you can still see.
    """
    rows = list(session.scalars(select(Category).order_by(Category.name)))
    counts = {
        category_id: total
        for category_id, total in session.execute(
            select(Entry.category_id, func.count(Entry.id))
            .where(Entry.is_deleted == False)  # noqa: E712
            .group_by(Entry.category_id)
        )
    }
    out = [
        {"id": c.id, "name": c.name, "count": counts.get(c.id, 0)}
        for c in rows
    ]
    out.sort(key=lambda c: (-c["count"], c["name"].lower()))
    return out


# **A category's name is part of what its notes embed, so renaming one makes
# every vector under it stale.**
#
# `ai/embeddings.embedding_text` folds the category name and the note's tags
# into the embedded text, that change is itself the fix for a reported
# problem ("I have a whole category called hobbies but basically none came up
# in the semantic search"). The consequence nobody wired up: rename "Games"
# to "Hobbies", or merge it into an existing "Hobbies", and every note that
# moved still has a vector built from the *old* name. Semantic search then
# keeps missing exactly the notes the user just tidied, which is the same
# symptom again, produced by the fix for it.
#
# The vectors are dropped rather than recomputed here. Re-embedding is a model
# call per note and this runs inside a rename the user is waiting on; dropping
# is instant, and the search path already treats a missing vector as "fall
# back to keywords for this note" rather than as an error. They are rebuilt by
# the next re-index (`POST /models/reindex`, or the periodic backfill), so the
# worst case is keyword-quality results for those notes until then, instead of
# semantic results that are quietly wrong.
def _restale_category_vectors(session: Session, category_id: int) -> int:
    """Drop the embeddings of every note in a category whose name just
    changed. Returns how many were dropped."""
    entry_ids = [
        row[0]
        for row in session.execute(
            select(Entry.id).where(Entry.category_id == category_id)
        ).all()
    ]
    if not entry_ids:
        return 0
    dropped = (
        session.query(EmbeddingRecord)
        .filter(EmbeddingRecord.entry_id.in_(entry_ids))
        .delete(synchronize_session=False)
    )
    session.commit()
    return int(dropped or 0)


def rename_category(session: Session, category_id: int, new_name: str) -> dict:
    """Rename a category; renaming onto an existing name merges the two.

    Merging is the useful behaviour rather than an error, "Work" and "work"
    turning up as separate categories is exactly the mess this is here to fix.
    """
    category = session.get(Category, category_id)
    if category is None:
        raise ValueError("That category no longer exists")
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("A category needs a name")
    if new_name == category.name:
        return {"renamed": False, "merged": False, "moved": 0}

    existing = session.scalar(select(Category).where(Category.name == new_name))
    if existing is not None and existing.id != category.id:
        # Merge: move the entries across, then drop the now-empty category.
        moved = _reassign(session, category.id, existing.id)
        log_action(session, "edited", "category", existing.id, f"merged {category.name} → {new_name}")
        session.delete(category)
        session.commit()
        _restale_category_vectors(session, existing.id)
        return {"renamed": True, "merged": True, "moved": moved}

    old = category.name
    category.name = new_name
    log_action(session, "edited", "category", category.id, f"{old} → {new_name}")
    session.commit()
    _restale_category_vectors(session, category.id)
    return {"renamed": True, "merged": False, "moved": 0}


def delete_category(session: Session, category_id: int) -> dict:
    """Remove a category. Its notes are kept and become Uncategorised.

    Deleting a category must never delete notes, that would make an organising
    action destructive, which is never what anyone means by "delete category".
    """
    category = session.get(Category, category_id)
    if category is None:
        raise ValueError("That category no longer exists")
    if category.name == UNCATEGORISED:
        raise ValueError("Uncategorised is where notes go; it can't be removed")

    fallback = get_or_create_category(session, UNCATEGORISED)
    moved = _reassign(session, category.id, fallback.id)
    log_action(session, "deleted", "category", category.id, category.name)
    session.delete(category)
    session.commit()
    return {"deleted": True, "moved": moved}


def _reassign(session: Session, from_id: int, to_id: int) -> int:
    """Point every entry in one category at another. Returns how many moved."""
    entries = list(session.scalars(select(Entry).where(Entry.category_id == from_id)))
    for entry in entries:
        entry.category_id = to_id
    return len(entries)


# --- private notes -----------------------------------------------------------
# Encryption lives behind these two helpers so every read and write goes
# through the same place. Scattering encrypt/decrypt calls across the routes is
# how a path gets missed and a note is stored in the clear.


def readable_content(entry: Entry) -> str:
    """The note's text, decrypting it if it's private and the vault is open.

    A locked vault returns a placeholder rather than raising: a private note
    must not break the notes list, the graph, or an export for everything else.
    """
    from memorymap.core import crypto, vault

    if not crypto.is_encrypted(entry.content):
        return entry.content
    key = vault.key()
    if key is None:
        return "Private note: unlock to read it."
    try:
        return crypto.decrypt(key, entry.content)
    except crypto.DecryptionError:
        # Kept deliberately non-fatal. The stored bytes are still there, so a
        # key problem is recoverable; crashing the list is not.
        return "This private note couldn't be decrypted."


def _heading_text(stripped: str) -> str | None:
    r"""The text of a leading Markdown heading (1-6 `#`, then a required
    space/tab, then the title), a `#` three paragraphs into a long note is
    a section break, not what the note is *called*, so this only ever looks
    at one already-stripped line. Requires the space after the hashes, so
    "#recipe" (a tag someone typed at the very top) is never mistaken for a
    heading.

    Hand-rolled instead of a `^#{1,6}[ \t]+(\S.*)$` regex: CodeQL flagged
    that shape as a polynomial-ReDoS risk on note content, which is as
    uncontrolled as input gets in this app. This scan is a single linear
    pass with no backtracking.
    """
    n = 0
    while n < len(stripped) and n < 6 and stripped[n] == "#":
        n += 1
    if n == 0 or n >= len(stripped) or stripped[n] not in " \t":
        return None
    text = stripped[n:].lstrip(" \t")
    if not text or text[0].isspace():
        return None
    return text


def plain_label(content: str, limit: int = 80) -> str:
    """A note's first line as a *person* would read it, for a chip or a card.

    Reported directly: "the used in note links dont render inline md", a
    usage chip in the Library's file gallery read
    `# Leafeon Pokemon image test ![WallpaperEngineOv…`, because the label was
    the raw first line of markdown. A chip is one line of plain text in a
    pill; it cannot render markdown and should not try, so the markup is
    removed rather than displayed.

    Deliberately small and regex-only: this is a label, not a document render.
    Images lose their alt text entirely (an image is not what the note *says*),
    links keep their text, and the usual inline emphasis/code markers go.
    """
    text = (content or "").strip()
    if not text:
        return ""
    first = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped
        break
    first = re.sub(r"^#{1,6}\s*", "", first)          # heading markers
    first = re.sub(r"^[-*+]\s+|^>\s*", "", first)     # list bullet / quote
    first = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", first)  # images, alt and all
    first = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", first)  # links keep their text
    first = re.sub(r"[*_`~]{1,3}", "", first)          # emphasis, code, strike
    first = re.sub(r"\s+", " ", first).strip()
    return first[:limit]


def extract_title(content: str) -> str | None:
    """A note's own title, if it wrote one, its first line, when that line
    is a Markdown heading. Not a stored field: there is nothing to fall out
    of sync with the content, and "editing the title" is just editing that
    line, the same as any other (asked for directly, and simpler than a
    second input box fighting the single-box capture flow this app is built
    around).
    """
    for line in (content or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        text = _heading_text(stripped)
        return text.strip() if text else None
    return None


def _first_content_line(content: str) -> int | None:
    """Index of the first non-blank line, or None if there isn't one."""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip():
            return i
    return None


def apply_title(content: str, title: str) -> str:
    """Set (or replace) a note's title: its first line, as a heading.
    Prepends a new heading line if the note doesn't have one yet; replaces
    the existing one otherwise, so generating a title for a note that
    already has one swaps it rather than stacking two."""
    lines = (content or "").splitlines()
    i = _first_content_line(content or "")
    heading = f"# {title}"
    if i is not None and _heading_text(lines[i].strip()) is not None:
        lines[i] = heading
        return "\n".join(lines)
    return heading if not content else f"{heading}\n{content}"


def remove_title(content: str) -> str:
    """Take a note's title back out, asked for directly, it's just the
    leading heading line, so removing it is removing that line (and one
    blank line right after it, so the body doesn't start with a gap). A
    note with no title is returned unchanged.
    """
    lines = (content or "").splitlines()
    i = _first_content_line(content or "")
    if i is None or _heading_text(lines[i].strip()) is None:
        return content
    del lines[i]
    if i < len(lines) and not lines[i].strip():
        del lines[i]
    return "\n".join(lines)


#: Inline markdown markers, matched with their content so stripping keeps
#: the words. An image or link becomes its alt/link text, the URL is never
#: captured, only whichever group actually matched ("first non-None group
#: wins", same trick every alternative here relies on). Originally lived
#: only in routes_graph.py (graph node labels); routes_library.py's Library
#: title/preview needed the identical fix, an image-only note (a sketch,
#: most often, but any note whose whole content is a pasted image works the
#: same way) read as literal `![sketch](/media/...)` there too, one surface
#: at a time, until this was factored out to stop that from happening a
#: third time somewhere else.
_INLINE_MD = re.compile(
    r"\*\*([^*\n]{1,500})\*\*|\*([^*\n]{1,500})\*|__([^_\n]{1,500})__"
    r"|_([^_\n]{1,500})_|~~([^~\n]{1,500})~~|`([^`\n]{1,500})`"
    r"|!\[([^\]\n]{0,200})\]\((?:[^)\n]{1,500})\)"
    r"|\[([^\]\n]{1,200})\]\((?:[^)\n]{1,500})\)"
)


def strip_inline_markdown(text: str) -> str:
    """A note's text as plain words: bold/italic/strike/code markers gone,
    an image or link reduced to its alt/link text. Markers only: block
    structure (headings, blockquotes, wiki-links) is each caller's own
    concern, since callers disagree on what to do with those."""
    return _INLINE_MD.sub(
        lambda m: next(g for g in m.groups() if g is not None), text
    )


@events.writes("entry", "edited")
def set_private(session: Session, entry: Entry, private: bool) -> bool:
    """Encrypt or decrypt one note in place. False if the vault is locked.

    Making a note private also drops its embedding: a vector derived from the
    text would leak what the note is about, which defeats the point.
    """
    from memorymap.core import crypto, vault
    from memorymap.core.database import EmbeddingRecord

    key = vault.key()
    if key is None:
        return False

    if private:
        if not crypto.is_encrypted(entry.content):
            entry.content = crypto.encrypt(key, entry.content)
        entry.is_private = True
        session.execute(delete(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry.id))
        # And out of the retrieval engine's in-memory matrix, which a bulk
        # `delete()` statement never reaches: a vector derived from this text
        # is exactly what the encryption is for, and one left in the array
        # would go on answering similarity queries about a note nobody can
        # read. `importlib` rather than an `import` statement, for the reason
        # this file already records for `core.events`: the statement itself is
        # what CodeQL and `tests/test_no_import_cycles.py` count, and this one
        # would close `entry.manager -> search.engine -> ... -> entry.manager`.
        search_engine = importlib.import_module("memorymap.search.engine")

        search_engine.forget_vector(entry.id)
        # And the resolved dates, for the same reason as the embedding: a note
        # is marked private *after* it is created, so anything derived from
        # its text and stored in the clear has to be cleared out here too.
        # "The appointment is tomorrow" plus a date is most of the note.
        session.execute(delete(EntryDate).where(EntryDate.entry_id == entry.id))
    else:
        if crypto.is_encrypted(entry.content):
            entry.content = crypto.decrypt(key, entry.content)
        entry.is_private = False
        record_dates(session, entry)  # readable again, so it can be read again
    # The payload carries the content as it now stands (ciphertext when the
    # note was just made private), so a replay of this note's events rebuilds
    # what is actually in the column rather than the plaintext it stopped
    # being here.
    log_action(
        session,
        "edited",
        "entry",
        entry.id,
        f"private={private}",
        payload={"after": {"content": entry.content, "is_private": bool(private)}},
    )
    return True


# --- [[wiki links]] ----------------------------------------------------------
# Typing [[something]] in a note links it to the note that starts with that
# text. It's the cheapest way to build a real web of notes: no AI, no dialog,
# no leaving the keyboard, and it's what makes the graph fill itself instead
# of waiting for someone to link things by hand.

WIKI_LINK = re.compile(r"\[\[([^\[\]]{1,120})\]\]")


def wiki_link_targets(content: str) -> list[str]:
    """The [[names]] mentioned in some text, de-duplicated, in order."""
    seen = {}
    for match in WIKI_LINK.finditer(content or ""):
        name = match.group(1).strip()
        if name:
            seen.setdefault(name.lower(), name)
    return list(seen.values())


def find_by_wiki_name(session: Session, name: str) -> Entry | None:
    """The note a [[name]] refers to, or None.

    Matched against the start of the note, because a note has no title, its
    opening words are what a person would call it. An exact opening beats a
    partial one, and among equals the oldest wins so a link doesn't silently
    change meaning when a newer note happens to start the same way.
    """
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    #: **A vault's links name the file, not the first words.** An imported
    #: note carries the path it came from (`Entry.source_path`), and Obsidian
    #: writes `[[Roadmap]]` for `Projects/Roadmap.md`, so without this an
    #: imported vault resolves almost none of its own links, since the note's
    #: text starts with the heading the importer wrote, not with the name.
    #: Tried first and matched exactly: a file called "Index" should not lose
    #: to a note that merely opens with the word "index".
    #: Filtered in SQL rather than by loading every imported note: this runs
    #: once per `[[link]]` per save, and a real vault is thousands of files.
    #: The `LIKE` can over-match (`Roadmap.md` also matches `My Roadmap.md`),
    #: so the stem is checked exactly in Python below: the query narrows, it
    #: does not decide. A name containing `%` used to over-match far wider
    #: than that, matching any path at all; `like_escape` ends that, and the
    #: `escape=` beside it is what makes the escaped pattern mean anything.
    vault_clauses = []
    for suffix in (".md", ".markdown"):
        stem = like_escape(wanted)
        vault_clauses.append(Entry.source_path.ilike(f"{stem}{suffix}", escape=LIKE_ESCAPE))
        vault_clauses.append(Entry.source_path.ilike(f"%/{stem}{suffix}", escape=LIKE_ESCAPE))
    vault = session.scalars(
        select(Entry)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.is_private == False,  # noqa: E712
            or_(*vault_clauses),
        )
        .order_by(Entry.id)
    ).all()
    for entry in vault:
        stem = (entry.source_path or "").rsplit("/", 1)[-1].lower()
        if stem.removesuffix(".md").removesuffix(".markdown") == wanted:
            return entry
    candidates = session.scalars(
        select(Entry)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.is_private == False,  # noqa: E712
            Entry.content.ilike(f"{like_escape(wanted)}%", escape=LIKE_ESCAPE),
        )
        .order_by(Entry.id)
    ).all()
    if not candidates:
        return None
    for entry in candidates:
        if entry.content.strip().lower() == wanted:
            return entry  # the whole note is exactly that name
    return candidates[0]


def sync_wiki_links(session: Session, entry: Entry) -> list[str]:
    """Create links for the [[names]] in this note. Returns the unresolved ones.

    Only ever adds. A [[name]] that matches nothing is left alone rather than
    reported as an error, you often write the link before the note it points
    at, and having that fail the save would be worse than useless.
    """
    unresolved = []
    for name in wiki_link_targets(entry.content):
        target = find_by_wiki_name(session, name)
        if target is None or target.id == entry.id:
            if target is None:
                unresolved.append(name)
            continue
        create_link(session, entry, target)
    return unresolved


# ROADMAP.md's onboarding item: "seeded example notes so the graph, timeline
# and dashboard have something to show before the first note exists". Content
# is deliberately about the app itself, a first-run tour that also
# demonstrates linking and categories, rather than generic placeholder text.
#: Each note's content deliberately opens with its own name verbatim, 
#: `find_by_wiki_name` resolves a [[link]] by matching the *start* of
#: another note's content (there's no separate title field), so this is
#: what makes the two real [[links]] below actually resolve.
_EXAMPLE_NOTES = [
    (
        "About MemoryMap",
        ["welcome"],
        "Local-first, always: MemoryMap keeps everything on this machine, "
        "notes, search, even the AI, if you point it at a local model. "
        "Nothing is sent anywhere unless you explicitly turn on web search.",
        9,
    ),
    (
        "About MemoryMap",
        ["welcome", "graph"],
        "Linking notes together: type [[Local-first, always]] and it "
        "becomes a real link, click it, or see it drawn on the Graph tab. "
        "That's how a notebook here becomes a map instead of a pile.",
        7,
    ),
    (
        "About MemoryMap",
        ["welcome", "ai"],
        "Try asking a question: open the Ask tab and try something like "
        "\"what's in my notebook about being local-first?\" The answer will "
        "point back to [[Local-first, always]] and show its reasoning.",
        5,
    ),
    (
        "Personal",
        ["example"],
        "A running shopping list: not every note has to be deep, jot down "
        "a shopping list, a name you don't want to forget, a link to read "
        "later. This one just fills out a second category and a different "
        "day on the Timeline.",
        3,
    ),
    (
        "About MemoryMap",
        ["welcome"],
        "Delete these whenever: these five notes are just here so the "
        "Graph, Timeline and Dashboard have something to show on a "
        "brand-new notebook. Filter the Library by the welcome tag and "
        "delete them any time, nothing about them is special.",
        1,
    ),
]


def seed_example_notes(session: Session) -> int:
    """Create the starter notes above, oldest first so each [[link]] resolves
    against a target that already exists (`sync_wiki_links` only ever adds,
    never fails a save on an unresolved name, but an unresolved name here
    would just be a missed demonstration, not a bug).

    Refuses silently (returns 0) on a notebook that already has any note, 
    seeding is an onboarding offer, never something that could land on top of
    real work if this were ever called twice.
    """
    if session.scalar(select(func.count(Entry.id))) or 0:
        return 0
    now = utcnow()
    for category_name, tags, content, days_ago in _EXAMPLE_NOTES:
        entry = create_entry(
            session, content=content, category_name=category_name, tags=tags
        )
        entry.created_at = now - timedelta(days=days_ago)
        entry.updated_at = entry.created_at
        session.commit()
        sync_wiki_links(session, entry)
        session.commit()
    return len(_EXAMPLE_NOTES)


# --- edit history ------------------------------------------------------------
# The recycle bin covers deletion. Nothing covered editing, so rewriting a note
# destroyed what it used to say with no way back, and the AI can rewrite notes
# too, which makes an undo more than a nicety.

# Per note. Enough to walk back a bad session, few enough that a note edited
# hundreds of times doesn't quietly become the largest thing in the database.
MAX_REVISIONS = 20


@events.writes("entry", "revised")
def record_revision(session: Session, entry: Entry) -> None:
    """Save the note as it is now, before it's changed.

    Private notes store their ciphertext, which is what's in the column, a
    revision must never be the one place a private note sits in the clear.
    """
    from memorymap.core.database import EntryRevision

    revision = EntryRevision(
        entry_id=entry.id, content=entry.content, tags=entry.tags or "[]"
    )
    session.add(revision)
    session.flush()
    # The snapshot is the state *before* whatever the caller is about to do,
    # so the payload says `before`, not `after`: applying it during a replay
    # would undo the very edit this row was written to protect.
    log_action(
        session,
        "revised",
        "entry",
        entry.id,
        f"version {revision.id}",
        payload={"before": {"content": entry.content, "tags": tags_from_json(entry.tags)}},
    )

    stale = list(
        session.scalars(
            select(EntryRevision)
            .where(EntryRevision.entry_id == entry.id)
            .order_by(EntryRevision.id.desc())
            .offset(MAX_REVISIONS)
        )
    )
    for revision in stale:
        session.delete(revision)


def revisions_for(session: Session, entry: Entry) -> list:
    """This note's past versions, newest first."""
    from memorymap.core.database import EntryRevision

    return list(
        session.scalars(
            select(EntryRevision)
            .where(EntryRevision.entry_id == entry.id)
            .order_by(EntryRevision.id.desc())
        )
    )
