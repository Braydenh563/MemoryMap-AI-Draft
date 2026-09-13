"""Notes that missed their embedding get one on the next start.

The bug: a note saved while the embedding model was still warming up got no
vector, and nothing ever went back for it, so it stayed invisible to semantic
search forever while looking completely normal in the notes list.
"""

from __future__ import annotations

from sqlalchemy import select

from memorymap.ai import embeddings
from memorymap.core import vault
from memorymap.core.database import EmbeddingRecord


def _factory(session):
    """Hand the backfill the test's own session, so assertions see its writes."""
    return lambda: session


def _embedded_ids(session):
    return {row.entry_id for row in session.scalars(select(EmbeddingRecord))}


def test_backfill_embeds_notes_that_have_none(client, session, fake_embeddings):
    a = client.post("/entries", json={"content": "first note"}).json()
    b = client.post("/entries", json={"content": "second note"}).json()
    # Simulate the warm-up gap: throw away the vectors that were stored.
    session.query(EmbeddingRecord).delete()
    session.commit()
    assert _embedded_ids(session) == set()

    fixed = embeddings.backfill_missing(fake_embeddings, _factory(session))

    assert fixed == 2
    assert _embedded_ids(session) == {a["id"], b["id"]}


def test_backfill_leaves_existing_embeddings_alone(client, session, fake_embeddings):
    client.post("/entries", json={"content": "already embedded"}).json()
    before = _embedded_ids(session)
    assert before  # the normal save path embedded it

    assert embeddings.backfill_missing(fake_embeddings, _factory(session)) == 0
    assert _embedded_ids(session) == before


def test_backfill_skips_private_notes(client, session, fake_embeddings):
    """A vector encodes what a note is about, backfilling one would leak it."""
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()

    entry = client.post("/entries", json={"content": "a private thing"}).json()
    client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    session.query(EmbeddingRecord).delete()
    session.commit()

    assert embeddings.backfill_missing(fake_embeddings, _factory(session)) == 0
    assert _embedded_ids(session) == set()
    vault.close()


def test_backfill_skips_binned_notes(client, session, fake_embeddings):
    entry = client.post("/entries", json={"content": "to be binned"}).json()
    client.delete(f"/entries/{entry['id']}")
    session.query(EmbeddingRecord).delete()
    session.commit()

    assert embeddings.backfill_missing(fake_embeddings, _factory(session)) == 0


def test_backfill_is_bounded(client, session, fake_embeddings):
    """A huge notebook must not spend minutes embedding on every launch."""
    for i in range(5):
        client.post("/entries", json={"content": f"note {i}"})
    session.query(EmbeddingRecord).delete()
    session.commit()

    assert embeddings.backfill_missing(fake_embeddings, _factory(session), limit=2) == 2


def test_backfill_does_nothing_without_a_ready_model(client, session, fake_embeddings):
    client.post("/entries", json={"content": "a note"})
    session.query(EmbeddingRecord).delete()
    session.commit()

    fake_embeddings.available = False  # is_ready() reads this
    assert embeddings.backfill_missing(fake_embeddings, _factory(session)) == 0


def test_wal_and_busy_timeout_are_set(app_state):
    """WAL lets reads continue during a write; the timeout stops a moment of
    contention surfacing as a broken save."""
    from memorymap.core import deps

    with deps.get_db().engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_repeated_embeds_of_the_same_text_are_cached():
    """Saving a note embeds the same text twice in quick succession, once to
    store the vector, once by the near-duplicate check right afterwards.

    Uses the real service: FakeEmbeddingService overrides embed_text wholesale,
    so it would never touch the cache being tested.
    """
    import numpy as np

    from memorymap.ai.embeddings import EmbeddingService

    service = EmbeddingService(model_manager=None, ollama_client=None)
    calls = []

    def fake_backend(text):
        calls.append(text)
        return np.array([len(text)], dtype="float32")

    service._embed_uncached = fake_backend

    first = service.embed_text("a note about bread")
    second = service.embed_text("a note about bread")

    assert calls == ["a note about bread"]  # the backend ran once, not twice
    assert (first == second).all()


def test_different_text_is_not_served_from_the_cache():
    import numpy as np

    from memorymap.ai.embeddings import EmbeddingService

    service = EmbeddingService(model_manager=None, ollama_client=None)
    calls = []

    def fake_backend(text):
        calls.append(text)
        return np.array([float(len(text))], dtype="float32")

    service._embed_uncached = fake_backend

    service.embed_text("bread")
    service.embed_text("kayaking")
    assert calls == ["bread", "kayaking"]


def test_the_cache_is_bounded():
    """It exists to collapse duplicate work in one request, not to grow."""
    import numpy as np

    from memorymap.ai import embeddings as emb
    from memorymap.ai.embeddings import EmbeddingService

    service = EmbeddingService(model_manager=None, ollama_client=None)
    service._embed_uncached = lambda text: np.array([1.0], dtype="float32")
    for i in range(emb._EMBED_CACHE_MAX + 20):
        service.embed_text(f"note {i}")
    assert len(service._embed_cache) <= emb._EMBED_CACHE_MAX
