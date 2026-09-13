"""SQLAlchemy engine, ORM models, and session factory.

The full MVP schema (build plan §5) is created up front, tables the
AI needs later (embeddings, entry_links) are cheap to have from day
one and painful to retrofit.

Schema upgrades: once real user data exists, "delete the db" stops
being acceptable, so DatabaseManager does additive auto-migration, 
any column that exists in the models but not in the on-disk database
is added with ALTER TABLE at startup. Renames/removals would still
need a real migration tool, so don't do those casually.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime as SaDateTime,
    ForeignKey,
    Integer,
    JSON,
    Float,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)


def utcnow() -> datetime:
    """Timezone-aware UTC now (datetime.utcnow is deprecated: plan §4)."""
    return datetime.now(timezone.utc)


#: The character every escaped LIKE pattern in this app declares.
#: A backslash is SQLite's own convention and the one SQLAlchemy passes
#: straight through in `escape=`.
LIKE_ESCAPE = "\\"


def like_escape(text: str) -> str:
    # Raw, because the docstring below quotes `\%` as the pattern a caller
    # ends up with, and a plain docstring makes that an invalid escape
    # sequence: a SyntaxWarning on every import, in a file every module
    # imports.
    r"""User text, made safe to put inside a LIKE pattern.

    `%` and `_` are wildcards in LIKE, and nothing in a search box says so.
    Searching for `100%` matched every row in the table, `a_b` matched `axb`,
    and a tag filter for `50%` returned the whole notebook: not injection (the
    value is still a bound parameter) but a search that quietly answers a
    different question than the one asked. WORLD_CLASS_PLAN section 12, S7,
    which counted the sites.

    The backslash is escaped first, or escaping `%` would double-escape the
    backslash this function itself inserts and `\%` would come out as a
    literal backslash followed by a wildcard.

    **Every caller must also pass `escape=LIKE_ESCAPE`**, because a pattern
    containing `\%` means "a literal percent" only when the statement says
    what the escape character is; without it SQLite reads the backslash as an
    ordinary character and the search finds nothing at all. That pairing is
    what `tests/test_like_escaping.py` checks at every call site, since the
    two halves are in different lines and only one of them is visibly wrong.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DateTime(TypeDecorator):
    """A DateTime that is always UTC, and always says so.

    SQLite has no timezone type, so a plain DateTime column silently drops the
    offset on the way in and hands back a NAIVE datetime on the way out. Every
    value here is UTC, utcnow() and the API both guarantee it, but "naive"
    and "UTC" are not the same claim, and the difference reaches the user:
    FastAPI serialises a naive datetime with no offset, and JavaScript parses a
    timezone-less date-time string as LOCAL time.

    So a reminder due in five minutes came back reading ten hours overdue for a
    user in UTC+10 (user-reported). It was worse than a display bug, because
    the POST response carried the offset (SQLAlchemy returned the object still
    in memory) and only a later read from disk lost it, so it looked right
    until it didn't.

    Attaching UTC on the way out costs nothing and makes every timestamp the
    API emits unambiguous, for every table at once rather than per endpoint.
    """

    impl = SaDateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        # Normalise to UTC before storing, so a caller that passes a local
        # aware datetime doesn't quietly write a different instant.
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Base(DeclarativeBase):
    pass

class Space(Base):
    """A workspace container for entries."""
    __tablename__ = "spaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    icon: Mapped[str] = mapped_column(String, nullable=False, default="ph-circles-four")
    #: Keep this space's contents out of "All spaces".
    #:
    #: Asked for directly: "how do I hide a specific space's notes and
    #: images/documents etc, all the content from the 'all spaces' space if I
    #: wish??" There was no way, `Space` carried only id/name/icon, and
    #: "all" simply switched the workspace filter off, so it showed
    #: everything with no exclusion path at all.
    #:
    #: **A view filter, not a privacy boundary.** The space stays completely
    #: usable when selected directly; this only decides whether its rows join
    #: the everything-view. Anything that must actually be unreadable is what
    #: the private-note vault is for.
    hidden_from_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")



class WorkspaceMixin:
    """Soft separation of notes and data.
    Added to every major model so querying can be scoped globally by workspace."""
    workspace_id: Mapped[str] = mapped_column(String, server_default="default", index=True, default="default")


def workspace_scoped_models() -> tuple[type, ...]:
    """Every mapped class that carries WorkspaceMixin.

    Discovered from the mapper registry instead of hand-listed, so
    delete_space's "reassign every workspace-scoped row to default" pass
    (routes_spaces.py) can't silently skip a model that gets WorkspaceMixin
    added after this list was last updated, a class missed there leaves
    rows pointing at a space id that no longer exists, which reads back as
    data that just vanished.
    """
    return tuple(
        mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, WorkspaceMixin)
    )

@event.listens_for(Session, "do_orm_execute")
def _add_workspace_filter(execute_state):
    # Only filter if the statement is a select() or similar ORM statement
    if execute_state.is_select or execute_state.is_update or execute_state.is_delete:
        workspace_id = execute_state.session.info.get("workspace_id")
        if workspace_id and workspace_id != "all":
            # Add criteria to all entities that have a workspace_id column
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    WorkspaceMixin,
                    lambda cls: cls.workspace_id == workspace_id,
                    include_aliases=True
                )
            )
        elif workspace_id == "all":
            # "All spaces" means every space that has not opted out. A space
            # marked `hidden_from_all` stays fully usable when it is selected
            # directly; it just does not pour its notes, files and boards
            # into the everything-view.
            #
            # The ids are resolved once per request by `get_session` and
            # cached in `session.info` rather than queried here: this handler
            # runs for *every* statement, so a query inside it would both
            # multiply the work and re-enter this same event.
            hidden = execute_state.session.info.get("hidden_workspaces")
            if hidden:
                execute_state.statement = execute_state.statement.options(
                    with_loader_criteria(
                        WorkspaceMixin,
                        lambda cls: cls.workspace_id.notin_(hidden),
                        include_aliases=True
                    )
                )

@event.listens_for(Session, "before_flush")
def _set_workspace(session, flush_context, instances):
    workspace_id = session.info.get("workspace_id")
    if workspace_id and workspace_id != "all":
        for obj in session.new:
            if isinstance(obj, WorkspaceMixin):
                # Ensure we don't overwrite if manually set elsewhere
                if not obj.__dict__.get("workspace_id"):
                    obj.workspace_id = workspace_id

