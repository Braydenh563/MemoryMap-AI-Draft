"""Renaming or merging a category invalidates its notes' vectors.

A category's name is part of what its notes embed (`embedding_text`), which
is itself the fix for a reported problem: *"I have a whole category called
hobbies but basically none came up in the semantic search."*

The consequence nobody had wired up: rename "Games" to "Hobbies", or merge it
into an existing "Hobbies", and every note that moved still carries a vector
built from the old name, so semantic search keeps missing exactly the notes
the user just tidied. The same symptom, produced by the fix for it.

Vectors are dropped rather than recomputed: re-embedding is a model call per
note inside a rename the user is waiting on, and the search path already
treats a missing vector as "keywords for this note".
"""

from __future__ import annotations

from sqlalchemy import select

from memorymap.core import deps
from memorymap.core.database import Category, EmbeddingRecord, Entry
from memorymap.entry import manager


def _vector_count(session, entry_ids) -> int:
    return len(
        session.scalars(
            select(EmbeddingRecord).where(EmbeddingRecord.entry_id.in_(entry_ids))
        ).all()
    )


def test_renaming_a_category_drops_its_notes_vectors(ai_client, fake_embeddings):
    ai_client.post("/entries", json={"content": "seraphine build", "category": "Games"})
    ai_client.post("/entries", json={"content": "warwick jungle route", "category": "Games"})
    session = deps.get_db().session()
    try:
        games = session.scalar(select(Category).where(Category.name == "Games"))
        ids = [e.id for e in session.scalars(select(Entry).where(Entry.category_id == games.id))]
        assert len(ids) == 2
        assert _vector_count(session, ids) == 2, "the notes start out embedded"

        manager.rename_category(session, games.id, "Hobbies")

        assert _vector_count(session, ids) == 0, "stale vectors must not survive the rename"
    finally:
        session.close()


def test_merging_two_categories_drops_the_merged_notes_vectors(ai_client, fake_embeddings):
    ai_client.post("/entries", json={"content": "seraphine build", "category": "Games"})
    ai_client.post("/entries", json={"content": "gym split", "category": "Hobbies"})
    session = deps.get_db().session()
    try:
        games = session.scalar(select(Category).where(Category.name == "Games"))
        hobbies = session.scalar(select(Category).where(Category.name == "Hobbies"))
        moved_ids = [e.id for e in session.scalars(select(Entry).where(Entry.category_id == games.id))]
        stayed_ids = [e.id for e in session.scalars(select(Entry).where(Entry.category_id == hobbies.id))]

        result = manager.rename_category(session, games.id, "Hobbies")
        assert result["merged"] is True

        # Everything now under "Hobbies" is stale: the notes that moved changed
        # category outright, and the ones already there are in a category whose
        # membership, and so whose meaning to the user, just changed.
        assert _vector_count(session, moved_ids + stayed_ids) == 0
    finally:
        session.close()


def test_a_no_op_rename_leaves_the_vectors_alone(ai_client, fake_embeddings):
    """Renaming a category to the name it already has changes nothing, so it
    must not cost every note in it its vector."""
    ai_client.post("/entries", json={"content": "seraphine build", "category": "Games"})
    session = deps.get_db().session()
    try:
        games = session.scalar(select(Category).where(Category.name == "Games"))
        ids = [e.id for e in session.scalars(select(Entry).where(Entry.category_id == games.id))]
        before = _vector_count(session, ids)
        assert before == 1

        assert manager.rename_category(session, games.id, "Games")["renamed"] is False
        assert _vector_count(session, ids) == before
    finally:
        session.close()


def test_notes_in_other_categories_keep_their_vectors(ai_client, fake_embeddings):
    ai_client.post("/entries", json={"content": "seraphine build", "category": "Games"})
    ai_client.post("/entries", json={"content": "lecture notes", "category": "Uni"})
    session = deps.get_db().session()
    try:
        games = session.scalar(select(Category).where(Category.name == "Games"))
        uni = session.scalar(select(Category).where(Category.name == "Uni"))
        uni_ids = [e.id for e in session.scalars(select(Entry).where(Entry.category_id == uni.id))]

        manager.rename_category(session, games.id, "Hobbies")

        assert _vector_count(session, uni_ids) == len(uni_ids)
    finally:
        session.close()
