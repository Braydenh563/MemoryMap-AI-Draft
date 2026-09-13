"""Core AI-module unit tests, all offline: vector helpers, janitor filing's
basic decision paths, librarian's message-building, and search retrieval.

(test_janitor_knn.py and test_keyword_search.py cover the same two modules'
edge cases and thorough behavior in more depth, this file is the basic
per-module coverage underneath both.)"""

from __future__ import annotations

import numpy as np
import pytest

from memorymap.ai import janitor, librarian
from memorymap.ai.embeddings import (
    bytes_to_vector,
    cosine_similarity,
    vector_to_bytes,
)
from memorymap.core import deps
from memorymap.core.database import EmbeddingRecord
from memorymap.entry import manager
from memorymap.search import search_manager
from tests.fakes import FakeEmbeddingService, FakeOllama, GarbageOllama


# --- vector storage helpers -------------------------------------------------


def test_vector_bytes_roundtrip():
    vector = np.array([0.25, -1.5, 3.0], dtype="float32")
    assert np.array_equal(bytes_to_vector(vector_to_bytes(vector)), vector)


def test_cosine_similarity_basics():
    a = np.array([1.0, 0.0], dtype="float32")
    b = np.array([0.0, 1.0], dtype="float32")
    assert cosine_similarity(a, a) == pytest.approx(1.0)
    assert cosine_similarity(a, b) == pytest.approx(0.0)
    assert cosine_similarity(a, np.zeros(2, dtype="float32")) == 0.0


# --- janitor ----------------------------------------------------------------


def _store(session, embeddings, content, category):
    """Seed one categorised entry with its embedding."""
    entry = manager.create_entry(session, content, category_name=category)
    assert embeddings.store_for_entry(session, entry)
    return entry


def test_janitor_prefers_the_model_over_a_confident_semantic_match(session, app_state):
    """A close vector match no longer short-circuits the model.

    This asserted the opposite until the filing order was reversed: a
    confident centroid match used to return before the chat model was asked,
    which in an established notebook meant the AI was consulted almost never
    (there is nearly always *some* category whose vectors sit close). Filed
    as a real complaint - notes landing in the wrong category and needing
    fixing by hand. "What does this resemble" is not "where does this
    belong", and only the model is answering the second question.
    """
    embeddings = FakeEmbeddingService()
    ollama = FakeOllama()
    model_manager = deps.get_model_manager()
    _store(session, embeddings, "Why did the scarecrow win an award?", "Dad Jokes")

    _, _, method = janitor.categorise(
        session, "another funny pun about cheese", embeddings, model_manager, ollama
    )

    assert method == "llm"
    assert len(ollama.chat_calls) == 1


def test_janitor_falls_back_to_centroid_match_with_no_model(session, app_state):
    """The semantic paths are still what files a note with no chat model.

    That is the case they were really written for, and reversing the order
    above must not cost it: with nothing running, `_ask_llm` reports method
    'none' and the centroid match takes over rather than everything landing
    in Uncategorised.
    """
    embeddings = FakeEmbeddingService()
    ollama = FakeOllama()
    ollama.running = False
    model_manager = deps.get_model_manager()
    _store(session, embeddings, "Why did the scarecrow win an award?", "Dad Jokes")

    category, confidence, method = janitor.categorise(
        session, "another funny pun about cheese", embeddings, model_manager, ollama
    )

    assert category == "Dad Jokes"
    assert confidence >= 60
    assert method == "semantic-match"
    assert ollama.chat_calls == []  # no model → nothing was asked


def test_janitor_asks_llm_when_no_match(session, app_state):
    embeddings = FakeEmbeddingService()
    ollama = FakeOllama()
    category, confidence, method = janitor.categorise(
        session, "buy milk and eggs", embeddings, deps.get_model_manager(), ollama
    )
    assert (category, confidence, method) == ("Shopping", 85, "llm")
    assert len(ollama.chat_calls) == 1


def test_janitor_falls_back_when_all_ai_down(session, app_state):
    embeddings = FakeEmbeddingService(available=False)
    ollama = FakeOllama(running=False)
    category, confidence, method = janitor.categorise(
        session, "anything at all", embeddings, deps.get_model_manager(), ollama
    )
    assert (category, confidence, method) == (manager.UNCATEGORISED, 0, "none")


def test_janitor_survives_garbage_llm_reply(session, app_state):
    embeddings = FakeEmbeddingService(available=False)
    ollama = GarbageOllama()
    category, confidence, method = janitor.categorise(
        session, "buy milk", embeddings, deps.get_model_manager(), ollama
    )
    assert (category, confidence, method) == (manager.UNCATEGORISED, 0, "none")