class User(Base):
    """Single-user unlock. One row, bcrypt password hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Vault(Base):
    """The wrapped data key for private notes (one row).

    Only the *wrapped* key is stored. Unwrapping needs the password, so this
    row on its own reveals nothing, which is the whole point of keeping it
    next to the notes it protects.
    """

    __tablename__ = "vault"

    id: Mapped[int] = mapped_column(primary_key=True)
    kdf_salt: Mapped[bytes] = mapped_column(LargeBinary(32))
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Category(Base, WorkspaceMixin):
    """A filing category. **Unique per space, not globally.**

    The `unique=True` this used to carry on `name` alone predates spaces, and
    it made two spaces genuinely unable to coexist: the moment a note in one
    space needed a category another space already had, "Uni", "Work",
    "Ideas", every ordinary name: `get_or_create_category` looked it up
    under the *current* space's filter, found nothing, inserted, and hit a
    global UNIQUE. Reproduced as a **500 on `POST /entries`**: creating a
    note in a second space simply failed, which is as close to "spaces do not
    work" as a bug gets.

    Two categories with the same name in two spaces are two different
    categories, that is the entire point of a space, so the constraint
    moves to the pair. Within one space the old guarantee is unchanged.
    """

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_categories_workspace_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Entry(Base, WorkspaceMixin):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), default=None
    )
    # JSON string array, e.g. '["joke", "dad"]' (plan §5).
    tags: Mapped[str] = mapped_column(Text, default="[]")
    # 0–100. How sure the AI was when it filed this (0 = no AI involved).
    ai_confidence: Mapped[int] = mapped_column(Integer, default=0)
    #: Where this note is in the filing queue: `done` (the only state a note
    #: filed synchronously is ever in), `pending` (saved, category not
    #: decided yet), or `failed` (the background pass raised and gave up, 
    #: the note keeps whatever category it was created with).
    #:
    #: This exists because filing used to be part of *saving*. `POST
    #: /entries` ran `janitor.categorise` inline, which asks a local model,
    #: so the composer sat disabled behind a spinner for as long as that
    #: took: reported as "the making of new notes was slow and annoying...
    #: I feel like the note panels should disappear while filing and
    #: continuing in the backend". A scalar string default so the additive
    #: auto-migrator backfills every existing row to `done`, which is
    #: exactly right: every note written before this column existed was
    #: filed before its POST returned.
    filing_state: Mapped[str] = mapped_column(String(10), default="done")
    #: The note this one turned out to be a near-duplicate of, found by the
    #: same background pass that files it. Only ever set on a deferred save:
    #: a synchronous one still returns its `similar` in the create response,
    #: because it has already paid for the search by then. NULL is the
    #: overwhelmingly common case and means "no duplicate, or not looked for
    #: yet", the two are not worth distinguishing, since a warning nobody
    #: has been shown yet and a warning there is nothing to show lead to
    #: exactly the same UI.
    #:
    #: Not a ForeignKey on purpose: the note it points at can be deleted,
    #: and an advisory pointer going stale must never take a `DELETE` down
    #: with it. `filing_status` resolves it and shrugs when it is gone.
    filing_similar_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Bumped every time this entry is opened or returned by a chat
    # question: feeds the "most used" dashboard.
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    #: **When it was last opened, as opposed to how often.** Reported: "the
    #: opens a note you opened or edited most recently button doesnt update
    #: and just shows my latest note". The dashboard's Continue pill promises
    #: "opened or edited" and could only deliver "edited", because a count
    #: says how many times without saying when, and `updated_at` moves only
    #: when the text changes. Reading an old note is coming back to it, and
    #: that is exactly the case the pill was useless in.
    #:
    #: Null on every row that existed before this column did (the auto-
    #: migrator cannot run `utcnow` in DDL, see this module's own note), which
    #: is the right answer rather than a missing one: an entry nobody has
    #: opened *since the app learned to remember* has no opening to report,
    #: and every reader below falls back to `updated_at` for it.
    last_opened_at: Mapped[datetime | None] = mapped_column(SaDateTime, default=None)
    # Train-of-thought threads: a child continues its parent.
    # (Added by the auto-migrator as a plain column on old DBs, the FK
    # constraint only exists on freshly created databases.)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id"), default=None
    )
    # Pinned entries float to the top of lists and the dashboard.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # True when the USER chose the category (guided mode or a manual
    # move): the janitor then keeps its hands off during re-filing.
    user_filed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
    # Soft delete = recycle bin (adds restore/auto-clear).
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Archive = kept, but out of the way, a third state, distinct from the
    # recycle bin: archiving never counts as deleting, so it's excluded from
    # normal listings the same way a binned note is, but nothing about it is
    # bound for auto-clear or purge. Null means "not archived"; the timestamp
    # itself (not a separate boolean) is the flag, same pattern as
    # deleted_at above (BACKLOG §4 item 3 / §26, ROADMAP Tier 3 §30b).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # Private notes have their content encrypted at rest. Scalar default so
    # the additive auto-migrator backfills every existing row as not-private.
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # ROADMAP.md item 34. Null means "never scanned"; set (even with zero
    # entities found) after a pass, so a note that genuinely mentions none
    # isn't rescanned by every autonomous pass forever. A plain timestamp
    # rather than a boolean so a future re-scan policy ("older than 30
    # days") has something to compare against without a second column.
    entities_extracted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # A note captured quickly, from a text-selection popup, say, and not
    # yet looked at properly. Shown normally everywhere (unlike is_private,
    # this changes nothing about how the note reads or where it appears),
    # just flagged, so nothing captured on the fly gets lost in the list
    # before its author comes back to it. Scalar default so the additive
    # auto-migrator backfills every existing row as not-a-draft.
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where a clipped web-reader highlight came from (BACKLOG §65's
    # "reader-mode capture", the Kortex/Eden read's item 6). Real metadata
    # now, not just a link folded into `content`: `saveSelectionAsNote`
    # (app.js) still writes the same markdown blockquote-plus-link into the
    # body too: a note is fundamentally plain markdown and must stay
    # readable/exportable with no app behind it, but a queryable column is
    # what lets a note card show a real "from the web" badge, or a future
    # "show me everything I clipped from this site" filter, without parsing
    # markdown to find out. Null means "not a clipping", same convention as
    # every other optional column here.
    source_url: Mapped[str | None] = mapped_column(String(2000), default=None)
    source_title: Mapped[str | None] = mapped_column(String(300), default=None)
    # A note that has ever been used as a whiteboard, created as one via
    # "+ New board", or drawn on directly (routes_whiteboard.py's own
    # "a board is just a note" design). Reported live: a board vanished from
    # the "Switch board" list the moment its last card/sketch/object was
    # removed, which read exactly like the board itself had been deleted, 
    # it hadn't; list_boards() only ever listed notes with a *current*
    # nonzero node/sketch/object count, so a freshly created empty board, or
    # one cleared back to empty mid-edit, dropped out of the only UI that
    # could find it again. Scalar default so the additive auto-migrator
    # backfills every existing row as not-a-board; an already-drawn-on note
    # stays visible regardless (its counts are still nonzero), so nothing
    # already in someone's board list disappears from this change.
    is_board: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Board-level settings, as a small JSON object, for a note being used as
    #: a board: `{"type": "board"|"map", "layout": "free"|"tree-right"|
    #: "tree-down"|"radial"}`. NULL: the overwhelmingly common case, since
    #: almost no note is a board, means "every default", never "unknown", so
    #: the auto-migrator's own NULL backfill leaves every existing board
    #: reading exactly as it did before this column existed: a free-layout
    #: whiteboard.
    #:
    #: **One JSON column rather than a column per setting**, and rather than a
    #: `board_settings` table (MINDMAP_PLAN.md §4, option B: "a `type` and a
    #: `layout` on the existing board entry"). `entries` is the notebook's
    #: widest and busiest table, and board-level settings are a family that
    #: keeps growing, type, layout, a default node colour, tidy-on-drop , 
    #: none of which any *note* has any use for. Two more booleans on every
    #: row of `entries` to describe the handful of rows that are boards is the
    #: wrong shape; a table with one row per board, joined on every list, is
    #: the wrong shape in the other direction. `WhiteboardObject.kind` is this
    #: file's own precedent for not adding structure per idea.
    #:
    #: Nothing queries *inside* it in SQL: `list_boards` already materialises
    #: every board to build its preview, so the `?type=map` filter reads this
    #: in Python over a list that is tens of rows long, not thousands.
    board_settings: Mapped[str | None] = mapped_column(Text, default=None)
    #: Where this note came from in an imported vault, a **relative** path
    #: like `Projects/Roadmap.md`, empty for everything written in this app.
    #:
    #: Asked for directly: *"kortex and obsidian files and md file trees and
    #: being able to link notes and obsidian md files and stuff is I think the
    #: largest gap that is missing right now."* The importer already read a
    #: whole vault, and threw its shape away: every file landed as a flat note
    #: with the folders gone and the **filename gone with them**. That second
    #: loss is the one that matters, because Obsidian's `[[wiki links]] name
    #: the file*, so a vault imported here arrived with every internal link
    #: pointing at nothing.
    #:
    #: A relative path, never an absolute one: it is a *structure*, not a
    #: location on the machine that happened to do the import, and storing
    #: someone's home directory in a notebook that syncs nowhere is a leak
    #: with no upside. A scalar `""` default so the additive auto-migrator
    #: backfills existing rows: "written here", which is what they all are.
    source_path: Mapped[str] = mapped_column(String(500), default="")
    # ROADMAP §87.1's own audit: "double-click pin exists but is never
    # persisted", a node held in place with a double-click on the Graph
    # tab (`d.fx`/`d.fy` in graph.js) only ever lived on the in-memory D3
    # node object, gone the moment `/graph` was refetched. Both null or
    # both set, never one alone (`routes_graph.py`'s own setter enforces
    # this): a lone x with no y is a coordinate nobody asked for. Distinct
    # names from `pinned` above on purpose: that one means "float to the
    # top of lists", this means "hold still at this point on the map", 
    # unrelated concepts that happen to share the English word.
    graph_pin_x: Mapped[float | None] = mapped_column(Float, default=None)
    graph_pin_y: Mapped[float | None] = mapped_column(Float, default=None)


class Entity(Base):
    """A person/project/thing worth naming, independent of any one note.

    ROADMAP.md item 34: every edge in the graph used to connect two whole
    notes; a name mentioned in passing across a dozen notes was a dozen
    separate matches, not one thing with a dozen mentions. Deliberately
    smaller than a full ontology, no entity-to-entity graph, no type
    system beyond the free-text `name` a local model already extracted.
    Membership (`EntityMention`) is the only edge kind, on purpose (see
    `ai/entities.py`).
    """

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not unique at the DB level: two different models/passes proposing
    # "Sarah" for two actually-different Sarahs is a real ambiguity this
    # MVP doesn't try to resolve, matching the roadmap item's own explicit
    # scope cut. `entities.py` still merges exact, case-folded name matches
    # within one pass so the same note doesn't create the same entity twice.
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntityMention(Base):
    """One note mentioning one entity, membership, not a graph edge kind."""

    __tablename__ = "entity_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntryLink(Base, WorkspaceMixin):
    """A user- or AI-made connection between two entries."""

    __tablename__ = "entry_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    target_entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Optional, free text: "why are these connected?" A shared tag or a
    # reply thread says why on its own; a manual or AI-made link often
    # doesn't ("a note about uni and gym might still be related if they're
    # both about scheduling", user-reported). Nullable rather than an empty
    # string default so "no reason given" and "reason is blank" aren't the
    # same row on old links backfilled by the auto-migrator.
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    # How sure `create_link` was of a reason it deduced itself, 0..1, set
    # only when the reason above came from embedding similarity rather than
    # from a person or the AI saying it in words. A human- or model-given
    # reason is taken at face value and leaves this null; null also means
    # "nothing could be deduced", which is deliberately indistinguishable
    # from "nobody tried", both display as no reason at all.
    reason_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    # What *kind* of connection this is, from LINK_TYPES below, or null,
    # which is what every link created before this column existed carries and
    # means exactly what a link has always meant: "these are related".
    #
    # Nullable and additive on purpose: the auto-migrator can ADD COLUMN and
    # nothing else (see this module's own header), so a default of null is the
    # only shape that leaves an existing notebook's links valid and unchanged.
    #
    # A closed vocabulary rather than free text, because three things read it, 
    # the graph styles edges by it, the traversal weights them by it, and the
    # model has to choose one, and none of those can do their job against an
    # open set of synonyms. The free-text half of "why" already exists and is
    # `reason` above; this is the part that has to be machine-readable.
    link_type: Mapped[str | None] = mapped_column(String(24), default=None)


#: The kinds of connection a link can carry, and what each one means.
#:
#: `contradicts` is the one worth having built this for: a notebook that can
#: show you where you disagreed with yourself is not something an embedding
#: similarity score can ever produce, however well tuned.
LINK_TYPES: dict[str, str] = {
    "related": "Related: these belong together",
    "continues": "Continues: this carries on from that",
    "context": "Extra context: this explains or supports that",
    "supports": "Supports: this is evidence for that",
    "contradicts": "Contradicts: these disagree",
    "example_of": "Example of: this is an instance of that",
}

# ROADMAP §87.5's first slice, using only what a link already stores, no new
# column, no migration. A named type is a considered choice (a person or the
# AI, with approval) and reads as a stronger connection than a bare link,
# which is why every one of the six above gets the same boost regardless of
# which: the distinction that matters here is "somebody decided this" versus
# "nobody said", not a ranking between "supports" and "contradicts", those
# are equally deliberate.
TYPED_LINK_BOOST = 1.5

# A floor, not a zero: `reason_confidence` only exists on a reason nobody
# actually gave (see the column's own docstring): it is a guess, and a
# low-confidence guess should weigh less, but even a 10%-confidence deduction
# is still a real signal, not nothing.
DEDUCED_LINK_FLOOR = 0.5


def link_strength(link_type: str | None, reason_confidence: float | None) -> float:
    """One number for how strong an `EntryLink` is. 1.0 is the baseline, a
    bare link with no type and no deduced-reason confidence, which is what
    every link created before either column existed still is.

    Consumed by `entry/paths.py`'s shortest-path weighting (as a divisor: 
    strength up, cost down) and `search_manager.graph_expansion()`'s
    neighbour ordering (as a sort key, strength up, ranked first), so a
    typed or well-evidenced connection is preferred over a bare one in both
    the places that already claimed to do this and did not.

    Deliberately **not** the full composite §87.5 scopes (shared tags,
    category, temporal proximity): those are derived signals that would
    need computing per-pair at query time on two hot paths (every chat/ask
    retrieval goes through `graph_expansion`), and neither has been measured
    against real usage yet. This uses only what a link already carries.
    """
    strength = TYPED_LINK_BOOST if link_type else 1.0
    if reason_confidence is not None:
        strength *= max(DEDUCED_LINK_FLOOR, reason_confidence)
    return strength


class EmbeddingRecord(Base):
    """One vector per entry, stored as raw float32 bytes, never pickle
    (plan §4). model_version + dim let us detect stale vectors after an
    embedding-backend switch (plan §6.5)."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), unique=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    dim: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Attachment(Base, WorkspaceMixin):
    """A file the user attached to an entry. The bytes live in
    the uploads/ folder under a random stored_name; the original
    filename is kept for downloads."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: What this file *says*, so the AI and the Library can both read it.
    #:
    #: Asked for directly: "the files tab needs vision model and ocr model
    #: caption and text extraction. especially for documents containing
    #: diagrams, images, data or scanned pdfs… the text and analysis needs to
    #: be accessible to the ai models and modifyable by the user."
    #:
    #: `MediaUpload` has carried these four since captioning existed; an
    #: `Attachment`, which is what a file dropped onto a *note* actually is
    #:, carried none of them, so a scanned PDF attached to a note was, to
    #: this app, a filename and some bytes. Same columns, same never-
    #: distinguished NULL convention ("not run yet, or found nothing"), and
    #: the same "a person may overwrite any of it" rule; added by the
    #: additive auto-migrator on existing databases like every other
    #: backfilled column here.
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    caption_model: Mapped[str | None] = mapped_column(String(200), default=None)
    caption_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Local Tesseract text for an image, or the extracted/converted text of
    #: a document (`core/docview.py`), one column either way, because what
    #: a reader wants is "the text in this file", not which extractor found it.
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    #: A vision model reading the pages, for the case Tesseract cannot serve:
    #: handwriting, low contrast, a diagram whose meaning is in its layout.
    vision_ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    vision_ocr_model: Mapped[str | None] = mapped_column(String(200), default=None)


class Conversation(Base, WorkspaceMixin):
    """A saved chat. Turns are a JSON list of
    {"role": "user"|"assistant", "content": str, "thinking": str|None}
    - one blob per conversation is the boring right size for a
    single-user app.

    Was missing WorkspaceMixin entirely, reported directly: the Library
    showed every chat regardless of which space was active, while notes and
    documents (which do carry it) correctly scoped to zero. Chat history is
    named explicitly as space-specific in the spaces design notes; this was
    the one model that shipped without the mixin the feature depends on.
    Existing rows get `workspace_id="default"` from the additive
    auto-migrator's column default, same as every other backfilled column
    on this table."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    messages: Mapped[str] = mapped_column(Text, default="[]")
    # Pinned chats sort above the rest. The list is flat and grows forever,
    # so the thread you keep coming back to sinks under a week of one-offs.
    # (Added by the auto-migrator on existing databases, defaulting to false.)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Kept, but out of the way, same shape as Entry.archived_at (BACKLOG
    # §30b), extended here to chats as that item's own named remaining
    # scope. Never implies deletion; added by the auto-migrator, defaulting
    # to NULL (not archived) on every existing row.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class AskTurn(Base, WorkspaceMixin):
    """One question asked in the Ask box (Notes tab), with its answer and
    which notes answered it, durable so the box can be browsed back through
    like the notes it's about, not just re-asked from a five-item chip row.

    Deliberately not a Conversation: the Ask box is single-shot, notes-only
    Q&A (§35A) with no follow-up thread, so a flat row per question beats a
    JSON message list a saved chat needs. `raw_result_ids` records which
    notes answered it at the time, resolved back to live entries on read
    (routes_ask_history.py), so an edited or deleted note since then shows
    as it is now, or drops out cleanly rather than serving a stale copy.
    """

    __tablename__ = "ask_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    raw_result_ids: Mapped[str] = mapped_column(Text, default="[]")
    search_mode: Mapped[str] = mapped_column(String(40), default="")
    when_phrase: Mapped[str] = mapped_column(String(120), default="")
    # Same provenance the live Ask box shows as a badge on each result
    # (similarity score, matched keyword(s), or "linked to a match"), kept
    # so browsing back through history shows the same explanation the
    # answer originally had, not results with no reason attached.
    match_info: Mapped[str] = mapped_column(Text, default="{}")
    connected_ids: Mapped[str] = mapped_column(Text, default="[]")
    # Pinned turns survive "clear history" and sort first: the same shape
    # Conversation.pinned already uses for saved chats.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Bookmark(Base, WorkspaceMixin):
    """A saved link to somewhere outside the notebook.

    Notes and documents already link to *each other* ([[wiki links]],
    EntryLink): nothing held a link to the open web, which is what "an area
    where the user can store lists of links... bookmark commonly visited or
    favourite websites" (§30, directly requested) actually needs. Deliberately
    its own small table rather than bolted onto Entry: a bookmark has no
    body text to search or file, and forcing it through the note pipeline
    (auto-categorisation, embeddings, the recycle bin) would be solving a
    problem this doesn't have."""

    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Free text, not a foreign key to a real folder table: asked for directly
    # ("should they be groupable... make sections and groups"), but a full
    # nested-folder model is a lot of new machinery (a tree table, drag-to-
    # move UI) for what a flat field mostly already buys. "Work/Reading"
    # (a "/" convention, the frontend's to render, not this column's to
    # enforce) gets most of real folders' value: grouping *and* a visual
    # hierarchy: without a second data model. Scalar default so the
    # additive auto-migrator backfills existing rows to "" (ungrouped).
    group_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntryBookmark(Base):
    """A note referencing a saved bookmark, so it shows up in that note's
    own References alongside its [[wiki links]] to other notes (asked for
    directly: "attach a bookmark to a note... show up in References").

    A plain join row, not folded into EntryLink: EntryLink connects two
    Entries, and a Bookmark is deliberately not an Entry (see Bookmark's own
    docstring): reusing that table would mean either a nullable
    target-kind column on every existing link row, or a fake Entry made
    just to hold a URL. Its own tiny table costs nothing and touches
    nothing already working."""

    __tablename__ = "entry_bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    bookmark_id: Mapped[int] = mapped_column(ForeignKey("bookmarks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentBookmark(Base):
    """The same reference as EntryBookmark, for a Document instead of a note
    (asked about directly: "should bookmarks show in documents... as well?").
    Its own table rather than a nullable entry_id/document_id pair on one
    table: Document and Entry are already deliberately separate (see
    Document's own docstring), so a single join table would need to know
    which foreign key was live on any given row."""

    __tablename__ = "document_bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    bookmark_id: Mapped[int] = mapped_column(ForeignKey("bookmarks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Reminder(Base, WorkspaceMixin):
    """A reminder, optionally attached to an entry."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"), default=None)
    text: Mapped[str] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Scalar defaults so the additive auto-migrator backfills existing rows.
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low|normal|high
    recurring: Mapped[str] = mapped_column(String(10), default="none")  # none|daily|weekly|monthly
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NoteScore(Base, WorkspaceMixin):
    """How faded one note is, computed nightly rather than per request.

    Resurfacing (WORLD_CLASS_PLAN 15, I4) shows three notes a day that are
    slipping out of reach: old, unlinked, unopened. Working that out means
    counting links and reads for every note in the notebook, which is a scan
    nobody should pay for while waiting for a page to paint, and it barely
    changes between one day and the next. So it is a stored number, refreshed
    by `ai/resurface.compute_scores`, and the request-time step is a sort plus
    a cosine against whatever the person is looking at now.

    One row per note, replaced rather than appended: this is a cache of a
    derivable fact, not a history. `AuditLog` is where history lives.
    """

    __tablename__ = "note_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), unique=True)
    #: 0 to 1, higher means more faded. The parts are kept beside it because a
    #: score nobody can explain is a score nobody will trust: the panel can say
    #: "you wrote this 120 days ago, it links to nothing, and you have not
    #: opened it" instead of "0.82".
    score: Mapped[float] = mapped_column(Float, default=0.0)
    age_days: Mapped[int] = mapped_column(Integer, default=0)
    link_count: Mapped[int] = mapped_column(Integer, default=0)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntryRevision(Base):
    """A note's text as it was before an edit.

    The recycle bin covers deletion; nothing covered editing, so rewriting a
    note destroyed what it used to say with no way back. Revisions are written
    before the change lands, so the newest one is always the version being
    replaced.
    """

    __tablename__ = "entry_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EntryDate(Base):
    """What a relative time phrase in a note meant, on the day it was written.

    "Tomorrow" is correct when it is typed and misleading forever afterwards,
    and nothing recorded what it resolved to (roadmap §10A). The phrase is
    kept alongside the date deliberately: the resolution is a rule, not a
    fact, and a reader can only disagree with it if they can see both.

    `precision` says how exact the phrase was, "last week" did not mean a
    day, and rendering it as one would invent precision the writer never used.
    """

    __tablename__ = "entry_dates"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), index=True)
    phrase: Mapped[str] = mapped_column(String(60))
    at: Mapped[datetime] = mapped_column(DateTime)
    precision: Mapped[str] = mapped_column(String(10), default="day")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base, WorkspaceMixin):
    """A long-form document (the editor tab).

    Kept separate from Entry on purpose. A note is a captured thought, short,
    auto-categorised, embedded for semantic search, and surfaced by the AI. A
    document is something you sit down and write. Sharing one table would mean
    every half-written document turning up in search results and in the graph.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="Untitled")
    content: Mapped[str] = mapped_column(Text, default="")
    # What kind of file this is, a bare extension, no dot ("md", "py",
    # "sql"). See core/filetypes.py for the table and why it is shared with
    # the frontend rather than duplicated there. A scalar default (not a
    # server_default or a callable) so the additive auto-migrator backfills
    # every document that existed before file types did as markdown, which is
    # what all of them are.
    file_type: Mapped[str] = mapped_column(String(20), default="md")
    # Same "kept, out of the way" column as Entry.archived_at/
    # Conversation.archived_at (BACKLOG §30b): never implies deletion.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentLink(Base):
    """A note attached to a document.

    Notes and documents are deliberately different things, a note is a
    captured thought, a document is something you sat down and write, but
    they are usually *about* the same thing, and until now there was no way to
    say so. Asked for directly: "I want a way to link documents to new notes I
    create in the capture tab; the documents and notes sections need to be
    more integrated."

    Its own table rather than a column on either side: the relationship is
    many-to-many (a document draws on several notes; a note can feed several
    documents), and neither side owns the other.
    """

    __tablename__ = "document_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentAiEdit(Base):
    """One accepted AI edit on a document, a changelog, asked for
    directly: "allow edits made by the AI to be undone or altered before
    and after they are set." Before acceptance, the AI panel's own result
    textarea already covers "altered before" (edit the suggestion, then
    accept whatever you kept). This table covers "undone... after": a
    durable, per-document history of what the AI actually applied, each
    entry revertible on its own, distinct from the app's session-only
    global undo stack (app.js's pushUndo), which still also fires on
    accept for an immediate Ctrl+Z, but forgets everything on reload. This
    is the record that survives one.

    Stores full before/after snapshots rather than a diff: documents are
    markdown text, not the kind of structured data a real diff format
    would represent as anything smaller than the text itself, and a revert
    needs to restore an exact prior state, not replay a patch against
    whatever the content happens to be *now* (which may have been edited
    by hand since). Bounded per document (`MAX_ENTRIES_PER_DOCUMENT` below,
    enforced in routes_documents.py) rather than kept forever, the same
    "a log, not an unbounded table" reasoning `taskhistory.py` uses for its
    own ring buffer: except this one has to survive a restart (a revert
    button pointing at nothing after closing the app would be worse than
    not offering one), so it is a real table, not an in-memory deque.
    """

    __tablename__ = "document_ai_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    verb: Mapped[str] = mapped_column(String(10), default="edit")
    instruction: Mapped[str] = mapped_column(String(500), default="")
    #: Whichever passage was targeted, trimmed to a display-sized excerpt, 
    #: never the full document (that's what before_content is for), just
    #: enough for the changelog entry to say what it touched.
    selection_excerpt: Mapped[str] = mapped_column(String(200), default="")
    before_content: Mapped[str] = mapped_column(Text, default="")
    after_content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PageRead(Base):
    """One page of one document, as read by one of the OCR workspace's readers.

    **This table exists because the reading was being thrown away.** Reported
    twice: *"ai read the pages 1-3 in my pdf as I put it, but no text appeared
    in any of the extracted text areas?? notifications appeared saying the
    pages were read but nothing happened after that."*

    The second sentence is the diagnosis. A page read is a model round-trip of
    several seconds, and the app deliberately advertises it as a background
    task so the workspace can be closed while it runs, that is what those
    notifications are. But the result only ever existed in the HTTP response
    and in the DOM the response painted. Close the workspace, switch tab, or
    simply have the read finish after you have moved on, and the text was
    gone: reopening the document showed empty extracted-text areas, with the
    "read" notifications sitting in the panel saying it had worked.

    So each page's reading is stored as it completes, and the workspace loads
    what is already known when a document is opened. It also makes a range
    read resumable and idempotent, asking again for a page already read is
    answered from here rather than costing another pass of the model.

    Keyed by `(kind, source_id, page)`: a page can belong to an Attachment or
    to a MediaUpload, which are two different id spaces, so the kind has to be
    part of the identity. Re-reading a page replaces its row rather than
    appending: the newest reading is the one the workspace should show, and a
    history of transcriptions of the same page is not something anyone asked
    for.
    """

    __tablename__ = "page_reads"
    __table_args__ = (
        UniqueConstraint("kind", "source_id", "page", name="uq_page_read_source_page"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: "attachment" or "upload", see the class docstring on why this is part
    #: of the key rather than a detail.
    kind: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    #: Zero-based, matching the API and the page rail's own indexing.
    page: Mapped[int] = mapped_column(Integer, default=0)
    #: Which reader produced it: "vision", "ocr" or "tesseract".
    reader: Mapped[str] = mapped_column(String(16), default="vision")
    #: The model's name, or "Tesseract". Shown to the reader, because "who read
    #: this" is the first question when a transcription looks wrong.
    model: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    #: **A description of this page, which is not the same claim as its text.**
    #:
    #: Asked for directly: *"image captioning, how it is done and displayed
    #: needs to be refined for pdf documents and other similar documents. with
    #: graphs, images and diagrams in them."*
    #:
    #: `MediaUpload.caption` is one caption for one file, which is the right
    #: shape for a photograph and the wrong one for a twenty-page slide deck:
    #: the figures are per page, and a single sentence about "the document"
    #: describes none of them. A page already has a row here, the per-page
    #: reading lives on it, so the per-page description belongs on the same
    #: row rather than in a second table keyed the same three ways.
    #:
    #: Written and read independently of `text`: a page can be described
    #: without being transcribed and vice versa, so neither read path clears
    #: the other's column (see `_remember_page_read` and `_remember_page_caption`
    #: in routes_files.py, which is why they are two functions).
    #:
    #: Additive columns with scalar defaults, so the auto-migrator in this
    #: module backfills every existing `page_reads` row with `""` rather than
    #: needing a migration of its own, the same treatment every other column
    #: added to this schema has had.
    caption: Mapped[str] = mapped_column(Text, default="")
    #: Which model wrote `caption`, surfaced in the UI for the same reason
    #: `model` is: a description is one model's guess, not the app's opinion.
    caption_model: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentRevision(Base):
    """A document's text as it was before an edit, the history behind "can the
    document have edit history like git logs??", asked for by name.

    Notes have had `EntryRevision` for a long time and documents had nothing:
    rewriting one destroyed what it used to say, with no way back beyond the
    session's own undo stack, which forgets on reload. `DocumentAiEdit` covered
    the *AI's* edits only: a person's own rewrite left no trace at all.

    Written before the change lands, so the newest revision is always the
    version being replaced, and stored as whole snapshots rather than diffs for
    the reason `DocumentAiEdit` already gives: a restore has to reproduce an
    exact prior state, not replay a patch against text that may have been
    edited by hand since.

    **Not one row per keystroke.** Autosave fires while you type, and a history
    with two hundred entries five seconds apart is not a history, it is a log
    nobody can read. `routes_documents` coalesces: an edit within
    `REVISION_QUIET_SECONDS` of the last revision replaces it rather than
    adding one, so a sitting at the keyboard becomes a single entry and
    coming back an hour later becomes another. That is what makes the list
    read like a git log rather than like a keylogger.
    """

    __tablename__ = "document_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    #: How the change was made: "edit" (a person), "ai" (an accepted AI
    #: suggestion), "restore" (rolled back to an earlier revision). Shown in
    #: the list, because "who changed this" is the first question a history
    #: answers.
    source: Mapped[str] = mapped_column(String(10), default="edit")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WhiteboardNode(Base, WorkspaceMixin):
    """A note card placed on the whiteboard canvas."""

    __tablename__ = "whiteboard_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"), default=None)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    z: Mapped[int] = mapped_column(Integer, default=0)
    #: A card's own size: asked for directly ("resizing... cards"). Nullable:
    #: unset means "auto", the CSS-sized ~250x150 every card used before this
    #: existed, so an old row (and the auto-migrator's own NULL backfill for
    #: it) renders exactly as it always did.
    width: Mapped[float | None] = mapped_column(Float, default=None)
    height: Mapped[float | None] = mapped_column(Float, default=None)
    #: Degrees, clockwise, about the card's own centre. Asked for directly
    #: ("rotations"); nullable/unset renders identically to 0 (no rotation),
    #: same reasoning as `width`/`height` above.
    rotation: Mapped[float | None] = mapped_column(Float, default=None)
    #: A persisted group (Ctrl+G): unlike `wbMultiSelection`'s own in-memory
    #: set, this survives a reload. An opaque client-generated id, not a
    #: foreign key to anything: a group spans three different tables (nodes,
    #: sketches, objects), so there is no one row for it to point at.
    group_id: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WhiteboardSketch(Base, WorkspaceMixin):
    """A freehand sketch placed on the whiteboard canvas."""

    __tablename__ = "whiteboard_sketches"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"), default=None)
    # The strokes data (JSON/SVG). Can be encrypted at rest later if needed.
    data: Mapped[str] = mapped_column(Text)
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    z: Mapped[int] = mapped_column(Integer, default=0)
    group_id: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WhiteboardObject(Base, WorkspaceMixin):
    """A freeform item on the whiteboard that isn't tied to a note: a pasted/
    dropped/uploaded image, or a text box, the two things asked for
    directly ("I want the whiteboard to basically be like OneNote and
    Microsoft Whiteboard") that a card (always wraps an existing note) and a
    sketch (a path, not a placeable rectangle) don't cover.

    One table with a `kind` discriminator rather than two, an image and a
    text box already share every other column (board, position, size), and
    the two things that differ (a media URL vs. styled text) both fit in one
    JSON `data` blob the same way a sketch's own stroke data already does.
    """

    __tablename__ = "whiteboard_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("entries.id"), default=None)
    kind: Mapped[str] = mapped_column(String(20))
    #: image: {"url": "/media/..."}. text: {"content": str, "color": str, "font_size": int}.
    #: A mindmap node (MINDMAP_PLAN.md §5.3) uses the same two shapes: a
    #: `topic` carries its own `content`, a `note`/`document`/`file`/`link`
    #: node carries the id of the library item it stands for in `ref_id`, and
    #: both may carry `collapsed`/`pinned`.
    data: Mapped[str] = mapped_column(Text)
    #: This node's parent in a mindmap's tree: NULL for a root topic and for
    #: every object on an ordinary whiteboard, which is what makes the map a
    #: *mode* of the board rather than a second data model (MINDMAP_PLAN.md
    #: §4, option B). Cross-branch links stay what they always were: link
    #: sketches, which are a general graph and are not this.
    #:
    #: **Deliberately not a `ForeignKey("whiteboard_objects.id")`**, for the
    #: same reason `Entry.filing_similar_id` isn't one either, plus one that
    #: is specific to this column:
    #:
    #: - the additive auto-migrator (`_add_missing_columns`) can only `ALTER
    #:   TABLE ... ADD COLUMN`, so a declared constraint would exist on
    #:   freshly created databases and *not* on any database that predates
    #:   this column. A rule enforced on some installs and not others is worse
    #:   than one enforced in code on all of them;
    #: - `PRAGMA foreign_keys=ON` is set, so a bulk `DELETE` that happens to
    #:   remove a parent before its child (deleting a space, purging a board)
    #:   would fail on row order alone.
    #:
    #: So the tree is enforced where it is read and written, 
    #: `routes_whiteboard.py` deletes a subtree with its root and refuses a
    #: re-parent that would make a node its own ancestor, and every reader
    #: treats a `parent_id` pointing at a row that is gone, or at a row on
    #: another board, as a root. That is the behaviour a dangling pointer
    #: should have anyway: a branch whose parent vanished is still a branch.
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    z: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[float] = mapped_column(Float, default=200.0)
    height: Mapped[float] = mapped_column(Float, default=120.0)
    #: Degrees, clockwise, about the object's own centre: same reasoning as
    #: `WhiteboardNode.rotation`.
    rotation: Mapped[float | None] = mapped_column(Float, default=None)
    group_id: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MediaUpload(Base, WorkspaceMixin):
    """Every file `/media/upload` has ever produced: an image pasted or
    dropped into a *note's* own markdown, unlike a whiteboard image object
    (`WhiteboardObject`), had no row tracking it at all: nothing could list
    it, delete it, or tell a live note apart from one whose image had
    already been removed from disk by hand (ROADMAP.md item 20a). One row
    per upload, regardless of where the resulting `/media/...` url ends up
    being pasted, a note's markdown, a whiteboard object, a document, so
    a single gallery and a single delete path cover all of them.
    """

    __tablename__ = "media_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: The stored, random filename, `/media/{filename}` serves it.
    filename: Mapped[str] = mapped_column(String(140))
    #: What the uploader's own file was called, kept for a readable gallery
    #: label only: never used to resolve a path.
    original_name: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: Local OCR text (core/ocr.py), filled in on a background thread after
    #: upload: NULL means "not extracted yet or nothing found", never
    #: distinguished from each other, since neither blocks the upload and a
    #: caller only ever wants "is there searchable text here at all".
    #: Populated for raster images only (`ocr.OCR_SUFFIXES`); a PDF upload
    #: stays NULL forever, honestly, no page-rasterisation step exists.
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    #: A vision model's own description of the image (`ai/captioning.py`),
    #: filled in on a background thread after upload, same NULL convention
    #: as `ocr_text` above: "not captioned yet or no vision model available",
    #: never distinguished, since neither blocks the upload. Written once and
    #: left alone after that (a caption an AI or a person already read and
    #: trusted must not silently change under them) unless the user presses
    #: Regenerate: see `routes_files.caption_media`.
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    #: Which model wrote the caption currently stored, or NULL when there is
    #: no caption or it was only ever typed by hand. Asked for directly: a
    #: caption with no visible author reads as this app's own opinion rather
    #: than one specific (possibly wrong) model's guess. Reset to NULL when
    #: the caption is cleared back to empty, same as `caption` itself.
    caption_model: Mapped[str | None] = mapped_column(String(200), default=None)
    #: True once a person has typed over an AI caption (or typed one from
    #: scratch): `caption_media`'s `text` path is the only way this is set.
    #: `caption_model` is left as whichever model wrote the caption *before*
    #: the edit (or NULL if there never was one) rather than cleared, so the
    #: badge can still say "started as granite3-vision, edited by you"
    #: instead of losing that history the moment someone fixes a typo.
    caption_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Verbatim text a vision model transcribed from the image
    #: (`ai/vision_ocr.py`), distinct from `ocr_text` above (Tesseract,
    #: local and exact) and from `caption` (a natural-language description,
    #: not a transcription). Asked for directly as a separate "extractor
    #: mode": Tesseract fails on handwriting, low-contrast photos and most
    #: non-Latin scripts, all of which a vision model can often still read.
    #: NULL until run: manual-trigger only (`POST /media/{id}/vision-ocr`),
    #: never automatic on upload, since it is a full model round trip a
    #: person opts into rather than something every upload should pay for.
    vision_ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    #: Which model produced `vision_ocr_text`, or NULL when there is none, 
    #: same "credit the model, not the app" reasoning as `caption_model`.
    vision_ocr_model: Mapped[str | None] = mapped_column(String(200), default=None)
    #: Bytes on disk, written once at upload time (PLAN.md §0 P6). Before this
    #: column existed, `GET /media` computed it by calling `Path.stat()` on
    #: every row on every single request, fine at a handful of files, a
    #: measured, avoidable disk hit at a few thousand. NULL means "uploaded
    #: before this column existed" (the additive auto-migrator's own
    #: NULL-backfill for a column with no scalar default), not "empty file", 
    #: `list_media` backfills any NULL it finds once, from a real `stat()`,
    #: and never stats again after that.
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)


