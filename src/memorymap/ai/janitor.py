"""The janitor: files a new thought into a category (LLM prompt #1).

Not a separate AI model, just a prompt to the active chat model, with
embedding-based filing behind it for when there is no model. Order of
attempts:

1. ONE call to the chat model, JSON answer. **This runs first**, which is
   the reverse of how it worked originally: the embedding shortcuts used to
   come first and were so rarely declined that in an established notebook
   the model was almost never asked, and notes were filed by resemblance
   rather than by meaning. Reported as notes landing in the wrong category
   and needing fixing by hand; see `categorise` for the full reasoning.
2. Embedding vs. category centroids: free, and what files notes when no
   chat model is running.
3. Nearest neighbours: the k most similar individual notes vote for their
   own category. Catches what a centroid can't: a category holding more
   than one kind of thing has an average resembling none of them.
4. No AI available and nothing similar → 'Uncategorised' with confidence 0.
   Saving an entry must never fail because the AI is down (plan §4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.ai import librarian
from memorymap.ai.embeddings import EmbeddingService, bytes_to_vector, cosine_similarity
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError
from memorymap.core import deps
from memorymap.core.database import Category, EmbeddingRecord, Entry
from memorymap.core.logbuffer import safe_value
from memorymap.entry.manager import UNCATEGORISED

# Above this cosine similarity we trust the embedding match and skip
# the LLM entirely. Below it, the call is worth its cost.
CONFIDENT_MATCH = 0.60

# Nearest-neighbour filing, tried after the centroid and before the model.
# k is small because a personal notebook's categories are small: with twenty
# notes in a category, twenty neighbours is the whole category and the vote
# stops meaning anything.
KNN_NEIGHBOURS = 7
# A neighbour further away than this has no useful opinion about where a note
# belongs; below it, everything looks equally unrelated.
KNN_MIN_SIMILARITY = 0.42
# The winner needs a clear majority of the weighted vote. A split is exactly
# the case where asking the model earns its cost.
KNN_MIN_SHARE = 0.55

SYSTEM_PROMPT = (
    "You are the filing assistant of a personal notebook. Given a note, "
    "choose the single best category for it. Prefer one of the existing "
    "categories; invent a short new category name (1-3 words) only if none "
    'fit. Reply with ONLY JSON like {"category": "...", "confidence": 0-100} '
    "where confidence is how sure you are."
)


@dataclass
class CentroidMatch:
    name: str
    similarity: float


@dataclass
class NeighbourMatch:
    name: str
    confidence: int


logger = logging.getLogger("memorymap.janitor")

#: The `method` values `categorise` returns when the *AI* made the choice, as
#: opposed to the user, a parent note, or nothing being available. A note filed
#: by one of these carries `manager.AUTO_FILED`, which is what makes a later
#: move by hand a correction rather than an ordinary edit (Brief 13). A tuple
#: here rather than a check at each call site so a fourth method added later
#: has one place to be listed.
AI_METHODS = ("semantic-match", "semantic-neighbours", "llm")


def is_ai_method(method: str) -> bool:
    return str(method or "") in AI_METHODS


def categorise(
    session: Session,
    content: str,
    embeddings: EmbeddingService,
    model_manager: ModelManager,
    ollama: OllamaClient,
    exclude_entry_id: int | None = None,
) -> tuple[str, int, str]:
    """Decide (category_name, confidence 0-100, method) for a new note.

    `method` tells the UI how the decision was made: 'semantic-match'
    (embedding centroid, no LLM), 'llm' (asked the chat model), or
    'none' (no AI available).

    When RE-categorising an existing note (add-context), pass
    `exclude_entry_id`, otherwise the note's own stored vector anchors
    it to its old category and it can never move."""
    # **The model decides when there is a model.** This used to run the other
    # way round: a confident centroid match, then nearest neighbours, and the
    # chat model only if both declined, which meant that in an established
    # notebook the AI was almost never consulted at all: there is nearly
    # always *some* category whose vectors sit close to a new note. Reported
    # directly, and the complaint is the right one: "what's the point of
    # having an ai managed notebook if it is filed inaccurately and I need to
    # manually fix it". Vector similarity answers "what does this most
    # resemble", which is not the same question as "where does this belong", 
    # a note about a bug in a work project resembles every other code note
    # more than it resembles the rest of "Work", and gets filed accordingly.
    #
    # The semantic paths below are kept exactly as they were, because they are
    # still the right answer for the case they were really written for: no
    # chat model running, where the alternative is Uncategorised. `_ask_llm`
    # already reports that case as method 'none' (it returns early when
    # `ollama.is_running()` is false, and on any model error or unparseable
    # reply), so "the model had nothing useful to say" and "there is no model"
    # collapse into the same fallback here without a second availability
    # check.
    # The order is a preference, defaulting to the model. Asking the model
    # first buys accuracy and costs a round-trip on every single capture,
    # which on a slow local model is felt immediately, so anyone who would
    # rather have the instant save can have the old order back without giving
    # up the AI entirely (the model still decides everything the vectors
    # decline). Flagged as a real latency change when it shipped; this is the
    # honest fix for it, rather than reverting the accuracy for everyone.
    if not deps.get_config().get_preference("ai_first_filing", True):
        semantic = _semantic_category(
            session, content, embeddings, exclude_entry_id=exclude_entry_id
        )
        if semantic is not None:
            return semantic

    category, confidence, method = _ask_llm(session, content, model_manager, ollama)
    if method != "none":
        # The category can come straight from the chat model, so it is
        # untrusted text on the way to a log line like any other.
        logger.info(
            "janitor: filed by %s -> '%s' (%d%%)",
            method,
            safe_value(category, 60),
            confidence,
        )
        return category, confidence, method

    semantic = _semantic_category(
        session, content, embeddings, exclude_entry_id=exclude_entry_id
    )
    if semantic is not None:
        return semantic

    # Still "filed by <method>", even when the method is 'none'. Reversing the
    # order above briefly replaced this with a differently-worded line, which
    # broke the one thing every filing decision is supposed to leave behind:
    # `test_ai_decisions_are_logged` greps the log console for exactly this
    # prefix, and the Logs tab is where a user finds out *why* a note landed
    # where it did. A decision with no model and no vector match is still a
    # decision, and it is the one most worth being able to see.
    logger.info(
        "janitor: filed by %s -> '%s' (%d%%)",
        method,
        safe_value(category, 60),
        confidence,
    )
    return category, confidence, method


def _semantic_category(
    session: Session,
    content: str,
    embeddings: EmbeddingService,
    exclude_entry_id: int | None = None,
) -> tuple[str, int, str] | None:
    """Filing by vectors alone, or None when neither path is confident.

    One implementation because it is now reached from two directions: as the
    fallback when there is no chat model, and as the *first* attempt when
    `ai_first_filing` is off. Two copies would be two chances for the
    orderings to drift apart.
    """
    match = _best_centroid_match(
        session, content, embeddings, exclude_entry_id=exclude_entry_id
    )
    if match is not None and match.similarity >= CONFIDENT_MATCH:
        confidence = min(100, round(match.similarity * 100))
        logger.info(
            "janitor: filed by semantic match -> '%s' (%d%%)",
            safe_value(match.name, 60),
            confidence,
        )
        return match.name, confidence, "semantic-match"

    # A centroid is the average of a whole category, which is a poor
    # description of any category holding more than one kind of thing: "Work"
    # containing both meeting notes and code snippets has a centroid sitting
    # between them, resembling neither. Individual neighbours don't average
    # away like that.
    neighbours = _knn_match(
        session, content, embeddings, exclude_entry_id=exclude_entry_id
    )
    if neighbours is not None:
        logger.info(
            "janitor: filed by nearest neighbours -> '%s' (%d%%)",
            safe_value(neighbours.name, 60),
            neighbours.confidence,
        )
        return neighbours.name, neighbours.confidence, "semantic-neighbours"
    return None


def _best_centroid_match(
    session: Session,
    content: str,
    embeddings: EmbeddingService,
    exclude_entry_id: int | None = None,
) -> CentroidMatch | None:
    """Compare the note's vector to the average vector (centroid) of each
    existing category. Only vectors from the current backend count."""
    note_vector = embeddings.embed_text(content)
    if note_vector is None:
        return None

    query = (
        select(Category.name, EmbeddingRecord.embedding)
        .join(Entry, Entry.category_id == Category.id)
        .join(EmbeddingRecord, EmbeddingRecord.entry_id == Entry.id)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            EmbeddingRecord.model_version == embeddings.backend_id(),
            Category.name != UNCATEGORISED,  # never gravitate INTO the junk drawer
        )
    )
    if exclude_entry_id is not None:
        query = query.where(Entry.id != exclude_entry_id)
    rows = session.execute(query).all()
    if not rows:
        return None

    vectors_by_category: dict[str, list[np.ndarray]] = {}
    for name, blob in rows:
        vectors_by_category.setdefault(name, []).append(bytes_to_vector(blob))

    best: CentroidMatch | None = None
    for name, vectors in vectors_by_category.items():
        centroid = np.mean(vectors, axis=0)
        similarity = cosine_similarity(note_vector, centroid)
        if best is None or similarity > best.similarity:
            best = CentroidMatch(name=name, similarity=similarity)
    return best


def _knn_match(
    session: Session,
    content: str,
    embeddings: EmbeddingService,
    exclude_entry_id: int | None = None,
) -> NeighbourMatch | None:
    """Vote among the k most similar individual notes.

    Each neighbour votes for its own category, weighted by how similar it is,
    so one very close note outweighs three vague ones. Returns None unless the
    nearest note is genuinely close *and* the winner takes a clear majority, 
    a split vote is the case where asking the model is worth its cost.
    """
    note_vector = embeddings.embed_text(content)
    if note_vector is None:
        return None

    query = (
        select(Category.name, EmbeddingRecord.embedding)
        .join(Entry, Entry.category_id == Category.id)
        .join(EmbeddingRecord, EmbeddingRecord.entry_id == Entry.id)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            # Private notes are excluded from everything the AI touches, and
            # filing is no exception: a category chosen by a private note's
            # neighbours would leak what that note is about.
            Entry.is_private == False,  # noqa: E712
            EmbeddingRecord.model_version == embeddings.backend_id(),
            Category.name != UNCATEGORISED,
        )
    )
    if exclude_entry_id is not None:
        query = query.where(Entry.id != exclude_entry_id)
    rows = session.execute(query).all()
    if not rows:
        return None

    # Was a Python loop calling `cosine_similarity` once per candidate note, 
    # every save paid an unvectorized per-row cost that `embeddings.similar_pairs`
    # already avoids for the equivalent all-pairs comparison. One query vector
    # against N candidates is a single matrix-vector product, not a block sweep
    # (no N² blow-up to guard against the way `similar_pairs` does).
    names = [name for name, _blob in rows]
    matrix = np.stack([bytes_to_vector(blob) for _name, blob in rows]).astype("float32")
    query_vec = note_vector.astype("float32")
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm == 0.0:
        return None  # every pair would score 0, same as the old per-row path
    row_norms = np.linalg.norm(matrix, axis=1)
    similarities = np.divide(
        matrix @ query_vec,
        row_norms * query_norm,
        out=np.zeros(len(rows), dtype="float32"),
        where=row_norms != 0,
    )

    order = np.argsort(-similarities)[:KNN_NEIGHBOURS]
    scored = [(float(similarities[i]), names[i]) for i in order]

    if not scored or scored[0][0] < KNN_MIN_SIMILARITY:
        return None

    votes: dict[str, float] = {}
    for similarity, name in scored:
        if similarity < KNN_MIN_SIMILARITY:
            continue  # too far away to have an opinion
        votes[name] = votes.get(name, 0.0) + similarity
    if not votes:
        return None

    total = sum(votes.values())
    name, weight = max(votes.items(), key=lambda pair: pair[1])
    share = weight / total
    if share < KNN_MIN_SHARE:
        return None

    # Confidence reflects both how close the neighbours are and how much they
    # agree: a unanimous vote among distant notes shouldn't read as certain.
    confidence = round(min(1.0, scored[0][0]) * share * 100)
    return NeighbourMatch(name=name, confidence=max(1, min(100, confidence)))


def _ask_llm(
    session: Session,
    content: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
) -> tuple[str, int, str]:
    if not ollama.is_running():
        return UNCATEGORISED, 0, "none"

    existing = [
        name
        for name in session.scalars(select(Category.name))
        if name != UNCATEGORISED
    ]
    # Built by the librarian, because it now carries more than this function
    # knows about: the corrections the user has already made for these
    # categories (Brief 13). Filing the same kind of note into the same wrong
    # place every week, with the user moving it every week, is the reported
    # failure this answers.
    user_prompt = librarian.filing_prompt(session, content, existing)
    try:
        reply = ollama.chat(
            # Filing is a quick background job, use the utility model so a
            # big slow chat model isn't tied up on every save.
            model_manager.utility_model(),
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        # Thinking models reason before answering; only the answer part
        # can contain the JSON we asked for.
        data = _extract_json(reply["content"])
        category = str(data["category"]).strip()
        if not category:
            raise ValueError("empty category")
        confidence = int(data.get("confidence", 50))
        return category, max(0, min(100, confidence)), "llm"
    except (OllamaError, ValueError, KeyError, TypeError):
        # A confused model must never block a save.
        return UNCATEGORISED, 0, "none"


def _extract_json(text: str) -> dict:
    """Small models often wrap JSON in chatter, grab the {...} part."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in reply: {text!r}")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("reply JSON is not an object")
    return parsed