def test_extract_json_from_chatty_reply():
    data = janitor._extract_json('Sure! {"category": "X", "confidence": 9} Hope that helps.')
    assert data == {"category": "X", "confidence": 9}
    with pytest.raises(ValueError):
        janitor._extract_json("no json here")


# --- librarian ---------------------------------------------------------------


def test_librarian_no_results_message(app_state):
    text, thinking = librarian.answer(
        "anything?", [], deps.get_model_manager(), FakeOllama()
    )
    assert text == librarian.NO_RESULTS_MESSAGE
    assert thinking is None


def test_librarian_offline_message(app_state):
    notes = [{"content": "a joke", "category": "Dad Jokes"}]
    text, _thinking = librarian.answer(
        "jokes?", notes, deps.get_model_manager(), FakeOllama(running=False)
    )
    assert text == librarian.OFFLINE_MESSAGE


def test_model_error_message_sanitises_the_exception_text():
    """CodeQL: "information exposure through an exception" - the exception's
    own str() is untrusted (some standard-library exceptions embed a file
    path or connection detail), so it has to go through the same sanitiser
    the Settings -> Logs viewer trusts, not straight into a message shown
    back to whoever is running this session."""
    forged = "line one\nline two\x07" + "x" * 500
    message = librarian.model_error_message("llama3.2", RuntimeError(forged))
    assert "\n" not in message
    assert "\x07" not in message
    assert len(message) < len(forged)


def test_librarian_answers_with_notes_in_prompt(app_state):
    ollama = FakeOllama()
    notes = [{"content": "the cheese joke", "category": "Dad Jokes"}]
    text, _thinking = librarian.answer("jokes?", notes, deps.get_model_manager(), ollama)
    assert text == ollama.librarian_reply
    prompt = ollama.chat_calls[0][-1]["content"]
    assert "the cheese joke" in prompt  # answers come from the user's notes


# --- search -----------------------------------------------------------------


def test_keyword_search_matches_content_and_tags(session):
    manager.create_entry(session, "remember the milk", tags=["shopping"])
    manager.create_entry(session, "totally unrelated")
    assert len(search_manager.keyword_search(session, "milk")) == 1
    assert len(search_manager.keyword_search(session, "shopping")) == 1


def test_semantic_search_ranks_same_topic_first(session):
    embeddings = FakeEmbeddingService()
    _store(session, embeddings, "a funny scarecrow joke", "Dad Jokes")
    _store(session, embeddings, "buy milk and eggs", "Shopping")

    results = search_manager.semantic_search(session, "what jokes do I have?", embeddings)
    assert results is not None
    contents = [entry.content for entry, _score in results]
    assert contents == ["a funny scarecrow joke"]  # shopping is below the floor


def test_semantic_search_relative_floor_rejects_anisotropic_noise(session):
    """A real bug, reported live: an unrelated note scored 57% cosine
    similarity for an unconnected query. The flat MIN_SIMILARITY floor
    (0.25) assumes "0 is unrelated", which does not hold for the current
    default embedding model (BGE-family, anisotropic: see
    search_manager.py's own comment on RELATIVE_Z_MARGIN): unrelated notes
    routinely land at 0.4-0.6, well above that floor.

    Builds that shape directly with hand-picked vectors rather than
    FakeEmbeddingService's clean one-hot topics (which cannot produce it, 
    orthogonal axes give exactly 0.0 for "unrelated", never anisotropic
    noise). A corpus where every note happens to be similarly-but-not-really
    related to the query (~0.5, simulating the anisotropic baseline) plus
    one note that is genuinely on-topic (~0.9): the relative floor should
    keep only the real match, not just whatever clears the absolute 0.25."""
    rng = np.random.default_rng(0)

    def _near(base: np.ndarray, spread: float) -> np.ndarray:
        return (base + rng.normal(0, spread, size=base.shape)).astype("float32")

    query_vector = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
    # A direction close enough to the query to land around ~0.5 cosine
    # similarity: "moderately similar", not "unrelated by chance".
    baseline_direction = np.array([0.5, 0.5, 0.5, 0.5], dtype="float32")

    entries = []
    for i in range(6):
        entry = manager.create_entry(session, f"baseline note {i}")
        entries.append(entry)
        session.add(
            EmbeddingRecord(
                entry_id=entry.id,
                embedding=vector_to_bytes(_near(baseline_direction, 0.02)),
                dim=4,
                model_version="fake:relative-floor-test",
            )
        )
    real_match = manager.create_entry(session, "the actual match")
    session.add(
        EmbeddingRecord(
            entry_id=real_match.id,
            embedding=vector_to_bytes(_near(query_vector, 0.02)),
            dim=4,
            model_version="fake:relative-floor-test",
        )
    )
    session.commit()

    class _FixedQueryEmbeddings(FakeEmbeddingService):
        def backend_id(self) -> str:
            return "fake:relative-floor-test"

        def embed_text(self, text: str) -> np.ndarray:  # noqa: ARG002
            return query_vector

    results = search_manager.semantic_search(session, "anything", _FixedQueryEmbeddings())
    assert results is not None
    result_ids = {entry.id for entry, _score in results}
    assert real_match.id in result_ids
    assert result_ids.isdisjoint({e.id for e in entries})