class UserPreference(Base):
    """Agent Memory Streams: Learned preferences and instructions appended by the AI."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: True while the *model* has proposed this and the user has not answered.
    #: A proposal is not in the prompt and is not "off", those are different
    #: states and the UI shows them differently. Asked for directly: "can the
    #: ai pick up things and suggest the user adds it as a preference in that
    #: section with an accept or deny or similar popup??"
    #:
    #: The distinction matters beyond tidiness. `save_user_preference` used to
    #: write a standing instruction into every future prompt with no
    #: confirmation of any kind, the tool's own description said "quietly
    #: append", so a model that misread one sentence could give itself a
    #: permanent rule the user never agreed to and would only find by opening
    #: a settings page they had no reason to visit.
    #:
    #: Scalar default (not a server_default or a callable) so the additive
    #: auto-migrator backfills every preference that existed before proposals
    #: did as already-accepted, which is what they are.
    proposed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    """Every meaningful action, logged from the start (plan §4), and since
    Brief 7 the event log the rest of the app replays (WORLD_CLASS_PLAN B1).

    One table, not two: this row already carried the action, the entity and
    the time, and a second `events` table beside it would have meant two
    half-histories, each missing whatever the other recorded. `actor` and
    `payload` are what it lacked, so they were added here.

    `core/events.py` is the only writer (`manager.log_action` delegates to
    it) and the only reader that interprets `payload`.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(50))  # created/edited/deleted/...
    entity_type: Mapped[str] = mapped_column(String(50))  # entry/category/...
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    #: Who did it: `user`, `ai:<tool or skill>`, or `system:<job>`. Free text
    #: rather than an enum because the tail of it (which tool, which job) is
    #: the half a reader actually wants, and an enum would have to be widened
    #: every time a skill is added. Defaults to `user`: an event with no
    #: stated actor came from somebody pressing something, which is what the
    #: pre-Brief-7 rows were, so the backfill default tells the truth about
    #: them too.
    actor: Mapped[str] = mapped_column(String(60), default="user")
    #: The whole value of every field this action set, not a diff:
    #: `{"before": {...}, "after": {...}}` for a change, plus whatever else
    #: the action needs to be replayable (a purge carries `{"ids": [...]}`).
    #: Whole values because `events.replay` rebuilds a note by applying each
    #: `after` in order, and a diff would need every earlier event to be
    #: present and correct to mean anything at all.
    payload: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_logger = logging.getLogger("memorymap.database")


