"""PLAN.md §0 P5: the per-connection pragmas and the four remaining indexes
AUDIT.md B10 named as unverified: `Entry.category_id`, `Attachment.entry_id`,
and the `workspace_id`/order-by composite `/media` and `/documents` need.

`Entry.is_deleted` and `PageRead(kind, source_id)`, the other two names in
that item, are already covered, the first by `test_entry_indexes.py`'s four
composite indexes (every one of them leads with `is_deleted`), the second by
its own unique constraint, which is itself a `(kind, source_id, page)` index
(checked directly with EXPLAIN QUERY PLAN while writing this, no SCAN, no
new index needed, so neither is re-tested here).

**Why a file-backed database, not the usual in-memory one.** WAL is a file
journal mode: SQLite silently falls back to the in-memory `memory` journal
for an `:memory:` database regardless of what `PRAGMA journal_mode` is told,
so asserting `journal_mode == 'wal'` against an in-memory db would pass for
the wrong reason (or not exercise the pragma at all). `tmp_path` gives a real
file every fixture already relies on elsewhere in this suite
(`test_entry_indexes.py`'s own `db` fixture does the same).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from memorymap.core.database import (
    Attachment,
    AuditLog,
    Category,
    DatabaseManager,
    Document,
    Entry,
    EntryLink,
    MediaUpload,
    WhiteboardObject,
)


@pytest.fixture
def db(tmp_path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "pragma-test.db")


def _pragma(db: DatabaseManager, name: str):
    with db.engine.connect() as connection:
        return connection.exec_driver_sql(f"PRAGMA {name}").scalar()


def test_wal_and_synchronous_and_temp_store_are_set_on_a_file_backed_db(db):
    # journal_mode reads back lower-case regardless of how it was set.
    assert _pragma(db, "journal_mode") == "wal"
    # NORMAL reads back as the integer 1 (0=OFF, 1=NORMAL, 2=FULL/EXTRA).
    assert _pragma(db, "synchronous") == 1
    # temp_store reads back as the integer 2 (0=DEFAULT, 1=FILE, 2=MEMORY).
    assert _pragma(db, "temp_store") == 2
    # Pre-existing pragmas this item's own instructions said to keep.
    assert _pragma(db, "foreign_keys") == 1
    assert _pragma(db, "busy_timeout") == 5000


def test_the_new_indexes_exist_in_sqlite_master(db):
    with db.engine.connect() as connection:
        names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    for expected in (
        "ix_entries_category_id",
        "ix_attachments_entry_id",
        "ix_media_uploads_workspace_created",
        "ix_documents_workspace_live_updated",
        # The 2026-09-12 pass: the link table of a linked-notes app had no
        # index on either of its two foreign keys, a board's objects had none
        # on the board they belong to, and the conversation and reminder
        # lists sorted their whole table on every load.
        "ix_entry_links_source",
        "ix_entry_links_target",
        "ix_whiteboard_objects_board",
        "ix_conversations_workspace_updated",
        "ix_reminders_workspace_due",
        "ix_note_scores_rank",
    ):
        assert expected in names, f"{expected} missing from a fresh database"


def test_new_indexes_are_created_on_a_database_that_already_exists(tmp_path):
    """Same trap `test_entry_indexes.py` guards against for the older four:
    `create_all()` only builds indexes declared on a table it is creating, 
    an index added to `_INDEXES` after a user's database already has the
    `entries`/`attachments`/`media_uploads`/`documents` tables would silently
    never appear on their real notebook without `_ensure_indexes` re-running
    unconditionally on every startup, `IF NOT EXISTS` throughout.
    """
    path = tmp_path / "existing.db"
    original = DatabaseManager._INDEXES
    DatabaseManager._INDEXES = ()
    try:
        DatabaseManager(path)  # built with index creation disabled
    finally:
        DatabaseManager._INDEXES = original

    with DatabaseManager(path).engine.connect() as connection:  # reopened normally
        names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    for name, _definition in DatabaseManager._INDEXES:
        assert name in names, f"{name} missing after reopening an existing database"


def _plan(db: DatabaseManager, sql: str) -> list[str]:
    with db.engine.connect() as connection:
        return [row[-1] for row in connection.execute(text("EXPLAIN QUERY PLAN " + sql))]


def test_entries_by_category_is_served_by_its_index(db):
    """`entry/manager.py`'s `category_entry_ids`/`move_category_entries` filter
    entries by `category_id` alone: a plain ForeignKey column that SQLAlchemy
    does not index on its own."""
    with db.session() as session:
        session.info["workspace_id"] = "default"
        category = Category(name="Work", workspace_id="default")
        session.add(category)
        session.commit()
        session.add_all(
            [
                Entry(
                    content=f"n{i}",
                    tags="[]",
                    workspace_id="default",
                    category_id=category.id if i % 3 == 0 else None,
                )
                for i in range(3000)
            ]
        )
        session.commit()
        category_id = category.id

    plan = " ".join(_plan(db, f"SELECT * FROM entries WHERE category_id={category_id}"))
    assert "ix_entries_category_id" in plan, plan


def test_attachments_by_entry_id_is_served_by_its_index(db):
    """`/library`'s thumbnail lookup and `entry/manager.py`'s bulk delete both
    filter `Attachment.entry_id` with an `IN (...)` over a page of notes."""
    with db.session() as session:
        session.info["workspace_id"] = "default"
        entries = [Entry(content=f"n{i}", tags="[]", workspace_id="default") for i in range(500)]
        session.add_all(entries)
        session.commit()
        session.add_all(
            [
                Attachment(
                    entry_id=e.id,
                    filename="a.png",
                    stored_name=f"stored-{e.id}",
                    workspace_id="default",
                )
                for e in entries
            ]
        )
        session.commit()
        ids = ",".join(str(e.id) for e in entries[:50])

    plan = " ".join(_plan(db, f"SELECT * FROM attachments WHERE entry_id IN ({ids})"))
    assert "ix_attachments_entry_id" in plan, plan


def _seed_media_and_documents(db: DatabaseManager) -> None:
    with db.session() as session:
        session.info["workspace_id"] = "default"
        for i in range(3000):
            session.add(
                MediaUpload(
                    filename=f"f{i}.png", original_name=f"f{i}.png", workspace_id="default"
                )
            )
            session.add(Document(title=f"doc{i}", content="x", workspace_id="default"))
        session.commit()


def test_media_list_query_does_not_sort_the_whole_table(db):
    """`GET /media` (`routes_files.list_media`), workspace-scoped, ordered by
    `created_at DESC`. Measured "USE TEMP B-TREE FOR ORDER BY" before the
    composite index existed."""
    _seed_media_and_documents(db)
    plan = " ".join(
        _plan(db, "SELECT * FROM media_uploads WHERE workspace_id='default' ORDER BY created_at DESC")
    )
    assert "ix_media_uploads_workspace_created" in plan, plan
    assert "TEMP B-TREE" not in plan, plan


def test_documents_list_query_does_not_sort_the_whole_table(db):
    """`GET /documents` (`routes_documents.list_documents`), workspace-scoped,
    `archived_at IS NULL`, ordered by `updated_at DESC`. Same measured
    TEMP B-TREE before this index existed."""
    _seed_media_and_documents(db)
    plan = " ".join(
        _plan(
            db,
            "SELECT * FROM documents WHERE workspace_id='default' "
            "AND archived_at IS NULL ORDER BY updated_at DESC",
        )
    )
    assert "ix_documents_workspace_live_updated" in plan, plan
    assert "TEMP B-TREE" not in plan, plan


def test_a_notes_history_is_served_by_its_index(db):
    """`events.events_for`, which is the History sheet, every replay and
    every restore (WORLD_CLASS_PLAN B1): `entity_type` and `entity_id`
    equality, `id DESC` for the newest-first page. Measured on 60,000
    events over 2,000 notes before this index existed: "SCAN audit_log",
    6.390 ms per request; after it, 0.082 ms. `audit_log` is the one table
    that only grows, so a scan here gets worse with use rather than
    staying merely wasteful.
    """
    with db.session() as session:
        session.info["workspace_id"] = "default"
        session.add_all(
            [
                AuditLog(
                    action="edited",
                    entity_type="entry",
                    entity_id=(i % 400) + 1,
                    detail="x",
                    actor="user",
                    payload={"after": {"content": "a note", "tags": []}},
                )
                for i in range(4000)
            ]
        )
        session.commit()

    plan = " ".join(
        _plan(
            db,
            "SELECT * FROM audit_log WHERE entity_type='entry' AND entity_id=7 "
            "ORDER BY id DESC LIMIT 51",
        )
    )
    assert "ix_audit_log_entity" in plan, plan
    assert "SCAN audit_log" not in plan, plan
    assert "TEMP B-TREE" not in plan, plan


def test_a_notes_links_are_served_by_an_index_from_either_end(db):
    """`entry_links` is read by `source = ? OR target = ?` everywhere.

    A note opening its own connections, `links_for_entries_bulk` for a page
    of the notes list, the graph build and `search/engine._hops_from`'s
    two-hop walk all read this table, and both its columns are plain
    ForeignKeys, which SQLAlchemy does not index. Measured on 2,000 notes
    with 6,000 links: "SCAN entry_links" from either end.

    Two single-column indexes, not one composite: the OR lets SQLite serve
    each side from its own index and union the rowids, where a composite on
    (source, target) would serve the source half only.
    """
    with db.session() as session:
        session.info["workspace_id"] = "default"
        session.add_all([Entry(content=f"note {i}") for i in range(400)])
        session.commit()
        ids = [e.id for e in session.scalars(select(Entry)).all()]
        session.add_all(
            [
                EntryLink(source_entry_id=ids[i % len(ids)], target_entry_id=ids[(i + 7) % len(ids)])
                for i in range(2000)
            ]
        )
        session.commit()

    for column, index in (
        ("source_entry_id", "ix_entry_links_source"),
        ("target_entry_id", "ix_entry_links_target"),
    ):
        plan = " ".join(_plan(db, f"SELECT * FROM entry_links WHERE {column}=7"))
        assert index in plan, plan
        assert "SCAN entry_links" not in plan, plan


def test_a_boards_objects_are_served_by_an_index(db):
    """Every open of a whiteboard or mind map reads its objects by board.

    `whiteboard_objects` holds every object of every board, so without an
    index on `board_id` opening one board reads all of them. Measured on one
    board of 3,000 objects: "SCAN whiteboard_objects", 34.38 ms.
    """
    with db.session() as session:
        session.info["workspace_id"] = "default"
        board = Entry(content="a board", is_board=True)
        session.add(board)
        session.commit()
        session.add_all(
            [WhiteboardObject(board_id=board.id, kind="card", data="{}") for _ in range(500)]
        )
        session.commit()

    plan = " ".join(_plan(db, "SELECT * FROM whiteboard_objects WHERE board_id=1"))
    assert "ix_whiteboard_objects_board" in plan, plan
    assert "SCAN whiteboard_objects" not in plan, plan


def test_the_chat_and_reminder_lists_do_not_sort_their_whole_table(db):
    """Same shape as the media and documents list tests above.

    Both order newest-first inside the workspace filter `WorkspaceMixin`
    adds, and both reported "USE TEMP B-TREE FOR ORDER BY" before their
    composite index existed.
    """
    for sql, index in (
        (
            "SELECT * FROM conversations WHERE workspace_id='default' "
            "ORDER BY updated_at DESC LIMIT 50",
            "ix_conversations_workspace_updated",
        ),
        (
            "SELECT * FROM reminders WHERE workspace_id='default' "
            "ORDER BY due_at DESC LIMIT 50",
            "ix_reminders_workspace_due",
        ),
    ):
        plan = " ".join(_plan(db, sql))
        assert index in plan, plan
        assert "TEMP B-TREE" not in plan, plan


def test_the_resurfacing_read_is_a_walk_along_its_index(db):
    """`note_scores` is read faded-first on every resurfacing request.

    The ORDER BY is the whole query, and a LIMIT over an unindexed sort still
    sorts everything before throwing it away: measured at 800 notes, adding
    the LIMIT alone moved the read from 23.0 ms to 58.7 ms, and this index
    took it to 6.7 ms, faster at 800 notes than the unindexed version was at
    200. That last part is the tell that the cost stopped tracking the row
    count.
    """
    plan = " ".join(
        _plan(
            db,
            "SELECT * FROM note_scores ORDER BY score DESC, entry_id DESC LIMIT 3",
        )
    )
    assert "ix_note_scores_rank" in plan, plan
    assert "TEMP B-TREE" not in plan, plan
