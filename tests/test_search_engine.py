"""The retrieval engine, measured (SESSION_BRIEFS Brief 11, WORLD_CLASS_PLAN B3).

`tests/test_search_engine_spec.py` is the contract and stays as written; this
file is where the behaviour around it is pinned: the operators one by one, the
index's write path, the three scores, and the perf gates with the numbers they
were measured at.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text as sa_text

from memorymap.search.query import understand


def test_an_ordinary_question_has_no_operators():
    u = understand("what did I write about beans")
    assert u.filters == {"tag": [], "kind": [], "space": [], "has": [], "is": []}
    assert not u.has_operators
    assert u.subject == "beans"


def test_operators_are_lifted_out_of_the_subject():
    u = understand("tag:work sourdough starter")
    assert u.filters["tag"] == ["work"]
    assert "tag:work" not in u.subject
    assert "sourdough" in u.subject


def test_a_quoted_value_and_a_comma_list():
    u = understand('tag:"two words" kind:note,document')
    assert u.filters["tag"] == ["two words"]
    assert u.filters["kind"] == ["note", "document"]


def test_aliases_mean_the_same_thing():
    assert understand("type:document").filters["kind"] == ["document"]
    assert understand("space:work").filters["space"] == ["work"]
    assert understand("tags:garden").filters["tag"] == ["garden"]


def test_before_and_after_are_exclusive_bounds():
    u = understand("before:2026-01-01 after:2025-12-01")
    assert u.until == date(2025, 12, 31)
    assert u.since == date(2025, 12, 2)


def test_a_typed_date_beats_a_time_phrase():
    """Both in one query: the stated bound wins rather than being overwritten."""
    u = understand("beans before:2026-01-01 last week", now=date(2026, 6, 1))
    assert u.until == date(2025, 12, 31)


def test_an_unreadable_date_invents_nothing():
    """`before:tuesday` is not an ISO date. No bound is guessed from it, and
    the words stay in the query, so the person sees their own text matching
    nothing rather than the app filtering by a date it made up."""
    u = understand("before:tuesday", now=date(2026, 6, 3))
    assert u.since is None and u.until is None
    assert "tuesday" in u.subject


def test_an_operator_query_is_not_a_time_only_question():
    u = understand("kind:document before:2026-01-01")
    assert not u.time_only


def test_a_url_is_not_an_operator():
    """`https:` must not read as an operator, and the url must survive whole.

    The assertion is on the whole subject rather than on a substring of it:
    CodeQL flagged the substring form (incomplete URL substring
    sanitization), and it is right that "does this text contain
    example.com" is a different question from "is this that url".
    """
    u = understand("https://example.com/thing")
    assert not u.has_operators
    assert u.subject == "https://example.com/thing"


@pytest.mark.parametrize("q", ["", "   ", '"', "-", "tag:"])
def test_a_ragged_query_is_never_an_error(q):
    understand(q)


# --- the index over every kind ------------------------------------------------


def _counts(session):
    from memorymap.search import index

    return index.counts(session)


def test_every_kind_has_a_source_and_an_unknown_one_is_loud():
    from memorymap.search import index

    for kind in index.KINDS:
        assert index.sources_for_kind(kind), f"no index source for kind {kind!r}"
    for source in index.sources():
        assert index.source_for(source.name) is source
    with pytest.raises(index.UnknownSource):
        index.source_for("entries_but_spelled_wrong")


def test_slots_are_unique_because_they_are_baked_into_rowids():
    from memorymap.search import index

    slots = [source.slot for source in index.sources()]
    assert len(set(slots)) == len(slots)


def test_a_note_is_indexed_when_it_is_written(session):
    from memorymap.entry import manager

    manager.create_entry(session, "sourdough starter needs feeding", tags=["bread"])
    session.commit()
    assert _counts(session)["note"] == 1


def test_a_board_is_indexed_as_a_board_not_a_note(session):
    from memorymap.core.database import Entry

    session.add(Entry(content="my map", is_board=True))
    session.commit()
    counts = _counts(session)
    assert counts["board"] == 1 and counts["note"] == 0


def test_a_private_note_is_never_indexed(session):
    from memorymap.core.database import Entry

    session.add(Entry(content="ciphertext here", is_private=True))
    session.commit()
    assert _counts(session)["note"] == 0


def test_an_edit_keeps_the_index_in_step(session):
    """The write the event log does not see (a document edit records no
    event), which is why the index hangs off the flush instead."""
    from memorymap.core.database import Document
    from memorymap.search import index

    doc = Document(title="Roadmap", content="quarterly planning")
    session.add(doc)
    session.commit()
    assert index.counts(session)["document"] == 1
    doc.content = "quarterly planning and the allotment"
    session.commit()
    rows = session.execute(
        sa_text("SELECT body FROM search_index WHERE kind='document'")
    ).all()
    assert len(rows) == 1 and "allotment" in rows[0][0]


def test_deleting_takes_the_row_out(session):
    from memorymap.core.database import Bookmark

    mark = Bookmark(url="https://example.com", title="example")
    session.add(mark)
    session.commit()
    assert _counts(session)["bookmark"] == 1
    session.delete(mark)
    session.commit()
    assert _counts(session)["bookmark"] == 0


def test_every_kind_lands_in_one_index(session):
    from memorymap.core.database import (
        Attachment,
        Bookmark,
        Document,
        Entry,
        Reminder,
    )
    from datetime import datetime

    session.add(Entry(content="a note about beans"))
    session.add(Entry(content="a board", is_board=True))
    session.add(Document(title="a document", content="beans again"))
    session.add(Bookmark(url="https://example.com/beans", title="beans online"))
    session.add(Reminder(text="buy beans", due_at=datetime(2026, 1, 1)))
    session.flush()
    session.add(
        Attachment(entry_id=1, filename="beans.pdf", stored_name="x1", ocr_text="beans, dried")
    )
    session.commit()
    counts = _counts(session)
    assert counts["note"] == 1
    assert counts["board"] == 1
    assert counts["document"] == 1
    assert counts["bookmark"] == 1
    assert counts["reminder"] == 1
    assert counts["file"] == 1


def test_rebuild_matches_what_the_writes_indexed(session):
    from memorymap.core.database import Document, Entry
    from memorymap.search import index

    session.add(Entry(content="one"))
    session.add(Document(title="two", content="two"))
    session.commit()
    live = index.counts(session)
    index.rebuild(session)
    session.commit()
    assert index.counts(session) == live


# --- the engine ---------------------------------------------------------------


def _note(session, content, **kwargs):
    from memorymap.entry import manager

    entry = manager.create_entry(session, content, tags=kwargs.pop("tags", []))
    for key, value in kwargs.items():
        setattr(entry, key, value)
    session.commit()
    return entry


def test_a_hit_from_every_kind_comes_back_from_one_query(session):
    from datetime import datetime

    from memorymap.core.database import Bookmark, Document, Entry, Reminder
    from memorymap.search import engine

    _note(session, "allotment planting plan")
    session.add(Entry(content="allotment board", is_board=True))
    session.add(Document(title="Allotment", content="the allotment beds"))
    session.add(Bookmark(url="https://example.com", title="allotment guide"))
    session.add(Reminder(text="water the allotment", due_at=datetime(2026, 1, 1)))
    session.commit()

    hits = engine.search(session, "allotment", ctx=None)
    assert {hit.kind for hit in hits} == {"note", "board", "document", "bookmark", "reminder"}
    assert all(hit.explain for hit in hits)


def test_a_filter_narrows_the_kinds(session):
    from memorymap.core.database import Document
    from memorymap.search import engine

    _note(session, "beans in the ground")
    session.add(Document(title="Beans", content="beans everywhere"))
    session.commit()

    hits = engine.search(session, "kind:document beans", ctx=None)
    assert [hit.kind for hit in hits] == ["document"]


def test_an_excluded_word_drops_the_hit(session):
    from memorymap.search import engine

    _note(session, "beans and rice")
    _note(session, "beans and bread")
    assert len(engine.search(session, "beans", ctx=None)) == 2
    kept = engine.search(session, "beans -rice", ctx=None)
    assert len(kept) == 1 and "bread" in kept[0].snippet


def test_a_tag_filter_uses_the_indexed_tags(session):
    from memorymap.search import engine

    _note(session, "planting notes", tags=["garden"])
    _note(session, "planting notes for work", tags=["work"])
    hits = engine.search(session, "tag:garden planting", ctx=None)
    assert len(hits) == 1


def test_the_open_note_lifts_what_is_linked_to_it(session):
    """The graph signal, which is the one no amount of text similarity has."""
    from memorymap.core.database import EntryLink
    from memorymap.search import engine

    open_note = _note(session, "the plan for the season")
    linked = _note(session, "seedlings hardening off")
    _note(session, "seedlings from a different year entirely")
    session.add(EntryLink(source_entry_id=open_note.id, target_entry_id=linked.id))
    session.commit()

    hits = engine.search(session, "seedlings", ctx={"entry_id": open_note.id})
    assert hits[0].ref_id == linked.id
    assert hits[0].scores["graph"] == 0.5  # one hop: 1 / (1 + 1)
    assert "linked to the open note" in hits[0].explain


def test_every_hit_says_which_signal_carried_it(session):
    from memorymap.core.database import Document
    from memorymap.search import engine

    _note(session, "risotto with peas", tags=["recipe"])
    hits = engine.search(session, "risotto", ctx=None)
    assert hits[0].explain[0] == "matched your words"
    assert set(hits[0].scores) == {"bm25", "cosine", "graph"}

    # A title only counts as one when the body does not simply repeat it: a
    # one-line note *is* its own first line, and "matched the title" there is
    # a distinction the reader cannot see.
    session.add(Document(title="Risotto method", content="stir until the rice gives"))
    session.commit()
    titled = engine.search(session, "kind:document risotto", ctx=None)
    assert titled[0].explain[0] == "matched the title"


def test_a_cold_matrix_means_no_similarity_not_a_scan(session, monkeypatch):
    """`related()` returning nothing beats `related()` reading every vector:
    startup warms the matrix, so cold is the first seconds of a process."""
    from memorymap.search import engine

    monkeypatch.setattr(engine, "_matrix", None)
    calls = []
    monkeypatch.setattr(engine, "_load_all_vectors", lambda *a, **k: calls.append(1))
    assert engine.related(session, entry_id=1, k=5) == []
    assert not calls


def test_the_matrix_takes_a_new_vector_without_reloading(session, fake_embeddings):
    from memorymap.search import engine

    entry = _note(session, "a note about bread")
    assert engine.warm_vectors(session) >= 0
    before = len(engine.vectors_by_id(session))
    fake_embeddings.store_for_entry(session, entry)
    assert len(engine.vectors_by_id(session)) == before + 1


def test_the_search_endpoint_answers_with_scores(client):
    client.post("/entries", json={"content": "bubble tea is a drink"})
    body = client.get("/search", params={"q": "bubble tea"}).json()
    assert body["hits"], body
    hit = body["hits"][0]
    assert set(hit["scores"]) == {"bm25", "cosine", "graph"}
    assert hit["explain"]
    assert body["counts"]["note"] == 1


def test_the_search_endpoint_is_behind_the_lock():
    """The one gate this app has: a route that reads the notebook is
    registered with `locked`, and this one reads every kind at once."""
    from pathlib import Path

    source = Path("src/memorymap/api/app.py").read_text(encoding="utf-8")
    assert "app.include_router(routes_search.router, dependencies=locked)" in source


def test_making_a_note_private_takes_its_vector_out_of_the_matrix(
    session, fake_embeddings, monkeypatch
):
    """A vector derived from the text is exactly what the encryption is for.
    The bulk `delete()` in `set_private` never reaches the in-memory array,
    so the array is told directly."""
    from memorymap.entry import manager
    from memorymap.search import engine

    entry = _note(session, "the private thing about bread")
    fake_embeddings.store_for_entry(session, entry)
    engine.warm_vectors(session)
    assert entry.id in engine.vectors_by_id(session)

    monkeypatch.setattr("memorymap.core.vault.key", lambda: b"k" * 32)
    assert manager.set_private(session, entry, True)
    session.commit()
    assert entry.id not in engine.vectors_by_id(session)


def test_forget_vector_is_reachable_on_its_own(session, fake_embeddings):
    from memorymap.search import engine

    entry = _note(session, "a note to forget")
    fake_embeddings.store_for_entry(session, entry)
    engine.warm_vectors(session)
    assert entry.id in engine.vectors_by_id(session)
    engine.forget_vector(entry.id)
    assert entry.id not in engine.vectors_by_id(session)


def test_a_query_of_filters_alone_still_answers(session):
    """`kind:document` is a question. An empty page for it would be the app
    refusing the one thing §5.1 promises works with no model running."""
    from memorymap.core.database import Document
    from memorymap.search import engine

    _note(session, "a note")
    session.add(Document(title="First", content="one"))
    session.add(Document(title="Second", content="two"))
    session.commit()

    hits = engine.search(session, "kind:document", ctx=None)
    assert {hit.kind for hit in hits} == {"document"}
    assert len(hits) == 2
    assert hits[0].explain == ["matched your filters"]


def test_a_quoted_phrase_binds_over_the_whole_query(session):
    """FTS5 binds AND tighter than OR, so an unbracketed `a OR b AND "p"`
    makes the phrase optional for half the results."""
    from memorymap.search import engine

    _note(session, "the quick brown fox jumped")
    _note(session, "quick, but no fox at all")
    hits = engine.search(session, 'quick fox "brown fox"', ctx=None)
    assert len(hits) == 1


def test_an_exclusion_binds_over_the_whole_query(session):
    from memorymap.search import engine

    _note(session, "beans with rice")
    _note(session, "peas with bread")
    # Loose enough that the "any" stage runs (no note has both words).
    hits = engine.search(session, "beans peas -rice", ctx=None)
    assert [hit.snippet for hit in hits] == ["peas with bread"]


def test_a_query_that_asks_for_nothing_answers_nothing(session):
    """An empty box, or a query that is only an exclusion, names nothing to
    find. Listing the notebook for it is noise with a scrollbar."""
    from memorymap.search import engine

    _note(session, "beans with rice")
    _note(session, "peas with bread")
    assert engine.search(session, "", ctx=None) == []
    assert engine.search(session, "   ", ctx=None) == []
    assert engine.search(session, "-rice", ctx=None) == []


def test_an_exclusion_narrows_a_filter_only_query(session):
    from memorymap.core.database import Document
    from memorymap.search import engine

    session.add(Document(title="Kept", content="peas"))
    session.add(Document(title="Dropped", content="rice"))
    session.commit()
    hits = engine.search(session, "kind:document -rice", ctx=None)
    assert [hit.title for hit in hits] == ["Kept"]
