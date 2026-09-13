"""Filing by nearest neighbours (roadmap §9).

The janitor compared a note against each category's *centroid*: the average
of every note in it, and asked the chat model whenever that was inconclusive.
A centroid is a poor description of any category holding more than one kind of
thing, and with no chat model running "inconclusive" meant Uncategorised. Both
of those are what k-nearest-neighbour filing fixes.
"""

from __future__ import annotations

import numpy as np

from memorymap.ai import janitor
from memorymap.ai.embeddings import EmbeddingService, vector_to_bytes
from memorymap.core.database import Category, EmbeddingRecord, Entry


class DirectedEmbeddings(EmbeddingService):
    """Vectors chosen by the test, so similarity is exact rather than guessed."""

    def __init__(self, vectors: dict[str, list[float]]):
        super().__init__(model_manager=None, ollama_client=None)  # type: ignore[arg-type]
        self.vectors = vectors

    def backend_id(self) -> str:
        return "test:directed"

    def is_ready(self) -> bool:
        return True

    def embed_text(self, text: str):
        for key, vector in self.vectors.items():
            if key in text:
                return np.array(vector, dtype="float32")
        return np.array([0.0, 0.0, 0.0, 1.0], dtype="float32")


class DeadOllama:
    """No chat model at all, the case this feature exists for."""

    def is_running(self) -> bool:
        return False


def _note(session, content, category_name, vector, backend="test:directed"):
    category = session.query(Category).filter_by(name=category_name).one_or_none()
    if category is None:
        category = Category(name=category_name)
        session.add(category)
        session.flush()
    entry = Entry(content=content, category_id=category.id, ai_confidence=100)
    session.add(entry)
    session.flush()
    session.add(
        EmbeddingRecord(
            entry_id=entry.id,
            embedding=vector_to_bytes(np.array(vector, dtype="float32")),
            dim=len(vector),
            model_version=backend,
        )
    )
    session.commit()
    return entry


def test_a_split_category_still_files_correctly_with_no_chat_model(session, app_state):
    """The case a centroid gets wrong.

    "Work" holds three unrelated kinds of note, so its average sits between
    them and resembles none of them. A new note matching one cluster exactly
    still matches that average weakly, and with no chat model to fall back
    on, that used to mean Uncategorised.
    """
    # Three unrelated kinds of note in one category. Their average points at
    # none of them: it sits at cosine 0.58 to each cluster, under the 0.60 the
    # centroid path needs, so that path gives up on a note it should place.
    _note(session, "standup meeting notes", "Work", [1.0, 0.0, 0.0, 0.0])
    _note(session, "sprint retro notes", "Work", [1.0, 0.0, 0.0, 0.0])
    _note(session, "python snippet for retries", "Work", [0.0, 1.0, 0.0, 0.0])
    _note(session, "bash snippet for logs", "Work", [0.0, 1.0, 0.0, 0.0])
    _note(session, "expenses form", "Work", [0.0, 0.0, 1.0, 0.0])
    _note(session, "invoice template", "Work", [0.0, 0.0, 1.0, 0.0])
    _note(session, "pasta recipe", "Cooking", [0.0, 0.0, 0.0, 1.0])

    embeddings = DirectedEmbeddings({"planning meeting": [1.0, 0.0, 0.0, 0.0]})
    name, confidence, method = janitor.categorise(
        session, "planning meeting", embeddings, model_manager=None, ollama=DeadOllama()
    )
    assert name == "Work"
    assert method == "semantic-neighbours"
    assert confidence > 0


def test_neighbours_are_not_consulted_when_nothing_is_close(session, app_state):
    """An unrelated note must not be dragged into whichever category exists."""
    _note(session, "pasta recipe", "Cooking", [0.0, 0.0, 1.0, 0.0])
    _note(session, "risotto recipe", "Cooking", [0.0, 0.0, 0.99, 0.0])

    embeddings = DirectedEmbeddings({"tax return": [0.0, 0.0, 0.0, 1.0]})
    name, _confidence, method = janitor.categorise(
        session, "tax return", embeddings, model_manager=None, ollama=DeadOllama()
    )
    assert name == "Uncategorised"
    assert method == "none"


