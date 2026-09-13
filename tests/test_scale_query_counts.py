"""Regression test for the N+1/full-scan patterns found scale-testing this
project: `routes_graph.graph()` was resolving each entry's category with its
own query, `search_manager.semantic_search()` materialised a full `Entry` ORM
object for every embedded note just to score and discard most of them
(ANALYSIS.md §34), `tools._graph_neighbours` fetched every non-deleted
`Entry` in the notebook whenever the note it was walking from had tags, and
`tools._note_summary` called `manager.entry_dates` once per row inside the
loops `list_notes`/`_summarize_notes` build their results from (both
ROADMAP.md Tier 1 item 8). `scripts/scale_test.py` measured the first two as
multi-second, N-proportional costs at 10k-50k notes; all four are now a
small, constant number of queries.

A query *count* rather than a wall-clock timing on purpose: a timing
assertion is flaky under CI load (a slow runner fails a fast function), while
"one query per entry" vs "a fixed handful of queries" is a fact about the
code, not the machine running it.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import event

from memorymap.ai import tools
from memorymap.ai.embeddings import vector_to_bytes
from memorymap.api import routes_graph
from memorymap.core.database import Category, EmbeddingRecord, Entry
from memorymap.search import search_manager


def _count_queries(session, fn):
    count = 0

    def _before_cursor_execute(*args, **kwargs):
        nonlocal count
        count += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    return count


def _count_statements(session, fn, contains):
    """Like `_count_queries`, but only counts statements whose SQL text
    contains `contains`, for asserting a specific table isn't queried
    twice, not just "the total didn't grow"."""
    hits = []

    def _before_cursor_execute(_conn, _cursor, statement, *_args, **_kwargs):
        if contains in statement:
            hits.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    return hits


def _add_entries(session, n, category_id):
    for i in range(n):
        session.add(Entry(content=f"note {i} about gardens", category_id=category_id))
    session.commit()


def test_graph_endpoint_query_count_does_not_scale_with_entry_count(session):
    category = Category(name="Garden")
    session.add(category)
    session.commit()

    _add_entries(session, 20, category.id)
    small = _count_queries(
        session, lambda: routes_graph.graph(similarity=False, session=session)
    )

    _add_entries(session, 200, category.id)
    large = _count_queries(
        session, lambda: routes_graph.graph(similarity=False, session=session)
    )

    # A handful more is fine, more entries can touch a few more code paths.
    # One extra query *per new entry* (the regression this guards) would be
    # +200, not a handful.
    assert large <= small + 5, (
        f"routes_graph.graph() issued {large} queries for 220 entries vs "
        f"{small} for 20: looks like the per-entry category lookup is back"
    )


def test_graph_endpoint_fetches_the_entries_table_once_not_twice(session):
    """`graph()` fetched the full `entries` table for node serialization,
    then `paths.build()` independently re-fetched the exact same
    identically-scoped set for its own path index, one call, two full
    scans of the same table. `graph()` now passes its own already-fetched
    list through."""
    category = Category(name="Garden")
    session.add(category)
    session.commit()
    _add_entries(session, 5, category.id)

    # Matched on a column only the full-row ORM fetch selects, the
    # notebook-fingerprint cache key also touches `entries` with its own
    # `count(...)`/`max(updated_at)` aggregates, which are unrelated,
    # already-cheap queries this test isn't about.
    hits = _count_statements(
        session,
        lambda: routes_graph.graph(similarity=False, session=session),
        "entries.access_count",
    )
    assert len(hits) == 1, f"expected one full `entries` row-fetch, got {len(hits)}: {hits}"


def test_semantic_search_query_count_does_not_scale_with_entry_count(
    session, fake_embeddings
):
    category = Category(name="Garden")
    session.add(category)
    session.commit()

    def _add_embedded_entries(n):
        for i in range(n):
            entry = Entry(content=f"note {i} about gardens", category_id=category.id)
            session.add(entry)
            session.flush()
            session.add(
                EmbeddingRecord(
                    entry_id=entry.id,
                    embedding=vector_to_bytes(np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")),
                    dim=4,
                    model_version=fake_embeddings.backend_id(),
                )
            )
        session.commit()

    _add_embedded_entries(20)
    small = _count_queries(
        session,
        lambda: search_manager.semantic_search(session, "garden", fake_embeddings, limit=5),
    )

    _add_embedded_entries(200)
    large = _count_queries(
        session,
        lambda: search_manager.semantic_search(session, "garden", fake_embeddings, limit=5),
    )

    assert large <= small + 5, (
        f"semantic_search issued {large} queries for 220 embedded entries vs "
        f"{small} for 20: looks like the per-candidate Entry fetch is back"
    )


def test_related_notes_tag_matching_query_count_does_not_scale_with_entry_count(session):
    """`_graph_neighbours` fetched every non-deleted `Entry`, the whole
    table, `content` included: whenever the note it was walking from had
    tags, to find tag matches by hand instead of a SQL filter.
    `_related_notes` calls it once per BFS-frontier node, so this scaled per
    call as well as per entry (ROADMAP.md Tier 1 item 8). Tags are a JSON
    text column with no per-tag index, so the fix narrows candidates with
    `ilike` rather than eliminating the scan outright, this pins "a fixed
    handful of queries", not "exactly one".
    """
    hub = Entry(content="hub", tags='["garden"]')
    session.add(hub)
    session.commit()

    def _call():
        tools.TOOLS["related_notes"].handler(session, {"note_id": hub.id})

    for i in range(20):
        session.add(Entry(content=f"note {i}", tags='["garden"]'))
    session.commit()
    small = _count_queries(session, _call)

    for i in range(200):
        session.add(Entry(content=f"note {i + 20}", tags='["garden"]'))
    session.commit()
    large = _count_queries(session, _call)

    assert large <= small + 2, (
        f"related_notes issued {large} queries for 220 tagged entries vs "
        f"{small} for 20: looks like the unfiltered full-table tag scan is back"
    )


def test_list_notes_date_lookup_query_count_does_not_scale_with_returned_notes(session):
    """`_note_summary` called `manager.entry_dates` (one SELECT per note)
    inside the loops `list_notes` and `_summarize_notes` build their results
    from: an N+1 on the agent's most-used read tools (ROADMAP.md Tier 1
    item 8). `entry_dates_bulk` fetches every returned note's dates in one
    query instead.
    """
    for i in range(5):
        session.add(Entry(content=f"note {i}"))
    session.commit()
    small = _count_queries(
        session, lambda: tools.TOOLS["list_notes"].handler(session, {"limit": 5})
    )

    for i in range(50):
        session.add(Entry(content=f"note {i + 5}"))
    session.commit()
    large = _count_queries(
        session, lambda: tools.TOOLS["list_notes"].handler(session, {"limit": 50})
    )

    assert large <= small + 3, (
        f"list_notes issued {large} queries for 50 returned notes vs "
        f"{small} for 5: looks like the per-note entry_dates lookup is back"
    )


def test_notes_list_fetches_attachments_once_not_once_per_note(client, session):
    """`GET /entries` reads the attachments table once per page, not per note.

    The fourth thing `_to_out` resolves per entry. `_to_out_bulk` had been
    given batched forms for categories, dates, documents and links, so the
    endpoint looked bulk-fetched; `attachments=` still called
    `manager.attachments_for` inside the list comprehension. Counted on a
    60-note page: 67 statements, 60 of them the same
    `SELECT ... FROM attachments WHERE entry_id = ?`; 8 after. This is the
    notes list, so it is the most-requested endpoint in the app.
    """
    category = session.scalars(__import__("sqlalchemy").select(Category).limit(1)).first()
    _add_entries(session, 60, category.id if category else None)

    hits = _count_statements(session, lambda: client.get("/entries"), "FROM attachments")
    assert len(hits) <= 1, f"one query per page, got {len(hits)}"
