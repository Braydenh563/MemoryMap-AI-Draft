"""One index over every kind (WORLD_CLASS_PLAN B3, SESSION_BRIEFS Brief 11).

Before this, the notebook had one index and five blind spots. `entries_fts`
covers notes, and covers them well (bm25, a porter stemmer, a spelling
vocabulary); a document, a file's extracted text, a bookmark and a reminder
were each found, when they were found at all, by a `LIKE` in whichever route
happened to want them. Searching for a word you know you wrote and getting
nothing because you wrote it in a document rather than a note is the same
failure as having no search at all, and it is the one people report.

So: a second FTS5 table, `search_index`, holding one row per indexed thing,
with the `kind` on the row. The engine (`search/engine.py`) reads it; this
module is the only thing that writes it.

**Why a second table rather than a `kind` column on `entries_fts`**, which is
what Brief 11 first proposed: `entries_fts` is an *external content* table
(`content='entries', content_rowid='id'`), so its rowids are `entries.id` and
its text is read back out of `entries`. Neither can hold a document: document
7 and note 7 would be the same row, and FTS5 would look for a document's text
in the notes table. The `kind` column arrives, as asked, but on a table that
can carry every kind. `entries_fts` stays exactly as it is, still serving
`keyword_search` and still backing the spelling vocabulary; nothing that works
today is rebuilt (CLAUDE.md §1).

**Why the write path hangs off the ORM flush rather than the event log**, which
is Brief 11's other first proposal, revised here with its measurement (the
revision is written into WORLD_CLASS_PLAN's "Decisions made"): the event log
does not see every write. `routes_documents.py` records `created`, `deleted`,
`archived` and `restored`, and records nothing when a document's text is
*edited*, which is the one write a search index most needs to hear about. An
index fed by events would have gone stale on the app's most common document
operation and looked, from the outside, exactly like search being broken. The
SQLAlchemy `after_flush` hook below sees every write to the six mapped classes
regardless of which route, job or script made it, which is the property Brief
7's decorator-plus-driver gave the event log: **a new call site cannot
silently miss out**. The driver shape is kept too: `source_for()` raises on an
unregistered name rather than quietly indexing nothing, so a seventh kind
added to `KINDS` fails `tests/test_search_engine.py` on the spot.

What this deliberately does not do: rebuild on a schedule, or index whiteboard
sketches and objects (a board's cards are notes, and are indexed as notes).
A full rebuild on a large notebook belongs to the job runtime (Brief 9), not
to a request; `rebuild()` is here for the one caller that needs it, a database
that has never had this table.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

logger = logging.getLogger("memorymap.search.index")

#: The kinds the engine can return, and the kinds `kind:` accepts. The spec
#: (`tests/test_search_engine_spec.py`) names exactly these six.
KINDS = ("note", "document", "board", "file", "bookmark", "reminder")

#: The FTS5 table's columns, in order. The first three are indexed (they are
#: what a query matches against); the rest are UNINDEXED, which in FTS5 means
#: "stored and readable, but not searchable": they are filters and payload, and
#: indexing them would let a note about "the file" match `has:file`.
_COLUMNS = (
    "title",
    "body",
    "tags",
    "kind",
    "ref_id",
    "source",
    "space",
    "flags",
    "written",
)

#: bm25 weights for the indexed columns, in column order. A title match is
#: worth four body matches and a tag match two: the same shape, and for the
#: same reason, as `entries_fts`'s own `bm25(entries_fts, 1.0, 4.0)`, where the
#: tag column is weighted over content.
BM25_WEIGHTS = (4.0, 1.0, 2.0)

#: How rowids are shared out between sources. A regular FTS5 table can delete
#: by rowid in O(1) and can only delete by anything else with a full scan, so
#: every row's identity has to *be* its rowid: `slot * SLOT_STRIDE + ref_id`.
#: A stride of a trillion leaves room for a trillion rows per source, which is
#: eleven orders of magnitude more than a personal notebook will ever hold, and
#: keeps the arithmetic readable in a debugger.
SLOT_STRIDE = 1_000_000_000_000


@dataclass(frozen=True)
class Row:
    """One indexable thing, as the index wants it."""

    title: str
    body: str
    tags: str = ""
    space: str = "default"
    #: Space-separated words that `is:` and `has:` can ask about, e.g.
    #: `pinned`, `archived`, `done`. Only what the row itself knows: whether a
    #: note has an attachment is a different table's business and is answered
    #: by the engine over the candidates, not by a join on every save.
    flags: str = ""
    #: ISO date, for `before:`/`after:` without parsing text at query time.
    written: str = ""


@dataclass(frozen=True)
class Source:
    """Where one kind's rows come from.

    `read` is the incremental path (one object that just changed, already in
    memory, so no query); `scan` is the rebuild path. `slot` is permanent: it
    is baked into every rowid this source has ever written, so changing one
    orphans that source's rows. New sources take the next free number.
    """

    name: str
    kind: str
    slot: int
    model: type
    read: Callable[[object], Row | None]
    scan: Callable[[Session], Iterable[tuple[int, Row]]]


_SOURCES: dict[str, Source] = {}
_BY_MODEL: dict[type, list[Source]] = {}


class UnknownSource(KeyError):
    """Asked for a source that was never registered. See `source_for`."""


def register(source: Source) -> Source:
    """Add a source. Called once per kind at import time, below."""
    if source.name in _SOURCES:
        raise ValueError(f"search index source {source.name!r} is registered twice")
    for existing in _SOURCES.values():
        if existing.slot == source.slot:
            raise ValueError(
                f"search index source {source.name!r} reuses slot {source.slot}, "
                f"which belongs to {existing.name!r}: slots are permanent"
            )
    if source.kind not in KINDS:
        raise ValueError(f"search index source {source.name!r} has kind {source.kind!r}, not in KINDS")
    _SOURCES[source.name] = source
    _BY_MODEL.setdefault(source.model, []).append(source)
    return source


def source_for(name: str) -> Source:
    """The source called `name`, or a loud failure.

    The driver shape from `core/events.py`: the point is the day someone adds
    a kind and no source with it. `tests/test_search_engine.py` walks `KINDS`
    through here, so the omission fails the build with a message saying what
    to write, instead of that kind silently never being findable.
    """
    try:
        return _SOURCES[name]
    except KeyError:
        raise UnknownSource(
            f"no search index source named {name!r}: register one in "
            f"src/memorymap/search/index.py (see the note source for the shape)"
        ) from None


def sources() -> tuple[Source, ...]:
    return tuple(_SOURCES.values())


def sources_for_kind(kind: str) -> tuple[Source, ...]:
    return tuple(s for s in _SOURCES.values() if s.kind == kind)


# --- the table ----------------------------------------------------------------


def ensure_table(connection) -> bool:  # noqa: ANN001  # a SQLAlchemy Connection
    """Create `search_index` if it is missing. Returns True when it was made.

    Called from `DatabaseManager.__init__` beside `_ensure_fts5`, the same
    additive convention every other schema change here follows.
    """
    existed = connection.exec_driver_sql(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='search_index'"
    ).scalar()
    if existed:
        return False
    columns = ", ".join(
        column if column in ("title", "body", "tags") else f"{column} UNINDEXED"
        for column in _COLUMNS
    )
    connection.exec_driver_sql(
        f"CREATE VIRTUAL TABLE search_index USING fts5({columns}, tokenize='porter unicode61')"
    )
    return True


def _rowid(source: Source, ref_id: int) -> int:
    return source.slot * SLOT_STRIDE + int(ref_id)


def _write(connection, source: Source, ref_id: int, row: Row | None) -> None:  # noqa: ANN001
    """Replace one row, or remove it when there is nothing to index.

    Delete-then-insert rather than an UPDATE: FTS5 updates are a delete and an
    insert anyway, and one shape covers "changed", "arrived" and "became
    private" without branching.
    """
    rowid = _rowid(source, ref_id)
    connection.exec_driver_sql("DELETE FROM search_index WHERE rowid = ?", (rowid,))
    if row is None:
        return
    connection.exec_driver_sql(
        f"INSERT INTO search_index(rowid, {', '.join(_COLUMNS)}) "
        f"VALUES ({', '.join('?' * (len(_COLUMNS) + 1))})",
        (
            rowid,
            row.title,
            row.body,
            row.tags,
            source.kind,
            int(ref_id),
            source.name,
            row.space,
            row.flags,
            row.written,
        ),
    )


# --- the write path -----------------------------------------------------------


def _table_missing(session: Session) -> bool:
    """True when this database has no `search_index` yet.

    Cached per session: a test that builds a bare `Base.metadata` database
    without `DatabaseManager` has no such table, and a failed write on every
    flush would be both noisy and slow.
    """
    known = session.info.get("memorymap_index_table")
    if known is None:
        known = bool(
            session.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='search_index'")
            ).scalar()
        )
        session.info["memorymap_index_table"] = known
    return not known


@event.listens_for(Session, "after_flush")
def _index_on_flush(session: Session, flush_context) -> None:  # noqa: ANN001
    """Keep the index in step with whatever just changed, in the same
    transaction, from the objects already in memory.

    `after_flush` is the one place that knows the whole of a write: what was
    added, what was changed and what was deleted, with every value final and
    every id assigned. Raw SQL through `session.connection()` rather than the
    ORM: this runs *inside* a flush, so anything that touches the unit of work
    would re-enter it.

    An indexing failure is logged and swallowed. That is a guard, not a
    shrug: the alternative is a note that will not save because its index row
    would not write, and a notebook that refuses to record a thought is worse
    in every way than one whose search is briefly behind. `rebuild()` puts it
    right, and the log line says which row.
    """
    if not (session.new or session.dirty or session.deleted):
        return
    if _table_missing(session):
        return
    work: list[tuple[Source, int, Row | None]] = []
    for obj in list(session.deleted):
        for source in _BY_MODEL.get(type(obj), ()):
            ref_id = getattr(obj, "id", None)
            if ref_id is not None:
                work.append((source, ref_id, None))
    for obj in [*session.new, *session.dirty]:
        for source in _BY_MODEL.get(type(obj), ()):
            ref_id = getattr(obj, "id", None)
            if ref_id is None:
                continue
            try:
                work.append((source, ref_id, source.read(obj)))
            except Exception:  # noqa: BLE001  # see the docstring
                logger.warning("could not index %s %s", source.name, ref_id, exc_info=True)
    if not work:
        return
    connection = session.connection()
    for source, ref_id, row in work:
        try:
            _write(connection, source, ref_id, row)
        except Exception:  # noqa: BLE001  # see the docstring
            logger.warning("could not write index row for %s %s", source.name, ref_id, exc_info=True)


def touch(session: Session, source_name: str, ref_id: int) -> None:
    """Re-index one thing by hand.

    For the writes the ORM cannot see: a bulk `UPDATE`, a raw migration, a
    file whose OCR text was filled in by a job that wrote it with
    `session.execute`. It re-reads the object rather than trusting a caller's
    copy.
    """
    if _table_missing(session):
        return
    source = source_for(source_name)
    obj = session.get(source.model, ref_id)
    row = source.read(obj) if obj is not None else None
    _write(session.connection(), source, ref_id, row)


def rebuild(session: Session, only: str | None = None) -> dict[str, int]:
    """Index everything from scratch. Returns rows written per kind.

    The one caller is a database that has never had the table (a notebook from
    before this existed): `DatabaseManager` runs it once at startup when
    `ensure_table` reports it created the table. On a large notebook this is
    work for the job runtime (Brief 9), never for a request, which is why
    nothing routes to it.
    """
    if _table_missing(session):
        return {}
    connection = session.connection()
    written: dict[str, int] = {kind: 0 for kind in KINDS}
    for source in _SOURCES.values():
        if only and source.name != only:
            continue
        connection.exec_driver_sql(
            "DELETE FROM search_index WHERE rowid >= ? AND rowid < ?",
            (source.slot * SLOT_STRIDE, (source.slot + 1) * SLOT_STRIDE),
        )
        for ref_id, row in source.scan(session):
            _write(connection, source, ref_id, row)
            written[source.kind] += 1
    return written


def counts(session: Session) -> dict[str, int]:
    """How many rows the index holds per kind. Every kind is a key, at zero
    when nothing of that kind exists: "no bookmarks" and "bookmarks are not
    indexed" are different answers and a missing key renders them the same."""
    tally = {kind: 0 for kind in KINDS}
    if _table_missing(session):
        return tally
    rows = session.execute(text("SELECT kind, count(*) FROM search_index GROUP BY kind")).all()
    for kind, count in rows:
        if kind in tally:
            tally[kind] = int(count)
    return tally