def test_a_split_vote_falls_through_to_the_model(session, app_state):
    """Two categories equally close is exactly when asking is worth the cost."""
    _note(session, "note a", "Alpha", [1.0, 0.0, 0.0, 0.0])
    _note(session, "note b", "Beta", [0.0, 1.0, 0.0, 0.0])

    # Equidistant from both at cosine 0.5: close enough for each to have an
    # opinion, far enough that no centroid claims it outright, and split
    # exactly evenly so neither takes a majority.
    embeddings = DirectedEmbeddings({"ambiguous": [0.5, 0.5, 0.7071, 0.0]})
    name, _confidence, method = janitor.categorise(
        session, "ambiguous", embeddings, model_manager=None, ollama=DeadOllama()
    )
    # No chat model, so it lands in the junk drawer, but by the intended
    # route, not by neighbours guessing.
    assert method == "none"
    assert name == "Uncategorised"


def test_confidence_reflects_both_closeness_and_agreement(session, app_state):
    """A unanimous vote among distant notes shouldn't read as certain."""
    _note(session, "one", "Topic", [1.0, 0.0, 0.0, 0.0])
    _note(session, "two", "Topic", [1.0, 0.0, 0.0, 0.0])

    close = janitor._knn_match(
        session, "x", DirectedEmbeddings({"x": [1.0, 0.0, 0.0, 0.0]})
    )
    far = janitor._knn_match(
        session, "y", DirectedEmbeddings({"y": [0.72, 0.69, 0.0, 0.0]})
    )
    assert close is not None and far is not None
    assert close.confidence > far.confidence


def test_a_private_notes_neighbours_are_never_used(session, app_state):
    """Filing by a private note's neighbours would leak what it's about."""
    secret = _note(session, "codeword elderflower", "Secrets", [1.0, 0.0, 0.0, 0.0])
    secret.is_private = True
    session.commit()

    embeddings = DirectedEmbeddings({"probe": [1.0, 0.0, 0.0, 0.0]})
    assert janitor._knn_match(session, "probe", embeddings) is None


def test_the_note_being_refiled_does_not_vote_for_itself(session, app_state):
    """Re-categorising has to be able to move a note, not anchor it."""
    entry = _note(session, "the note itself", "Old", [1.0, 0.0, 0.0, 0.0])
    _note(session, "somewhere else entirely", "New", [0.99, 0.02, 0.0, 0.0])

    embeddings = DirectedEmbeddings({"the note itself": [1.0, 0.0, 0.0, 0.0]})
    match = janitor._knn_match(
        session, "the note itself", embeddings, exclude_entry_id=entry.id
    )
    assert match is not None
    assert match.name == "New"


def test_an_empty_notebook_has_no_neighbours_to_ask(session, app_state):
    embeddings = DirectedEmbeddings({"anything": [1.0, 0.0, 0.0, 0.0]})
    assert janitor._knn_match(session, "anything", embeddings) is None


def test_the_confident_centroid_path_still_wins_first(session, app_state):
    """kNN is a fallback, not a replacement, the cheap check goes first."""
    _note(session, "pasta recipe", "Cooking", [1.0, 0.0, 0.0, 0.0])
    _note(session, "risotto recipe", "Cooking", [1.0, 0.0, 0.0, 0.0])

    embeddings = DirectedEmbeddings({"lasagne recipe": [1.0, 0.0, 0.0, 0.0]})
    name, _confidence, method = janitor.categorise(
        session, "lasagne recipe", embeddings, model_manager=None, ollama=DeadOllama()
    )
    assert name == "Cooking"
    assert method == "semantic-match"
