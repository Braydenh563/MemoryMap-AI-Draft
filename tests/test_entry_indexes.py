"""The composite indexes behind the list queries, and the query plans that
prove they are actually being used.

Why a query-plan test rather than "the index exists": an index that exists but
is never chosen is indistinguishable from no index at all, and the way to lose
one is subtle: reorder a column in `list_entries`' `ORDER BY`, or change a
direction, and SQLite silently goes back to sorting the whole table. Asserting
on `EXPLAIN QUERY PLAN` fails *at the point the query drifts*, which asserting
on `sqlite_master` would not.

Measured on a 20,000-note database when these were added: the live-notes query
went from "USE TEMP B-TREE FOR ORDER BY" at ~46 ms/call to an index search at
~15 ms/call, and a single-note save went from 0.470 to 0.491 ms, a read win of
two thirds for a write cost inside the noise.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from memorymap.core.database import DatabaseManager, Entry
from memorymap.entry import manager

# The four hot list queries, spelled the way the ORM emits them. Kept as SQL
# rather than driven through `manager` because EXPLAIN QUERY PLAN needs the
# statement, and the point of the test is the shape of that statement.
LIVE = (
    "SELECT * FROM entries WHERE workspace_id='default' AND is_deleted=0 "
    "AND archived_at IS NULL ORDER BY pinned DESC, created_at DESC, id DESC LIMIT 1000"
)
BIN = (
    "SELECT * FROM entries WHERE workspace_id='default' AND is_deleted=1 "
    "ORDER BY deleted_at DESC, id DESC LIMIT 1000"
)
ARCHIVE = (
    "SELECT * FROM entries WHERE workspace_id='default' AND archived_at IS NOT NULL "
    "AND is_deleted=0 ORDER BY archived_at DESC, id DESC LIMIT 1000"
)
LIBRARY = (
    "SELECT * FROM entries WHERE workspace_id='default' AND is_deleted=0 "
    "AND archived_at IS NULL AND is_draft=0 ORDER BY created_at DESC, id DESC LIMIT 1000"
)


def _plan(db: DatabaseManager, sql: str) -> list[str]:
    with db.engine.connect() as connection:
        return [row[-1] for row in connection.execute(text("EXPLAIN QUERY PLAN " + sql))]


@pytest.fixture
def db(tmp_path) -> DatabaseManager:
    """A real database with enough rows that SQLite prefers an index to a
    scan. A handful of rows is not enough, the planner will correctly decide
    a table that fits in one page is cheaper to scan, and the test would pass
    or fail on row count rather than on the index."""
    database = DatabaseManager(tmp_path / "index-test.db")
    with database.session() as session:
        session.info["workspace_id"] = "default"
        session.add_all(
            [
                Entry(
                    content=f"note {i}",
                    tags='["a"]',
                    workspace_id="default",
                    is_deleted=(i % 50 == 0),
                    is_draft=(i % 30 == 0),
                )
                for i in range(2000)
            ]
        )
        session.commit()
    return database


@pytest.mark.parametrize(
    ("sql", "index"),
    [
        (LIVE, "ix_entries_live"),
        (BIN, "ix_entries_bin"),
        (ARCHIVE, "ix_entries_archive"),
        (LIBRARY, "ix_entries_live_nodraft"),
    ],
)
def test_each_list_query_is_served_by_its_index(db, sql, index):
    plan = " ".join(_plan(db, sql))
    assert index in plan, plan


@pytest.mark.parametrize("sql", [LIVE, BIN, ARCHIVE, LIBRARY])
def test_no_list_query_sorts_the_whole_table(db, sql):
    """The expensive half. A query can use an index for its WHERE clause and
    still sort every matching row afterwards, that is exactly what these
    looked like before the indexes were added."""
    plan = " ".join(_plan(db, sql))
    assert "TEMP B-TREE" not in plan, plan


def test_indexes_are_created_on_a_database_that_already_exists(tmp_path):
    """The trap this guards. `Base.metadata.create_all()` creates missing
    *tables* only, so an index declared on the model would appear on a fresh
    profile and never on anybody's real notebook. `_ensure_indexes` runs on
    every startup for that reason, this pins it by building a database with
    no indexes, then reopening it normally."""
    path = tmp_path / "existing.db"
    # Build the file with index creation disabled, the way a database written
    # by a version from before this feature existed would look.
    original = DatabaseManager._INDEXES
    DatabaseManager._INDEXES = ()
    try:
        DatabaseManager(path)
    finally:
        DatabaseManager._INDEXES = original

    with DatabaseManager(path).engine.connect() as connection:
        names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    for name, _definition in DatabaseManager._INDEXES:
        assert name in names, f"{name} missing after reopening an existing database"


def test_entry_id_scope_still_honours_the_active_space(tmp_path):
    """`entry_id_scope` selects a column rather than an entity, and the
    workspace filter is a `with_loader_criteria` on the mapped class, so
    "does it still apply?" is a real question, not a rhetorical one. It does,
    and this pins it: a column-only select that quietly stopped being
    space-scoped would leak one space's notes into another's search scope with
    nothing to notice it by.
    """
    database = DatabaseManager(tmp_path / "scoped.db")
    with database.session() as session:
        session.info["workspace_id"] = "work"
        session.add(Entry(content="a work note", tags="[]", workspace_id="work"))
        session.add(Entry(content="a personal note", tags="[]", workspace_id="personal"))
        session.commit()

    with database.session() as session:
        session.info["workspace_id"] = "work"
        scope = manager.entry_id_scope(session)
        entities = {entry.id for entry in session.scalars(select(Entry))}
    assert scope == entities
    assert len(scope) == 1


def test_all_tags_still_honours_the_active_space(tmp_path):
    """Same invariant, for the other column-only select changed alongside it."""
    database = DatabaseManager(tmp_path / "tagscoped.db")
    with database.session() as session:
        session.info["workspace_id"] = "work"
        session.add(Entry(content="w", tags='["work-only"]', workspace_id="work"))
        session.add(Entry(content="p", tags='["personal-only"]', workspace_id="personal"))
        session.commit()

    with database.session() as session:
        session.info["workspace_id"] = "work"
        manager.reset_tag_cache()
        assert set(manager.all_tags(session)) == {"work-only"}