def _migrations_root() -> Path:
    """Where `alembic.ini` and `migrations/` live, source or frozen.

    Mirrors `api/app.py`'s own `FRONTEND_DIR` resolution exactly: same
    directory depth from this file (`src/memorymap/core/database.py`) to
    the repo root, same `sys.frozen`/`_MEIPASS` split for a PyInstaller
    build. Kept here rather than imported from `app.py` because `core/` is
    the bottom layer (`deps.register_cache_reset`'s own docstring, above,
    already explains why that direction matters in this codebase).
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]


def _ensure_alembic_baseline(db_path: Path) -> None:
    """Make Alembic aware of this exact database, without ever running DDL
    against one that doesn't need it.

    Every database this app opens already has the correct current schema by
    the time this runs, `create_all()` and `_add_missing_columns()` above
    guarantee that, unchanged, for both a brand-new database and an existing
    one missing a column. What Alembic adds is only for the day a *rename*
    or *drop* is actually needed, which those two never could do (`core/
    database.py`'s own module docstring has said so from the start). So:

    - No `alembic_version` table yet (every database before this function
      existed, plus every fresh one `create_all()` just built) → **stamp**
      to the baseline revision. Stamping records "this database is already
      at revision X" without executing revision X's `upgrade()`, correct
      here specifically because the schema already matches it by
      construction, not because stamping is generally safe to reach for.
    - `alembic_version` already exists → a previous startup already
      stamped or migrated this database, so **upgrade** to head. A no-op
      when nothing newer than what's stamped has been added; applies any
      real migration that has, the actual point of wiring this in at all.

    Never allowed to stop the app from starting: this is new, additive
    infrastructure layered on a schema mechanism that already works on its
    own, not a replacement for it. Any failure here: a packaging issue in
    a frozen build that didn't bundle `migrations/` correctly, a locked
    file, anything: is logged and swallowed rather than raised.

    `DatabaseManager.__init__` skips calling this at all under pytest
    (`PYTEST_CURRENT_TEST`, which pytest itself sets, no per-test opt-in
    needed): a throwaway `tmp_path` database that gets discarded the
    moment its one test ends has nothing to gain from being stamped, and
    this measured ~30ms per call against a suite where `DatabaseManager`
    runs in a large fraction of the ~1,600 tests: real minutes, for a
    database that will never see a second startup to make the "upgrade"
    half of this function's job matter. The skip lives at the call site,
    not in here, so `tests/test_alembic_baseline.py` can call this function
    directly and actually exercise it.
    """
    try:
        from alembic import command
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine as _create_engine

        root = _migrations_root()
        ini_path = root / "alembic.ini"
        if not ini_path.is_file():
            _logger.warning("Alembic config not found at %s, skipping", ini_path)
            return

        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(root / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        # alembic.ini's own [loggers] section defaults to INFO, meant for a
        # human watching a terminal run `alembic upgrade head` by hand: not
        # for every one of this app's own startups. This runs silently
        # unless something actually goes wrong (the except below still logs).
        logging.getLogger("alembic").setLevel(logging.WARNING)

        probe_engine = _create_engine(f"sqlite:///{db_path}")
        try:
            with probe_engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_revision()
        finally:
            probe_engine.dispose()

        # migrations/env.py calls logging.config.fileConfig() every time
        # command.stamp/upgrade below runs it, and that call unconditionally
        # REPLACES the handler list (and resets the level) of every logger
        # alembic.ini explicitly configures, root among them, regardless
        # of disable_existing_loggers, which only protects loggers *not*
        # listed there from being disabled. alembic.ini's own
        # [logger_root] sets handlers = console, so this silently tore
        # logbuffer.install()'s own handler off the root logger and
        # replaced it with Alembic's plain console handler for the rest of
        # this process's life: reported directly: the Settings -> Logs
        # viewer showed nothing but Alembic's own plugin-registration
        # lines, forever, because nothing the app itself logs reaches a
        # handler that no longer exists. Same mechanism undid the
        # WARNING level just set above ([logger_alembic] says INFO),
        # which is why those plugin lines were visible at all. Restored
        # here rather than in env.py itself, because a human running
        # `alembic upgrade head` directly from a terminal *wants*
        # fileConfig()'s effect to stick for that short-lived process, 
        # this restore only matters for the in-process caller, which is
        # this function.
        root_logger = logging.getLogger()
        saved_root_handlers = list(root_logger.handlers)
        saved_root_level = root_logger.level
        saved_alembic_level = logging.getLogger("alembic").level
        try:
            if current is None:
                command.stamp(cfg, "head")
            else:
                command.upgrade(cfg, "head")
        finally:
            root_logger.handlers = saved_root_handlers
            root_logger.setLevel(saved_root_level)
            logging.getLogger("alembic").setLevel(saved_alembic_level)
    except Exception:  # noqa: BLE001  # see docstring: never fatal to startup
        _logger.warning("Alembic baseline/upgrade step failed", exc_info=True)


class DatabaseManager:
    """Owns the one engine + session factory for the whole app."""

    def __init__(self, db_path: Path) -> None:
        # check_same_thread=False because FastAPI serves requests from a
        # threadpool; SQLAlchemy still gives each request its own session.
        self.engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )

        # Per-connection SQLite settings. All of these are per-connection
        # rather than per-database, so they have to be set on every connect.
        @event.listens_for(self.engine, "connect")
        def _configure_connection(dbapi_connection, _record):  # noqa: ANN001
            # SQLite ignores foreign keys unless told otherwise.
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            # WAL lets readers carry on while a write is in progress. Without
            # it, saving a note blocks every concurrent read, and FastAPI
            # serves from a threadpool, so a background job (the janitor, an
            # embedding write) overlapping a page load is routine rather than
            # rare. WAL persists on the file, but setting it per connection is
            # harmless and covers a database created by an older version.
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            # When two writers do collide, wait rather than failing instantly.
            # The default is 0, which turns a millisecond of contention into a
            # "database is locked" error the user sees as a broken save.
            dbapi_connection.execute("PRAGMA busy_timeout=5000")
            # NORMAL is the recommended durability level under WAL: still
            # crash-safe, without an fsync on every single commit.
            dbapi_connection.execute("PRAGMA synchronous=NORMAL")
            # Temp b-tree sorts and the transient tables ANALYZE/vacuum use
            # otherwise spill to a file under the data directory, the same
            # disk this app is trying to keep quiet while a local model reads
            # its own weights off it. The working set here is one user's own
            # notebook, not a multi-gigabyte warehouse query, so keeping it in
            # RAM instead costs nothing that matters (PLAN.md §0 P5).
            dbapi_connection.execute("PRAGMA temp_store=MEMORY")

        Base.metadata.create_all(self.engine)  # creates missing tables only
        self._add_missing_columns()
        self._rebuild_categories_unique_constraint()
        self._backfill_inherited_workspaces()
        self._ensure_fts5()
        self._ensure_indexes()
        # See _ensure_alembic_baseline's own docstring for why this is
        # skipped under pytest: a throwaway per-test database has nothing
        # to gain from being stamped, and the constructor runs in most of
        # this suite's ~1,600 tests.
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            _ensure_alembic_baseline(db_path)
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        self._ensure_search_index()
        self._ensure_default_spaces()

    def _ensure_search_index(self) -> None:
        """The index that covers every kind (`search/index.py`), built once.

        Below the session factory rather than beside `_ensure_fts5` because a
        database that has never had this table has to be *filled*, and filling
        it needs a session.

        `importlib`, not an `import` statement: `search/index.py` reads this
        module's models, so naming it here closes `core.database ->
        search.index -> core.database`, and the storage layer is the wrong
        end of that edge to be doing the naming.
        `tests/test_no_import_cycles.py` counts the statement wherever it
        sits (CodeQL does), so a function-level `from ... import` would hide
        the cycle rather than break it.
        """
        search_index = importlib.import_module("memorymap.search.index")

        with self.engine.begin() as connection:
            created = search_index.ensure_table(connection)
        if not created:
            return
        # Only on the one startup that creates the table: every write after
        # this keeps itself in step (see the module's `after_flush` hook), so
        # this is a migration, not a recurring cost.
        with self.session() as session:
            search_index.rebuild(session)
            session.commit()

    def _ensure_default_spaces(self) -> None:
        """Seed default spaces if none exist."""
        with self.session() as session:
            if session.query(Space).first() is None:
                defaults = [
                    Space(id="default", name="Default Space", icon="ph-house"),
                    Space(id="work", name="Work", icon="ph-briefcase"),
                    Space(id="personal", name="Personal", icon="ph-user"),
                    Space(id="projects", name="Projects", icon="ph-kanban")
                ]
                session.add_all(defaults)
                session.commit()


    def _ensure_fts5(self) -> None:
        """An FTS5 index over `entries`, kept in sync by triggers.

        ROADMAP.md item 32: `keyword_search` used to be a leading-wildcard
        `ILIKE`, which no index can serve, plus a hand-rolled integer score
        that treats a rare word the same as a common one. FTS5's own
        `bm25()` gives real IDF-weighted relevance, already in SQLite, no
        new dependency: for the cost of one virtual table.

        `content='entries', content_rowid='id'` makes this an *external
        content* table: FTS5 stores only its own index, not a second copy
        of the text, and `entries.id` already is the SQLite rowid (a plain
        `INTEGER PRIMARY KEY` column is a rowid alias). The three triggers
        are what an external-content table needs instead of the automatic
        upkeep a normal table gets from the ORM, SQLite doesn't have
        anything that reaches into a virtual table on its own, so every
        write path (the ORM, a raw migration script, anything future) stays
        in sync for free rather than needing to remember to call something.
        `IF NOT EXISTS` throughout makes this safe to run on every startup,
        the same additive convention `_add_missing_columns` already uses.
        """
        with self.engine.begin() as connection:
            # Stemming, so "proving" finds "prove" and "proved", and "boots"
            # finds "boot". The index shipped on FTS5's default tokenizer,
            # which matches whole words only; with no AI running keyword
            # search is the whole of search, and a query in a different
            # inflection than the note found nothing. `porter unicode61`
            # is built into SQLite's FTS5, no dependency. A tokenizer is
            # fixed at CREATE time, so an index built before this has to be
            # rebuilt once: the table's own DDL in sqlite_master says which
            # it is, and dropping the index (never the notes: it is an
            # external-content table holding no text of its own) lets the
            # back-fill below repopulate it, guarded by the trigger it also
            # drops.
            existing_ddl = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries_fts'"
            ).scalar()
            if existing_ddl and "porter" not in existing_ddl:
                for trigger in ("entries_fts_ai", "entries_fts_ad", "entries_fts_au"):
                    connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
                connection.exec_driver_sql("DROP TABLE IF EXISTS entries_fts_vocab")
                connection.exec_driver_sql("DROP TABLE IF EXISTS entries_fts")
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5("
                "content, tags, content='entries', content_rowid='id', "
                "tokenize='porter unicode61'"
                ")"
            )
            # The index's own vocabulary as a table, one row per distinct
            # term, maintained by FTS5 itself. `keyword_search` reads it to
            # correct a misspelt query word to the nearest word the notebook
            # actually contains ("sourdogh" → "sourdough"), which is the
            # cheap, honest form of typo tolerance: it can only ever suggest
            # words that exist in the notes, and it costs one range scan on
            # the term's first letter rather than a second index.
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts_vocab "
                "USING fts5vocab('entries_fts', 'row')"
            )
            # A fresh virtual table starts empty even when `entries` already
            # has rows (a database from before this existed), the
            # external-content trick means FTS5 never scanned the real table
            # on its own. `INSERT INTO ... SELECT` once, guarded by the
            # trigger's own existence so it can't re-run and duplicate rows
            # on every subsequent startup.
            already_wired = connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type='trigger' AND name='entries_fts_ai'"
            ).scalar()
            if not already_wired:
                connection.exec_driver_sql(
                    "INSERT INTO entries_fts(rowid, content, tags) "
                    "SELECT id, content, tags FROM entries"
                )
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS entries_fts_ai "
                "AFTER INSERT ON entries BEGIN "
                "INSERT INTO entries_fts(rowid, content, tags) "
                "VALUES (new.id, new.content, new.tags); "
                "END"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS entries_fts_ad "
                "AFTER DELETE ON entries BEGIN "
                "INSERT INTO entries_fts(entries_fts, rowid, content, tags) "
                "VALUES ('delete', old.id, old.content, old.tags); "
                "END"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS entries_fts_au "
                "AFTER UPDATE ON entries BEGIN "
                "INSERT INTO entries_fts(entries_fts, rowid, content, tags) "
                "VALUES ('delete', old.id, old.content, old.tags); "
                "INSERT INTO entries_fts(rowid, content, tags) "
                "VALUES (new.id, new.content, new.tags); "
                "END"
            )

    #: The list queries that run on essentially every page load, and the
    #: composite index each one needs to be served from an index instead of a
    #: sort. Kept as data in one place rather than as `Index()` objects on the
    #: model, for a reason worth stating: `create_all()` "creates missing
    #: tables only" (see its call site above), so an index declared on an
    #: already-existing table would be created on a *fresh* database and
    #: silently never appear on anybody's real one: the same
    #: works-on-a-new-profile-only trap `_add_missing_columns` exists to avoid
    #: for columns.
    #:
    #: The column order in each is the query's own shape: equality filters
    #: first, then the ORDER BY terms in order and in their own direction.
    #: SQLite will only skip the sort if the index's trailing columns match
    #: the ORDER BY exactly, direction included, which is why `pinned DESC`
    #: is spelled out rather than left to default ASC.
    _INDEXES: tuple[tuple[str, str], ...] = (
        # manager.list_entries(), the Notes tab, GET /entries, and most
        # background jobs. Measured before this existed: EXPLAIN QUERY PLAN
        # reported "USE TEMP B-TREE FOR ORDER BY", i.e. SQLite sorted every
        # live note in the notebook on every call.
        (
            "ix_entries_live",
            "entries (workspace_id, is_deleted, archived_at, "
            "pinned DESC, created_at DESC, id DESC)",
        ),
        # manager.list_deleted_entries(), the recycle bin.
        (
            "ix_entries_bin",
            "entries (workspace_id, is_deleted, deleted_at DESC, id DESC)",
        ),
        # manager.list_archived_entries(), the archive.
        (
            "ix_entries_archive",
            "entries (workspace_id, is_deleted, archived_at DESC, id DESC)",
        ),
        # routes_library._notes() and routes_graph's entry scan both add
        # `is_draft = 0` to the live filter; without `is_draft` in an index
        # they fall back to the same full scan the live index above removes.
        (
            "ix_entries_live_nodraft",
            "entries (workspace_id, is_deleted, is_draft, archived_at, "
            "created_at DESC, id DESC)",
        ),
        # PLAN.md §0 P5 / AUDIT.md B10's remaining, unverified columns.
        # `Entry.category_id`, a plain ForeignKey column carries no index of
        # its own in SQLAlchemy/SQLite, is scanned by "notes in category X"
        # (`entry/manager.py`'s `category_entry_ids`/`move_category_entries`)
        # and by every `/library` row that resolves a note's category name.
        ("ix_entries_category_id", "entries (category_id)"),
        # `Attachment.entry_id`, same gap: an unindexed ForeignKey, searched
        # both singly (a note opening its own attachments) and via `IN (...)`
        # over a page of notes (`/library`'s thumbnail lookup,
        # `entry/manager.py`'s bulk delete). Measured: without this, the
        # `IN` lookup above does a full table scan of `attachments` per page.
        ("ix_attachments_entry_id", "attachments (entry_id)"),
        # GET /media (`routes_files.list_media`) orders every upload by
        # `created_at DESC` inside the workspace filter `WorkspaceMixin`
        # already adds: measured "USE TEMP B-TREE FOR ORDER BY" on 5,000
        # uploads without this; the single-column `workspace_id` index the
        # mixin gives every table isn't enough once an ORDER BY is added on
        # top of the equality filter.
        ("ix_media_uploads_workspace_created", "media_uploads (workspace_id, created_at DESC)"),
        # GET /documents (`routes_documents.list_documents`) is the same
        # shape one predicate wider: workspace-scoped, `archived_at IS NULL`,
        # ordered by `updated_at DESC`, same measured TEMP B-TREE without a
        # composite index that includes the sort column.
        (
            "ix_documents_workspace_live_updated",
            "documents (workspace_id, archived_at, updated_at DESC)",
        ),
        # `PageRead(kind, source_id)`, named in the same audit item, turns
        # out to already be covered: `uq_page_read_source_page`'s own unique
        # constraint is itself an index on `(kind, source_id, page)`, and
        # SQLite serves both `_remember_page_read`'s single-row lookup and
        # `_stored_page_reads`'s `kind=? AND source_id IN (...)` scan from
        # its `(kind, source_id)` prefix with no SCAN (checked with EXPLAIN
        # QUERY PLAN, not assumed), so no new index is added for it here.
        #
        # `events.events_for`, which is a note's History sheet, every replay
        # and every restore (WORLD_CLASS_PLAN B1, Brief 7): it filters
        # `entity_type` and `entity_id` and orders by `id DESC`, and neither
        # filter column was indexed, so opening one note's history read the
        # whole of `audit_log`. That table only grows, and grows fastest on
        # the notebooks that are used most, so this is the one index here
        # whose absence gets worse rather than staying merely wasteful.
        # Measured on 60,000 events over 2,000 notes: "SCAN audit_log" at
        # 6.390 ms per request became "SEARCH audit_log USING INDEX
        # ix_audit_log_entity" at 0.082 ms. `id DESC` is in the index so the
        # newest-first page is a walk backwards along it rather than a sort
        # of everything that matched.
        ("ix_audit_log_entity", "audit_log (entity_type, entity_id, id DESC)"),
        # `EntryLink.source_entry_id` and `.target_entry_id`, the link table
        # of a linked-notes app and the largest remaining gap. Both are plain
        # ForeignKey columns, so neither carried an index, and every lookup
        # is `source = ? OR target = ?`: a note opening its own connections,
        # `links_for_entries_bulk` for a page of the notes list, the graph
        # build, and the two-hop walk `search/engine._hops_from` does per
        # search. Measured on 2,000 notes with 6,000 links, three per note:
        # "SCAN entry_links", and `links_for_entries_bulk` over a 50-note
        # page at 8.78 ms. Two single-column indexes rather than one
        # composite, because the OR means SQLite serves each side from its
        # own index and unions the rowids; a composite on (source, target)
        # would only serve the source half.
        ("ix_entry_links_source", "entry_links (source_entry_id)"),
        ("ix_entry_links_target", "entry_links (target_entry_id)"),
        # `WhiteboardObject.board_id`, the same shape: every open of a
        # whiteboard or mind map reads its objects by board, and the table
        # holds every object of every board. Measured on one board of 3,000
        # objects: "SCAN whiteboard_objects", 34.38 ms to read that board.
        ("ix_whiteboard_objects_board", "whiteboard_objects (board_id)"),
        # `Conversation` and `Reminder` list newest-first inside the
        # workspace filter the mixin adds, and both reported "USE TEMP
        # B-TREE FOR ORDER BY": the same shape as the media and documents
        # indexes above, which is why they take the same form.
        ("ix_conversations_workspace_updated", "conversations (workspace_id, updated_at DESC)"),
        ("ix_reminders_workspace_due", "reminders (workspace_id, due_at DESC)"),
        # `note_scores`, read newest-faded-first on every resurfacing request
        # (WORLD_CLASS_PLAN I4). The ORDER BY is the whole query, so without
        # this SQLite sorts every scored note to find three: measured at 800
        # notes, adding a LIMIT alone moved the read from 23.0 ms to 58.7 ms,
        # because a LIMIT over an unindexed sort still sorts everything and
        # then throws it away. The index is the half that makes the LIMIT
        # mean something.
        ("ix_note_scores_rank", "note_scores (score DESC, entry_id DESC)"),
    )

    def _ensure_indexes(self) -> None:
        """Create the composite indexes the hot list queries need.

        `IF NOT EXISTS` throughout, run on every startup, the same additive
        convention `_ensure_fts5` and `_add_missing_columns` already use, and
        for the same reason: it has to be correct on a database created by any
        earlier version, not only on a fresh one.

        Adding an index is not free, every write to `entries` maintains it , 
        but these are read-heavy paths by a wide margin in a notebook app, and
        the alternative measured on a 20k-note database was a temp B-tree sort
        of the whole table per request.
        """
        with self.engine.begin() as connection:
            for name, definition in self._INDEXES:
                connection.exec_driver_sql(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {definition}"
                )

    #: Rows whose space has to be *inherited* rather than defaulted, as
    #: `(table, parent-id column, parent table)`. See
    #: `_backfill_inherited_workspaces` for why a plain DEFAULT is wrong here.
    _WORKSPACE_INHERITANCE = (
        ("attachments", "entry_id", "entries"),
        ("reminders", "entry_id", "entries"),
        ("whiteboard_nodes", "board_id", "entries"),
        ("whiteboard_sketches", "board_id", "entries"),
        ("whiteboard_objects", "board_id", "entries"),
    )

    def _rebuild_categories_unique_constraint(self) -> None:
        """Move `categories.name`'s UNIQUE from the column to (space, name).

        `create_all` never touches an existing table and `_add_missing_columns`
        only ever *adds* columns, so an existing database keeps whatever
        constraints it was built with, and the one this replaces made a
        second space unusable. `get_or_create_category` looks a name up under
        the current space's filter; in another space it finds nothing, tries
        to insert, and hits a UNIQUE that spans every space at once.
        Reproduced as a **500 on `POST /entries`** the first time a note in a
        new space wanted a category name the default space already had, 
        which for ordinary names ("Work", "Ideas", "Uni") is immediately.

        SQLite cannot drop a constraint, so this is the standard rebuild:
        make the table with the right shape, copy every row, swap the names.
        Guarded on actually finding the old single-column unique index, so it
        runs exactly once per database and is a no-op on a fresh one (where
        `create_all` has already built the correct shape) and on every
        startup after the first.

        Never allowed to stop the app from starting, the same rule
        `_ensure_alembic_baseline` follows: a database that somehow cannot be
        rebuilt still opens, with the old constraint and the old limitation,
        rather than not opening at all.
        """
        try:
            with self.engine.begin() as connection:
                tables = {
                    row[0]
                    for row in connection.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "categories" not in tables:
                    return
                stale = None
                for index in connection.exec_driver_sql(
                    "PRAGMA index_list('categories')"
                ).fetchall():
                    name, unique = index[1], index[2]
                    if not unique:
                        continue
                    columns = [
                        row[2]
                        for row in connection.exec_driver_sql(
                            f"PRAGMA index_info('{name}')"
                        ).fetchall()
                    ]
                    if columns == ["name"]:
                        stale = name
                        break
                if stale is None:
                    return  # already the composite constraint, or never had one

                _logger.info("rebuilding categories to scope its unique name per space")
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.exec_driver_sql(
                    'CREATE TABLE "categories_rebuilt" ('
                    " id INTEGER NOT NULL PRIMARY KEY,"
                    " name VARCHAR(100) NOT NULL,"
                    " description TEXT,"
                    " created_at DATETIME,"
                    " workspace_id VARCHAR DEFAULT 'default' NOT NULL,"
                    " CONSTRAINT uq_categories_workspace_name UNIQUE (workspace_id, name)"
                    ")"
                )
                connection.exec_driver_sql(
                    'INSERT INTO "categories_rebuilt" '
                    " (id, name, description, created_at, workspace_id)"
                    " SELECT id, name, description, created_at,"
                    "        COALESCE(workspace_id, 'default') FROM categories"
                )
                connection.exec_driver_sql('DROP TABLE "categories"')
                connection.exec_driver_sql(
                    'ALTER TABLE "categories_rebuilt" RENAME TO "categories"'
                )
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_categories_workspace_id"
                    " ON categories (workspace_id)"
                )
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        except Exception:
            _logger.warning(
                "couldn't rebuild the categories table; spaces will still share "
                "one category namespace on this database",
                exc_info=True,
            )

    def _backfill_inherited_workspaces(self) -> None:
        """Give a newly-scoped child row the space its parent note is in.

        These six tables (the five here plus `media_uploads`) had no
        `workspace_id` at all until this ran, which is why an image uploaded
        inside a class-specific space showed up in the main space's gallery
        and a reminder written in one space appeared in every other, 
        reported directly, and reproduced before this was written.

        Adding the column is the easy half. `_add_missing_columns` backfills
        it with the model default, `'default'`, and for a *parentless* row
        (a `media_uploads` row, a whiteboard object on the shared
        board_id-NULL board) that is the honest answer: it really was
        visible everywhere before, and the main space is where it belongs
        now.

        For a row that hangs off a note it is actively wrong. An attachment
        on a note in space `uni` stamped `'default'` does not merely land in
        the wrong gallery: the workspace loader criteria then filter it out
        of its *own note*, so a user in `uni` opens the note they attached it
        to and the file is gone. That is data loss as far as anyone using it
        can tell. So each of these inherits from its parent note instead,
        and only a row with no parent keeps the default.

        Idempotent by construction: it only touches rows still sitting at
        `'default'` whose parent says otherwise, so a second startup is a
        no-op, and a row a user has deliberately moved is never dragged back.
        """
        with self.engine.begin() as connection:
            tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "entries" not in tables:
                return
            for table, fk, parent in self._WORKSPACE_INHERITANCE:
                if table not in tables:
                    continue
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        f'PRAGMA table_info("{table}")'
                    ).fetchall()
                }
                if "workspace_id" not in columns or fk not in columns:
                    continue
                connection.exec_driver_sql(
                    f'UPDATE "{table}" SET workspace_id = ('
                    f'  SELECT p.workspace_id FROM "{parent}" p WHERE p.id = "{table}".{fk}'
                    f") WHERE {fk} IS NOT NULL AND workspace_id = 'default'"
                    f'   AND EXISTS (SELECT 1 FROM "{parent}" p WHERE p.id = "{table}".{fk}'
                    f"              AND p.workspace_id <> 'default')"
                )

    def _add_missing_columns(self) -> None:
        """Additive auto-migration for existing databases.

        create_all() never touches tables that already exist, so a
        database made by an older version lacks newly added columns and
        every query on that table would 500. Add them here instead of
        making the user delete their data."""
        with self.engine.begin() as connection:
            for table in Base.metadata.tables.values():
                rows = connection.exec_driver_sql(
                    f'PRAGMA table_info("{table.name}")'
                ).fetchall()
                if not rows:
                    continue  # brand-new table: create_all just made it
                existing = {row[1] for row in rows}
                for column in table.columns:
                    if column.name in existing:
                        continue
                    ddl = (
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                        f"{column.type.compile(self.engine.dialect)}"
                    )
                    # Backfill old rows with the model's default when it's a
                    # plain value (callables like utcnow can't run in DDL, 
                    # those columns stay NULL for pre-existing rows).
                    if column.default is not None and column.default.is_scalar:
                        value = column.default.arg
                        if isinstance(value, bool):
                            value = int(value)
                        if isinstance(value, str):
                            ddl += f" DEFAULT '{value}'"
                        else:
                            ddl += f" DEFAULT {value}"
                    connection.exec_driver_sql(ddl)

    def session(self) -> Session:
        """A fresh session; caller is responsible for closing it."""
        return self._session_factory()
