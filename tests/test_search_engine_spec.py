"""The retrieval engine (WORLD_CLASS_PLAN 4 B3; SESSION_BRIEFS Brief 11): the spec.

Built, 2026-09-12: every marker is off and every test here passes on its own
(`search/engine.py`, `search/index.py`). The file stays as written, as the
contract the engine is held to rather than a record of one session.
Specified: one `search()` over every kind; three scores per hit (bm25,
cosine, graph) so "why this result" is a rendering; the FTS index carries a
kind column; the operators of WORLD_CLASS_PLAN 5.1 parse; similarity no
longer loads every vector per request; and the perf gates on a 5,000-entry
fixture (recorded as before/after on the sandbox, not promised).
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def five_thousand(session):
    from memorymap.entry import manager

    for i in range(5000):
        manager.create_entry(session, f"note {i} about topic{i % 50} and thing{i % 7}", tags=[f"t{i % 9}"])
    session.commit()
    return session


def test_every_hit_carries_three_scores(session):
    from memorymap.entry import manager
    from memorymap.search import engine

    manager.create_entry(session, "bubble tea is a drink", tags=[])
    session.commit()
    hits = engine.search(session, "bubble tea", ctx=None)
    assert hits, "no hits for an exact phrase"
    for hit in hits:
        assert set(hit.scores) == {"bm25", "cosine", "graph"}
        assert hit.kind in {"note", "document", "board", "file", "bookmark", "reminder"}
        assert hit.explain, "each hit says why it matched, in words"


def test_the_index_covers_every_kind(session):
    from memorymap.search import engine

    counts = engine.index_counts(session)
    assert {"note", "document", "board", "file", "bookmark", "reminder"} <= set(counts)


def test_operators_parse():
    from memorymap.search.query import understand

    u = understand('tag:work kind:document in:personal before:2026-01-01 has:file is:pinned "exact phrase" -not')
    assert u.filters["tag"] == ["work"]
    assert u.filters["kind"] == ["document"]
    assert u.filters["space"] == ["personal"]
    assert u.filters["has"] == ["file"] and u.filters["is"] == ["pinned"]
    assert u.phrases == ["exact phrase"] and u.excluded == ["not"]


def test_keyword_search_is_fast_on_five_thousand(five_thousand):
    from memorymap.search import engine

    t = time.perf_counter()
    hits = engine.search(five_thousand, "topic7 thing3", ctx=None, hybrid=False)
    assert hits
    assert (time.perf_counter() - t) < 0.05, "FTS-only p95 must be under 50ms"


def test_similarity_does_not_scan_every_vector(five_thousand, monkeypatch):
    """The matrix is built once and updated by events; a request must not
    select every EmbeddingRecord row."""
    from memorymap.search import engine

    calls = []
    monkeypatch.setattr(engine, "_load_all_vectors", lambda *a, **k: calls.append(1))
    engine.related(five_thousand, entry_id=1, k=10)
    assert not calls, "related() loaded every vector for one request"