# --- the sources --------------------------------------------------------------
#
# One per kind, registered at import. Each `read` takes an object that is
# already in memory and returns the row, or None for "this must not be in the
# index" (deleted, private, a board being read by the note source).


def _first_line(text_value: str | None, limit: int = 120) -> str:
    for line in (text_value or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:limit]
    return ""


def _tagstext(raw: str | None) -> str:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return ""
    return " ".join(str(tag) for tag in parsed) if isinstance(parsed, list) else ""


def _written(value: datetime | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _entry_row(entry, *, want_board: bool) -> Row | None:  # noqa: ANN001
    """A note or a board, from the same table.

    A private note is never indexed, for the reason its ciphertext exists: an
    index of what an encrypted note says is the encryption undone. A binned or
    archived note *is* indexed, with a flag, so the bin stays searchable.
    """
    if entry is None or bool(getattr(entry, "is_private", False)):
        return None
    if bool(getattr(entry, "is_board", False)) != want_board:
        return None
    flags = []
    if getattr(entry, "pinned", False):
        flags.append("pinned")
    if getattr(entry, "is_deleted", False):
        flags.append("deleted")
    if getattr(entry, "archived_at", None):
        flags.append("archived")
    if getattr(entry, "is_draft", False):
        flags.append("draft")
    if getattr(entry, "source_url", None):
        flags.append("clipped")
    content = entry.content or ""
    return Row(
        title=_first_line(content),
        body=content,
        tags=_tagstext(getattr(entry, "tags", "[]")),
        space=getattr(entry, "workspace_id", "default") or "default",
        flags=" ".join(flags),
        written=_written(getattr(entry, "created_at", None)),
    )


def _scan_entries(session: Session, *, want_board: bool) -> Iterator[tuple[int, Row]]:
    from memorymap.core.database import Entry

    for entry in session.scalars(select(Entry).where(Entry.is_private == False)):  # noqa: E712
        row = _entry_row(entry, want_board=want_board)
        if row is not None:
            yield entry.id, row


def _register_all() -> None:
    """Every source, in one place, so adding a kind is one block of code."""
    from memorymap.core.database import (
        Attachment,
        Bookmark,
        Document,
        Entry,
        MediaUpload,
        Reminder,
    )

    register(
        Source(
            name="notes",
            kind="note",
            slot=1,
            model=Entry,
            read=lambda obj: _entry_row(obj, want_board=False),
            scan=lambda session: _scan_entries(session, want_board=False),
        )
    )
    register(
        Source(
            name="boards",
            kind="board",
            slot=2,
            model=Entry,
            read=lambda obj: _entry_row(obj, want_board=True),
            scan=lambda session: _scan_entries(session, want_board=True),
        )
    )
    register(
        Source(
            name="documents",
            kind="document",
            slot=3,
            model=Document,
            read=_document_row,
            scan=lambda session: (
                (doc.id, _document_row(doc)) for doc in session.scalars(select(Document))
            ),
        )
    )
    register(
        Source(
            name="attachments",
            kind="file",
            slot=4,
            model=Attachment,
            read=_attachment_row,
            scan=lambda session: (
                (att.id, _attachment_row(att)) for att in session.scalars(select(Attachment))
            ),
        )
    )
    register(
        Source(
            name="media",
            kind="file",
            slot=5,
            model=MediaUpload,
            read=_media_row,
            scan=lambda session: (
                (media.id, _media_row(media)) for media in session.scalars(select(MediaUpload))
            ),
        )
    )
    register(
        Source(
            name="bookmarks",
            kind="bookmark",
            slot=6,
            model=Bookmark,
            read=_bookmark_row,
            scan=lambda session: (
                (mark.id, _bookmark_row(mark)) for mark in session.scalars(select(Bookmark))
            ),
        )
    )
    register(
        Source(
            name="reminders",
            kind="reminder",
            slot=7,
            model=Reminder,
            read=_reminder_row,
            scan=lambda session: (
                (rem.id, _reminder_row(rem)) for rem in session.scalars(select(Reminder))
            ),
        )
    )


def _document_row(doc) -> Row | None:  # noqa: ANN001
    if doc is None:
        return None
    flags = ["archived"] if getattr(doc, "archived_at", None) else []
    return Row(
        title=doc.title or "",
        body=doc.content or "",
        tags=getattr(doc, "file_type", "") or "",
        space=getattr(doc, "workspace_id", "default") or "default",
        flags=" ".join(flags),
        written=_written(getattr(doc, "created_at", None)),
    )


def _attachment_row(att) -> Row | None:  # noqa: ANN001
    """A file attached to a note: its name and whatever it says.

    The caption, the OCR text and the vision reading are one body rather than
    three columns: a person searching for a word in a scanned page does not
    know or care which extractor found it, and B3's promise is that the file's
    *text* is findable.
    """
    if att is None:
        return None
    parts = [
        getattr(att, "caption", None),
        getattr(att, "ocr_text", None),
        getattr(att, "vision_ocr_text", None),
    ]
    return Row(
        title=att.filename or "",
        body="\n".join(part for part in parts if part),
        tags=getattr(att, "mime", "") or "",
        space=getattr(att, "workspace_id", "default") or "default",
        written=_written(getattr(att, "created_at", None)),
    )


def _media_row(media) -> Row | None:  # noqa: ANN001
    if media is None:
        return None
    parts = [getattr(media, "caption", None), getattr(media, "ocr_text", None)]
    return Row(
        title=getattr(media, "original_name", "") or "",
        body="\n".join(part for part in parts if part),
        space=getattr(media, "workspace_id", "default") or "default",
        written=_written(getattr(media, "created_at", None)),
    )


def _bookmark_row(mark) -> Row | None:  # noqa: ANN001
    if mark is None:
        return None
    flags = ["pinned"] if getattr(mark, "pinned", False) else []
    return Row(
        title=mark.title or mark.url or "",
        body="\n".join(part for part in (mark.url, mark.note) if part),
        tags=getattr(mark, "group_name", "") or "",
        space=getattr(mark, "workspace_id", "default") or "default",
        flags=" ".join(flags),
        written=_written(getattr(mark, "created_at", None)),
    )


def _reminder_row(rem) -> Row | None:  # noqa: ANN001
    if rem is None:
        return None
    flags = ["done"] if getattr(rem, "done", False) else ["open"]
    if getattr(rem, "priority", "") == "high":
        flags.append("urgent")
    return Row(
        title=rem.text or "",
        body=rem.text or "",
        space=getattr(rem, "workspace_id", "default") or "default",
        flags=" ".join(flags),
        written=_written(getattr(rem, "due_at", None)),
    )


_register_all()