def test_semantic_search_returns_its_matches_in_rank_order(ai_client, session):
    """`?semantic=true` rebuilt its result as "every note that matched, in
    notebook order", throwing away the ranking that is the whole point, so
    the best match landed wherever it happened to sit in the list."""
    for text_ in ("kayak repair", "sourdough starter", "kayak paddle"):
        ai_client.post("/entries", json={"content": text_})

    response = ai_client.get("/entries", params={"q": "kayak", "semantic": "true"})
    assert response.status_code == 200
    # Whatever the fake embedder ranks first must come back first.
    expected = [
        e.id
        for e, _ in search_manager.semantic_search(
            session, "kayak", deps.get_embeddings(), limit=25
        )
    ]
    assert [row["id"] for row in response.json()] == expected


def test_semantic_search_ignores_the_pagination_limit(ai_client, session):
    """GET /entries now pages the plain list (BACKLOG.md §20). The semantic
    branch decides which hits are in scope from the *complete* id set on
    purpose: it must never be quietly narrowed by a small `limit` meant for
    the unrelated plain-list page size, or a real match could vanish just
    because the note happened to sort past the requested page."""
    for text_ in ("kayak repair", "sourdough starter", "kayak paddle"):
        ai_client.post("/entries", json={"content": text_})

    # A tiny plain-list page (limit=1) must not narrow the semantic result:
    # it should match what a direct, unpaginated search returns, not one row.
    expected = [
        e.id
        for e, _ in search_manager.semantic_search(
            session, "kayak", deps.get_embeddings(), limit=25
        )
    ]
    response = ai_client.get(
        "/entries", params={"q": "kayak", "semantic": "true", "limit": 1}
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == expected
    assert len(expected) > 1  # otherwise this test can't tell truncation from luck


def test_a_cold_embedding_model_says_so_instead_of_dumping_the_notebook(client):
    """The failure was swallowed with a bare `except: pass`, which left the
    caller holding every note in the notebook labelled as a search result."""
    client.post("/entries", json={"content": "anything"})
    response = client.get("/entries", params={"q": "anything", "semantic": "true"})
    assert response.status_code == 503


def test_retrieve_falls_back_to_keyword(session):
    manager.create_entry(session, "remember the milk")
    entries, mode = search_manager.retrieve(
        session, "milk", FakeEmbeddingService(available=False)
    )
    assert mode == "keyword"
    assert [e.content for e in entries] == ["remember the milk"]


def test_retrieve_recent_fallback_for_broad_question(session):
    # Broad "overview" questions match nothing by keyword or meaning, so
    # the notebook must not look empty, recent entries come back instead.
    manager.create_entry(session, "a note about cheese")
    manager.create_entry(session, "a note about racing")
    entries, mode = search_manager.retrieve(
        session, "what have I saved so far?", FakeEmbeddingService(available=False)
    )
    assert mode == "recent"
    assert len(entries) == 2


def test_a_pinned_note_outranks_an_identical_unpinned_one(session):
    """BACKLOG.md §95 item B.6, asked for directly: "search ranks by
    relevance; it does not know that a note pinned last week matters more
    than a relevant one from 2023." Two notes that tie exactly on both
    semantic and keyword relevance (identical content) would, before this,
    tie-break on id alone (`_fuse`'s own `-note_id`), the newer one always
    wins regardless of anything else. Pinning the *older* one has to be
    enough to flip that, or the signal isn't doing anything."""
    embeddings = FakeEmbeddingService()
    older_pinned = manager.create_entry(session, "kayak repair notes")
    newer_unpinned = manager.create_entry(session, "kayak repair notes")
    assert older_pinned.id < newer_unpinned.id  # the tie-break this test isolates
    older_pinned.pinned = True
    for entry in (older_pinned, newer_unpinned):
        session.add(
            EmbeddingRecord(
                entry_id=entry.id,
                embedding=vector_to_bytes(embeddings.embed_text(entry.content)),
                dim=4,
                model_version=embeddings.backend_id(),
            )
        )
    session.commit()

    entries, mode = search_manager.retrieve(session, "kayak repair", embeddings, limit=2)
    assert mode == "hybrid"
    assert [e.id for e in entries] == [older_pinned.id, newer_unpinned.id]


def test_retrieve_recent_fallback_empty_notebook(session):
    # Truly empty notebook → still empty (nothing to fall back to).
    entries, mode = search_manager.retrieve(
        session, "anything", FakeEmbeddingService(available=False)
    )
    assert entries == []


def test_retrieve_finds_a_subject_match_outside_a_misremembered_range(session):
    """Reported directly: a joke tagged joke/jokes/funny (the word "joke"
    never appears in the text itself), asked about as "two weeks ago" when
    it was actually written three weeks ago, the hard date filter excluded
    it and the answer came back empty. Dropping the date and keeping the
    subject (not the reverse: see the comment on the fallback this pins)
    should surface it, labelled `outside_range` rather than as a real
    in-window hit."""
    from datetime import timedelta

    from memorymap.core.database import utcnow

    joke = manager.create_entry(
        session,
        "why did the chicken cross the road? to prove it could be done",
        tags=["joke", "jokes", "funny"],
    )
    joke.created_at = utcnow() - timedelta(days=21)
    session.commit()

    entries, mode = search_manager.retrieve(
        session, "that joke I wrote about two weeks ago", FakeEmbeddingService(available=False)
    )
    assert mode == "outside_range"
    assert [e.id for e in entries] == [joke.id]


def test_retrieve_dated_subject_question_still_empty_when_truly_nothing_matches(session):
    """The fallback above must not become the rejected one it sits next to
    - a date question with a subject that matches *nothing at all*, in or
    out of the window, still says so honestly rather than listing unrelated
    notes."""
    manager.create_entry(session, "a note about gardening")
    entries, mode = search_manager.retrieve(
        session, "that joke I wrote about two weeks ago", FakeEmbeddingService(available=False)
    )
    assert mode == "dated"
    assert entries == []


def test_chat_broad_question_answers_from_recent(ai_client, fake_ollama):
    # Reproduces the reported bug: entries exist but a broad question with
    # no semantic/keyword match returned "no saved notes". These two notes
    # sit on distinct topics, so an overview question matches neither and
    # the recent fallback must kick in.
    ai_client.post("/entries", json={"content": "a funny scarecrow joke"})
    ai_client.post("/entries", json={"content": "buy milk and eggs"})

    body = ai_client.post("/chat", json={"question": "what entries have I done so far?"}).json()
    assert body["search_mode"] == "recent"
    assert len(body["raw_results"]) == 2
    assert body["ai_response"] == fake_ollama.librarian_reply  # the model answered
    assert body["answered_by"] == "llama3.2"
    assert body["ollama_running"] is True


def test_turning_off_ai_first_filing_puts_the_vectors_back_in_front(
    session, app_state
):
    """The escape hatch for the latency the reordering introduced.

    Asking the model first costs a round-trip on every capture, which is felt
    immediately on a slow local model. Off, the embedding shortcuts decide
    what they can and the model is only asked for what they decline - the old
    order, without giving up the AI entirely.
    """
    embeddings = FakeEmbeddingService()
    ollama = FakeOllama()
    model_manager = deps.get_model_manager()
    _store(session, embeddings, "Why did the scarecrow win an award?", "Dad Jokes")
    deps.get_config().set_preference("ai_first_filing", False)

    category, _, method = janitor.categorise(
        session, "another funny pun about cheese", embeddings, model_manager, ollama
    )

    assert (category, method) == ("Dad Jokes", "semantic-match")
    assert ollama.chat_calls == []  # the vectors were confident, so no round-trip


def test_with_ai_first_filing_off_the_model_still_decides_what_vectors_cannot(
    session, app_state
):
    """Off is not "stop using the AI" - it is only a reordering."""
    embeddings = FakeEmbeddingService()
    ollama = FakeOllama()
    deps.get_config().set_preference("ai_first_filing", False)

    category, confidence, method = janitor.categorise(
        session, "buy milk and eggs", embeddings, deps.get_model_manager(), ollama
    )

    assert (category, confidence, method) == ("Shopping", 85, "llm")
    assert len(ollama.chat_calls) == 1
