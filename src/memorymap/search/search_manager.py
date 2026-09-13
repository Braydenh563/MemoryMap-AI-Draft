"""Find entries two ways.

- Keyword search: word-based and ranked: always works, even with zero AI.
- Semantic search: cosine similarity over stored vectors, needs an
  embedding backend.

`retrieve()` is what /chat uses: semantic when possible, keyword as the
fallback, so asking a question always returns *something* (plan §4).
"""

from __future__ import annotations

import logging
import difflib
import re
from dataclasses import dataclass
from datetime import datetime, time

import numpy as np
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from memorymap.ai.embeddings import (
    EmbeddingService,
    bytes_to_vector,
)
from memorymap.core.database import EmbeddingRecord, Entry, link_strength
from memorymap.search import query as query_understanding

logger = logging.getLogger("memorymap.search")


def _user_today(session: Session):
    """The user's own date, not the server's.

    A question about "yesterday" asked at 00:30 in one timezone is about a
    different day in another, and getting this wrong makes the filter look
    broken in exactly the cases where it matters most.
    """
    try:
        from memorymap.core import deps
        from memorymap.core.config import user_now

        return user_now(deps.get_config()).date()
    except Exception:  # noqa: BLE001  # a script or a test with no app state
        return datetime.now().date()

# Below this cosine similarity a match is probably noise, hide it. An
# absolute floor, kept as a sanity check alongside the relative one below
# (RELATIVE_Z_MARGIN): see semantic_search's own comment on why an
# absolute number alone is not enough for an anisotropic embedding space.
MIN_SIMILARITY = 0.25

# How many standard deviations above this query's own mean score a
# candidate needs to clear the *relative* floor in semantic_search.
RELATIVE_Z_MARGIN = 0.5

# Below this many valid candidate scores, a mean/std is too noisy an
# estimate to reject anything by, semantic_search falls back to
# MIN_SIMILARITY alone.
RELATIVE_MIN_CANDIDATES = 5

# When nothing matches, hand the assistant this many recent entries so
# broad/overview questions ("what have I saved?") still get answered.
RECENT_FALLBACK_LIMIT = 10


def recent_entries(session: Session, limit: int = RECENT_FALLBACK_LIMIT) -> list[Entry]:
    """Most recent non-deleted, non-private entries, newest first."""
    return list(
        session.scalars(
            select(Entry)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
            )
            .order_by(Entry.created_at.desc(), Entry.id.desc())
            .limit(limit)
        )
    )


def keyword_search(session: Session, query: str, limit: int = 10) -> list[Entry]:
    """Find entries by words, best match first.

    This used to be one `LIKE %query%`, which meant the query had to appear as
    a contiguous substring: "proving bread" found nothing even when notes
    contained both words, because the order didn't match. Word order is not
    something anyone should have to guess.

    Now every word must appear somewhere (content or tags), in any order.
    Ranked by SQLite's own FTS5 `bm25()`, real IDF-weighted relevance
    (ROADMAP.md item 32: the previous hand-rolled integer score treated a
    rare, distinctive word the same as a common one), with tag matches
    weighted above a plain content mention, and an exact contiguous phrase
    (checked in Python against the small candidate set FTS already
    narrowed things to, not a second index) breaking ties in front of
    everything else, the same way the old +25 phrase bonus did. When no
    note has all the words, it falls back to notes with *some* of them, a
    partial answer beats an empty page.

    This matters most with no AI running: keyword search is then the whole of
    search, not a fallback.
    """
    terms = _meaningful_terms(query)
    if not terms:
        # Nothing to match on, a question made entirely of common words
        # ("what have I saved so far?") isn't a keyword search at all, and
        # saying so lets the caller fall through to recent notes instead.
        return []

    base = (
        Entry.is_deleted == False,  # noqa: E712
        Entry.is_private == False,  # noqa: E712
    )

    def matching(require_all: bool, words: list[str] | None = None) -> dict[int, float]:
        # `terms` are pre-filtered to \W-stripped words by `_meaningful_terms`,
        # so none of them can contain FTS5 query-syntax characters, safe to
        # join directly rather than needing to quote/escape each one. (A
        # trailing `*` from the prefix stage is FTS5's own prefix operator.)
        match_expr = (" AND " if require_all else " OR ").join(words or terms)
        rows = session.execute(
            text(
                "SELECT rowid, bm25(entries_fts, 1.0, 4.0) AS score "
                "FROM entries_fts WHERE entries_fts MATCH :expr "
                # Over-fetch so ranking (below) has something to choose
                # between; the cut to `limit` happens after, not before.
                "ORDER BY score LIMIT :n"
            ),
            {"expr": match_expr, "n": max(limit * 5, 50)},
        ).all()
        # bm25() is *lower is better*, more negative means more relevant.
        return {row.rowid: row.score for row in rows}

    # Four stages, each only when the one before found nothing, each a
    # little looser: every word exactly → every word as a prefix ("agent"
    # finds "agents", "prov" finds "proving") → every word corrected to the
    # nearest word the notebook actually contains ("sourdogh" → "sourdough")
    # → any of the words. Asked for as "search tolerant of spelling
    # mistakes": a student typing fast should not get an empty page for one
    # transposed letter, and the FTS index already knows every word it has.
    phrase_terms = terms
    scores = matching(require_all=True)
    if not scores:
        prefixed = [f"{t}*" if len(t) >= PREFIX_MIN_LEN else t for t in terms]
        if prefixed != terms:
            scores = matching(require_all=True, words=prefixed)
    if not scores:
        corrected = _corrected_terms(session, terms)
        if corrected != terms:
            scores = matching(require_all=True, words=corrected)
            if scores:
                phrase_terms = corrected
    if not scores:
        scores = matching(require_all=False)
    if not scores:
        return []

    entries = list(session.scalars(select(Entry).where(*base, Entry.id.in_(scores))))
    phrase = " ".join(phrase_terms)

    def sort_key(entry: Entry) -> tuple[int, float, int]:
        has_phrase = phrase in re.sub(r"\W+", " ", (entry.content or "").lower())
        return (0 if has_phrase else 1, scores.get(entry.id, 0.0), -entry.id)

    entries.sort(key=sort_key)
    return entries[:limit]


# A query word this long or longer is also tried as a prefix when nothing
# matched it whole. Three letters would turn "the" into "the*" and match
# "theory", "thermal", "these", a prefix that short is noise, not intent.
PREFIX_MIN_LEN = 4
# Only words this long are ever "corrected": a three-letter word is one
# edit from dozens of others, and difflib's ratio cannot tell them apart.
CORRECT_MIN_LEN = 4
# difflib ratio floor for treating a vocabulary word as the query word
# misspelt: 0.8 is roughly one wrong letter in five, two in ten.
CORRECT_CUTOFF = 0.8


def _corrected_terms(session: Session, terms: list[str]) -> list[str]:
    """Each term replaced by the closest word the FTS index holds, when it
    holds no such word itself. Terms already in the vocabulary, and short
    terms, are returned unchanged.

    Reads `entries_fts_vocab` (database.py) one first-letter range at a time
    - a few hundred candidates at most, and lets `difflib` pick. Nothing
    here is cleverer than that on purpose: it can only ever propose a word
    that is actually in a note, so a wrong correction still lands on real
    text rather than inventing a match."""
    corrected: list[str] = []
    for term in terms:
        if len(term) < CORRECT_MIN_LEN:
            corrected.append(term)
            continue
        first = term[0]
        try:
            rows = session.execute(
                text(
                    "SELECT term FROM entries_fts_vocab "
                    "WHERE term >= :lo AND term < :hi"
                ),
                {"lo": first, "hi": chr(ord(first) + 1)},
            ).all()
        except Exception:  # noqa: BLE001 - an older database without the vocab table
            return terms
        vocabulary = [row.term for row in rows]
        if term in vocabulary:
            corrected.append(term)
            continue
        near = [w for w in vocabulary if abs(len(w) - len(term)) <= 2]
        close = difflib.get_close_matches(term, near, n=1, cutoff=CORRECT_CUTOFF)
        corrected.append(close[0] if close else term)
    return corrected


#: The stopword list and the term splitter both moved to `search/query.py`,
#: which is the floor both searches share (see its own comment on the import
#: cycle that made the move necessary).
#:
#: A `_STOPWORDS = query_understanding.STOPWORDS` alias stood here for one
#: commit, kept "under the name eighty lines of this file and
#: `ai/grounding.py` already use". That was true before the move and false
#: after it: the same commit rewrote every one of those call sites to go
#: through `search_terms`, so the alias was read by nothing. CodeQL said so
#: (alert 402, unused global) and a grep agreed, which is the whole value of
#: that check: a name kept for compatibility is worth keeping only while
#: something is compatible with it.


def _meaningful_terms(query: str) -> list[str]:
    """Search words worth matching on, in order. See `query.search_terms`."""
    return query_understanding.search_terms(query)


def configured_thresholds() -> tuple[float, float]:
    """(min_similarity, relative_z_margin), from user preferences if set,
    the module defaults otherwise. One place for every real caller (the API
    routes, /chat's retrieve() below) to read these, so semantic_search
    itself stays a pure function of its arguments, no hidden global-state
    dependency for a bare-session test to trip over."""
    from memorymap.core import deps

    config = deps.get_config()
    return (
        config.get_preference("search_min_similarity", MIN_SIMILARITY),
        config.get_preference("search_relative_z_margin", RELATIVE_Z_MARGIN),
    )


def semantic_search(
    session: Session,
    query: str,
    embeddings: EmbeddingService,
    limit: int = 5,
    min_similarity: float = MIN_SIMILARITY,
    relative_z_margin: float = RELATIVE_Z_MARGIN,
) -> list[tuple[Entry, float]] | None:
    """Best-matching entries with scores, or None when embeddings are
    unavailable (caller should fall back to keyword search).

    The MVP compared against every stored vector *and joined in the full
    `Entry` for each one* in Python, this docstring used to say "revisit
    only if it ever feels slow", and ANALYSIS.md §34's scale-test found it
    does: materialising every entry as an ORM object just to score and throw
    most of them away was ~85% of one search's cost at 20k+ notes (~6.6s of
    a ~7.3s call at 50k). The vector scan itself is still brute-force, there
    is no index to avoid it, but scoring needs only `(entry_id, embedding)`
    tuples, not full mapped entities, so that part is now a plain column
    query and only the handful of notes that actually rank get a real
    `Entry` fetched."""
    query_vector = embeddings.embed_text(query)
    if query_vector is None:
        return None

    records = session.execute(
        select(EmbeddingRecord.entry_id, EmbeddingRecord.embedding).where(
            # Vectors from other backends live in a different space, 
            # comparing them would give nonsense (plan §6.5).
            EmbeddingRecord.model_version
            == embeddings.backend_id()
        )
    ).all()

    if not records:
        return []

    query_norm = float(np.linalg.norm(query_vector))
    if query_norm == 0:
        return []

    # One matrix multiply instead of a Python loop of dot products, the scan
    # is still brute-force, but NumPy does it at memory speed.
    #
    # Only over the rows whose vector is the same width as the query, though.
    # `model_version` narrows this to one backend, and a backend is not a
    # dimension: swapping the embedding *model* inside the same backend (which
    # Settings → Embedding models offers as a button) leaves the old rows in
    # place at their old width. Stacking those into one array raises on the
    # ragged list and took the whole search down with it, every query
    # returning nothing, until a reindex that the error gave no hint to run.
    # Mismatched rows are skipped instead; they get their real scores back as
    # the reindex refills them.
    by_width: dict[int, list[tuple[int, np.ndarray]]] = {}
    for entry_id, blob in records:
        vector = bytes_to_vector(blob)
        by_width.setdefault(vector.shape[0], []).append((entry_id, vector))

    usable = by_width.get(query_vector.shape[0], [])
    if not usable:
        logger.warning(
            "no stored vectors match the query's %d dimensions (widths present: %s) "
            ", reindex to score these notes again",
            query_vector.shape[0],
            sorted(by_width),
        )
        return []
    if len(usable) < len(records):
        logger.info(
            "%d of %d vectors are a different width and were skipped, reindex to include them",
            len(records) - len(usable),
            len(records),
        )

    entry_ids = [entry_id for entry_id, _ in usable]
    vectors = np.stack([vector for _, vector in usable])

    norms = np.linalg.norm(vectors, axis=1)
    valid = norms > 0

    scores = np.zeros(len(vectors), dtype="float32")
    if np.any(valid):
        scores[valid] = np.dot(vectors[valid], query_vector) / (norms[valid] * query_norm)

    # MIN_SIMILARITY alone assumes "0.25" means the same thing regardless of
    # which embedding model produced the vectors, it does not. A BGE-family
    # model (the current DEFAULT_ST_MODEL, embeddings.py) is anisotropic:
    # its vectors cluster in a narrow cone, so two genuinely unrelated notes
    # routinely land at 0.4-0.6 cosine similarity, nowhere near the "0 is
    # unrelated" an absolute floor implicitly assumes. Reported live: an
    # unrelated note scored 57% for an unconnected query, comfortably above
    # this floor. MIN_SIMILARITY predates that model (the built-in default
    # was all-MiniLM before it, which does not have anisotropy to nearly the
    # same degree: see embeddings.py's own comment on the switch) and was
    # never recalibrated.
    #
    # Rather than guess a new fixed number for BGE specifically, unverified
    # in this sandbox, which cannot run sentence-transformers at all per
    # CLAUDE.md: this adds a second, *relative* floor from the query's own
    # score distribution: a candidate has to beat what an unrelated note
    # typically scores for THIS query, not just clear an absolute number
    # picked for a different model. Self-calibrating regardless of backend,
    # and it degrades to "floor only" (relative_floor = -inf) when there
    # are too few candidates for a mean/std to mean anything, a two-note
    # notebook has no "typical unrelated score" to measure against.
    valid_scores = scores[valid]
    if valid_scores.size >= RELATIVE_MIN_CANDIDATES:
        relative_floor = float(np.mean(valid_scores) + relative_z_margin * np.std(valid_scores))
    else:
        relative_floor = float("-inf")

    scored_ids = [
        (entry_ids[i], float(scores[i]))
        for i in range(len(entry_ids))
        if scores[i] >= min_similarity and scores[i] >= relative_floor
    ]
    scored_ids.sort(key=lambda pair: pair[1], reverse=True)
    if not scored_ids:
        return []

    # A generous pool before the is_deleted filter below: a deleted note's
    # embedding can still be sitting in the table (nothing prunes it), and
    # over-fetching candidates is cheap next to under-returning matches.
    candidates = scored_ids[: max(limit * 4, 40)]
    entries_by_id = {
        e.id: e
        for e in session.scalars(
            select(Entry).where(
                Entry.id.in_([eid for eid, _ in candidates]),
                Entry.is_deleted == False,  # noqa: E712
            )
        )
    }
    result = [
        (entries_by_id[eid], score) for eid, score in candidates if eid in entries_by_id
    ]
    return result[:limit]


# --- fusing the two searches ---------------------------------------------------
#
# The old rule was either/or: semantic won outright, and keyword was only
# consulted when semantic came back empty. That loses in both directions, and
# each failure is one a person notices immediately.
#
# - A note containing the query **verbatim** loses to three notes that are
#   vaguely on topic, because 0.31 cosine beats 0.28 and the exact match was
#   never in the running. Searching for a phrase you know you wrote and not
#   getting it is the single most damaging thing a notebook search can do.
# - A misspelling, a synonym, or a question phrased differently from the note
#   ("how do I prove dough" vs "bread rising times") is exactly what semantic
#   search is *for*, and it was being discarded whenever the keyword branch
#   happened to fire first.
#
# Reciprocal rank fusion combines the two by **rank** rather than by score,
# which is what makes it robust here: a cosine similarity and a keyword tally
# are not on the same scale and never will be, so any weighted sum of the two
# needs a tuning constant per notebook. RRF needs none: it only asks "how near
# the top of each list did this note come?"
RRF_K = 10

# How deep each ranking is read before fusing. Deeper than the number returned,
# because the whole point is that a note ranked 8th by meaning and 3rd by words
# can beat one ranked 2nd by meaning and nowhere by words.
FUSION_DEPTH = 20


def _recency_pin_ranking(entries: list[Entry]) -> list[Entry]:
    """The same candidates, reordered by pinned-first then most-recently-
    touched: a third vote for `_fuse` rather than a new source of matches.

    BACKLOG.md §95 item B.6, asked for directly: "search ranks by relevance;
    it does not know that a note pinned last week matters more than a
    relevant one from 2023." Both columns already existed (`Entry.pinned`,
    `Entry.updated_at`); nothing read them at search time.

    Deliberately a *reorder of the candidates a real search already found*,
    never a fresh query, a pinned note that has nothing to do with the
    question is not a better answer to it, so this only ever influences
    ranking among notes that already matched by meaning or by word. Fed into
    `_fuse` exactly like the semantic and keyword rankings: by rank
    position, not a weighted score, for the same reason those two are (see
    RRF_K's own comment): "how recently pinned" and "how many days old"
    are not on a shared scale with cosine similarity or a BM25 tally, and a
    weighted sum of the three would need a tuning constant this notebook has
    no way to pick.
    """
    return sorted(
        entries,
        key=lambda entry: (not entry.pinned, -(entry.updated_at or entry.created_at).timestamp()),
    )


def _fuse(ranked_lists: list[list[Entry]], limit: int) -> list[Entry]:
    """Reciprocal rank fusion over several rankings of the same notes."""
    scores: dict[int, float] = {}
    seen: dict[int, Entry] = {}
    for ranking in ranked_lists:
        for position, entry in enumerate(ranking[:FUSION_DEPTH]):
            scores[entry.id] = scores.get(entry.id, 0.0) + 1.0 / (RRF_K + position + 1)
            seen.setdefault(entry.id, entry)
    order = sorted(scores, key=lambda note_id: (-scores[note_id], -note_id))
    return [seen[note_id] for note_id in order[:limit]]


# How many notes the graph is allowed to add to an answer's context, and how
# many of the top hits it walks out from.
#
# **This is what makes the app a memory *map* rather than a search box.** A
# question retrieves the notes that match it; the notes those *link to* are
# very often where the answer actually is, you wrote the question's subject in
# one note and the thing you need in the note you linked from it. That
# connection is the structure the whole app is built around, and until now no
# answer used it: only the agent could walk links, and only when it thought to.
#
# Deliberately small, and deliberately at the end of the list. These are
# context, not matches: they earned their place by being connected to
# something that matched, which is weaker evidence than matching. A large
# expansion would push real matches out of a budgeted prompt to make room for
# notes nobody searched for.
GRAPH_EXPANSION_SEEDS = 3
GRAPH_EXPANSION_LIMIT = 3
# ROADMAP.md item 33: a second hop, opt-in by being small and automatic
# rather than a user-visible "search deeper" action: the roadmap left that
# choice open; automatic is the one that needs no new UI and degrades to
# "just doesn't add much" rather than "a control nobody found". Smaller than
# the first hop on purpose: a neighbour-of-a-neighbour is weaker evidence
# again, verified the same way (still a real link, still carries its own
# reason if it has one) but two links removed from what was actually asked.
GRAPH_EXPANSION_HOP2_LIMIT = 2


def _linked_neighbours(
    session: Session, seeds: list[int], exclude: set[int]
) -> tuple[list[int], dict[int, str]]:
    """One hop of `graph_expansion`'s own walk: links plus reply threads,
    strongest first (ties in the order found). Factored out so a second hop
    can call it again starting from the first hop's own results, rather than
    duplicating the walk.

    Ordering matters here specifically because both `GRAPH_EXPANSION_LIMIT`
    and `GRAPH_EXPANSION_HOP2_LIMIT` truncate this list: §87.5's payoff for
    this side is which neighbours *survive* that truncation, not just how
    they're labelled.
    """
    from memorymap.core.database import EntryLink

    neighbours: list[int] = []
    reasons: dict[int, str] = {}
    # A reply/parent thread has no EntryLink to read a type or confidence
    # off, so it gets no entry here, the sort below falls back to 1.0 for
    # it, the same baseline `entry/paths.py`'s THREAD_WEIGHT == LINK_WEIGHT
    # already treats a reply and a bare link as equally strong.
    strengths: dict[int, float] = {}
    if not seeds:
        return neighbours, reasons

    links = session.scalars(
        select(EntryLink).where(
            or_(
                EntryLink.source_entry_id.in_(seeds),
                EntryLink.target_entry_id.in_(seeds),
            )
        )
    )
    for link in links:
        strength = link_strength(link.link_type, link.reason_confidence)
        for end in (link.source_entry_id, link.target_entry_id):
            if end in exclude:
                continue
            if end not in neighbours:
                neighbours.append(end)
                if link.reason:
                    reasons[end] = link.reason
            # A neighbour reachable by more than one link (from different
            # seeds, say) is scored by its strongest connection, not its
            # first-seen one.
            strengths[end] = max(strengths.get(end, 0.0), strength)
    # Replies, both directions: a thread is one train of thought, so the note
    # that answers the match is as relevant as the one it answers.
    for entry in session.scalars(
        select(Entry).where(Entry.parent_id.in_(seeds), Entry.is_deleted == False)  # noqa: E712
    ):
        if entry.id not in exclude and entry.id not in neighbours:
            neighbours.append(entry.id)
    # The seeds' own parents, in one query rather than one `session.get` each
    #, same reasoning as `semantic_search`'s own docstring on avoiding
    # per-row fetches.
    for parent_id in session.scalars(
        select(Entry.parent_id).where(Entry.id.in_(seeds), Entry.parent_id.is_not(None))
    ):
        if parent_id not in exclude and parent_id not in neighbours:
            neighbours.append(parent_id)
    neighbours.sort(key=lambda n: strengths.get(n, 1.0), reverse=True)
    return neighbours, reasons


def graph_expansion(
    session: Session, matches: list[Entry], limit: int = GRAPH_EXPANSION_LIMIT
) -> tuple[list[Entry], dict[int, str], dict[int, int]]:
    """Notes connected to the best matches, nearest first, plus *why*, a
    link's own reason, keyed by neighbour id, for the ones that have one, 
    and *how far*, keyed the same way (1 = directly linked to a match, 2 =
    linked to one of those). Only the one caller (`_retrieve`) reads either
    extra dict; the reason is what lets the "linked to a match" badge say
    what the link actually is instead of just that one exists (asked for
    directly: "does the reason in the links show in [connected results] as
    well?", it didn't, this is that gap closed), and the hop count is what
    lets a second-hop note render as a visibly weaker tier rather than
    merged in with the first hop's (ROADMAP.md item 33).

    Links and reply threads only, not shared tags. A tag is a filing label
    that can put fifty unrelated notes one hop apart, and the same reasoning
    that made `entry/paths.py` weight tag steps down applies with more force
    here: this list goes straight into a prompt, where a weak connection is
    indistinguishable from a strong one.
    """
    if not matches:
        return [], {}, {}

    have = {entry.id for entry in matches}
    seeds = [entry.id for entry in matches[:GRAPH_EXPANSION_SEEDS]]
    hop1, reasons = _linked_neighbours(session, seeds, have)

    hop2: list[int] = []
    if hop1 and GRAPH_EXPANSION_HOP2_LIMIT:
        hop2_all, hop2_reasons = _linked_neighbours(
            session, hop1[:GRAPH_EXPANSION_SEEDS], have | set(hop1)
        )
        hop2 = hop2_all[:GRAPH_EXPANSION_HOP2_LIMIT]
        for note_id in hop2:
            if note_id in hop2_reasons:
                reasons[note_id] = hop2_reasons[note_id]

    neighbours = hop1 + hop2
    if not neighbours:
        return [], {}, {}
    found = list(
        session.scalars(
            select(Entry).where(
                Entry.id.in_(neighbours),
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
            )
        )
    )
    # Back into the order the walk found them, so the nearest neighbour of the
    # best match comes first rather than whatever the database returned.
    by_id = {entry.id: entry for entry in found}
    hop_of = {note_id: 1 for note_id in hop1} | {note_id: 2 for note_id in hop2}
    ordered_hop1 = [by_id[note_id] for note_id in hop1 if note_id in by_id][:limit]
    ordered_hop2 = [
        by_id[note_id] for note_id in hop2 if note_id in by_id
    ][:GRAPH_EXPANSION_HOP2_LIMIT]
    ordered = ordered_hop1 + ordered_hop2
    return (
        ordered,
        {e.id: reasons[e.id] for e in ordered if e.id in reasons},
        {e.id: hop_of[e.id] for e in ordered},
    )


def in_range(
    session: Session, since, until, limit: int = 25
) -> list[Entry]:
    """Every note written in a date range, newest first.

    The answer to a question that is *only* about time, "what did I save last
    week?", where ranking by similarity would be ranking noise: there is no
    subject to be similar to.
    """
    clauses = [
        Entry.is_deleted == False,  # noqa: E712
        Entry.is_private == False,  # noqa: E712
    ]
    if since is not None:
        clauses.append(Entry.created_at >= datetime.combine(since, time.min))
    if until is not None:
        clauses.append(Entry.created_at <= datetime.combine(until, time.max))
    return list(
        session.scalars(
            select(Entry)
            .where(*clauses)
            .order_by(Entry.created_at.desc(), Entry.id.desc())
            .limit(limit)
        )
    )


def _written_at(entry: Entry):
    """When a note was written, for sorting. A note with no timestamp sorts
    oldest rather than crashing the comparison, the same choice `_within`
    makes when it keeps an undated note rather than filtering on an absence."""
    written = getattr(entry, "created_at", None)
    return written or datetime.min


def _within(entry: Entry, since, until) -> bool:
    """Was this note written in the range? Notes with no timestamp are kept, 
    dropping a note because its date is missing would be filtering on an
    absence rather than on a fact."""
    written = getattr(entry, "created_at", None)
    if written is None:
        return True
    day = written.date() if hasattr(written, "date") else written
    if since is not None and day < since:
        return False
    if until is not None and day > until:
        return False
    return True


@dataclass
class Retrieval:
    """What a search found, and how, everything `retrieve` knows.

    A separate shape rather than a wider tuple because the *provenance* is the
    part that matters to the model: a note that arrived because it is linked to
    a match is context, and reporting it as a search hit is the same class of
    mistake as calling a shared tag a link. The two-value `retrieve()` below
    stays exactly as it was for everything that only wants the notes.
    """

    entries: list[Entry]
    mode: str
    #: Ids that came from the graph walk rather than from either search.
    connected_ids: set[int]
    #: The date range applied, and the phrase it came from, or None.
    since: object = None
    until: object = None
    when_phrase: str = ""
    #: Why each entry is here, keyed by id, e.g. {"type": "semantic",
    #: "score": 0.81} or {"type": "keyword", "terms": ["gym"]}. Built from
    #: information `_rank`/`_fuse` would otherwise discard once they've
    #: collapsed two ranked lists into one ordered-by-relevance list of
    #: entries. Best-effort: an id with no entry here matched by whatever
    #: `mode` alone already says (`dated`, `recent`, `attached`, …).
    match_info: dict = None

    def __post_init__(self) -> None:
        if self.match_info is None:
            self.match_info = {}


def retrieve_detailed(
    session: Session,
    query: str,
    embeddings: EmbeddingService,
    limit: int = 5,
    expand_graph: bool = True,
) -> Retrieval:
    """`retrieve`, with the provenance kept. See `Retrieval`."""
    found: dict = {}
    entries, mode = _retrieve(
        session, query, embeddings, limit, expand_graph, found
    )
    return Retrieval(
        entries=entries,
        mode=mode,
        connected_ids=found.get("connected", set()),
        since=found.get("since"),
        until=found.get("until"),
        when_phrase=found.get("when_phrase", ""),
        match_info=found.get("match_info", {}),
    )


def retrieve(
    session: Session,
    query: str,
    embeddings: EmbeddingService,
    limit: int = 5,
    expand_graph: bool = True,
) -> tuple[list[Entry], str]:
    """Entries for a question + how they were found, so the UI can be honest.

    Modes: `hybrid` (both searches agreed on a ranking), `semantic`, `keyword`,
    `recent` (a broad question matched nothing specific, so the notebook must
    not look empty), `dated` (the question was about *when*), or `none`.

    `expand_graph` adds notes *connected* to the matches, see
    `graph_expansion`. On by default because it is the app's whole premise;
    switched off by callers that want the matches alone, such as a duplicate
    check, where a linked note is not a candidate for anything.

    `retrieve_detailed` above is the same search with the provenance kept.
    """
    return _retrieve(session, query, embeddings, limit, expand_graph, {})


def _rank(
    semantic: list[tuple[Entry, float]] | None, keyword: list[Entry], limit: int
) -> tuple[list[Entry], str]:
    """Combine a semantic and a keyword result list into one ranked answer,
    with an honest label for how it was found. Factored out so the
    date-range fallback in `_retrieve` (searching again with the same two
    lists, minus the range) can reuse it instead of repeating the branch."""
    if semantic is None:
        # No embedding backend at all: keyword search is the whole of search,
        # not a fallback, and saying "keyword" is the honest label.
        return keyword[:limit], "keyword"
    if semantic and keyword:
        sem_entries = [entry for entry, _s in semantic]
        # The pool both searches already agreed is relevant, recency/pin
        # only ever reorders within it, see _recency_pin_ranking's own
        # docstring on why that scope matters.
        candidates = {entry.id: entry for entry in [*sem_entries, *keyword]}.values()
        return (
            _fuse(
                [sem_entries, keyword, _recency_pin_ranking(list(candidates))],
                limit,
            ),
            "hybrid",
        )
    if semantic:
        return [entry for entry, _s in semantic][:limit], "semantic"
    return keyword[:limit], "keyword"


def _retrieve(
    session: Session,
    query: str,
    embeddings: EmbeddingService,
    limit: int,
    expand_graph: bool,
    found: dict,
) -> tuple[list[Entry], str]:
    """The search itself. `found` is filled in with what happened, for
    `retrieve_detailed`; the plain caller passes a dict it throws away."""
    # What the question is actually asking. A time phrase becomes a filter
    # instead of search terms, and the question's scaffolding comes off before
    # anything is embedded: see `search/query.py` for why both matter.
    asked = query_understanding.understand(query, _user_today(session))
    found["since"] = asked.since
    found["until"] = asked.until
    found["when_phrase"] = asked.when_phrase
    found["connected"] = set()
    if asked.time_only:
        # Nothing but a date range: list it. Ranking by similarity here would
        # be ranking noise, and the honest answer to "what did I write last
        # week" is *the notes from last week*, in order.
        dated = in_range(session, asked.since, asked.until)
        if dated:
            return _without_private(dated)[: max(limit, 10)], "dated"
        # An empty week is a real answer, but an empty *list* looks like a
        # failure: fall through so the caller still gets recent notes.

    # Searching for the subject rather than the sentence. Falls back to the
    # whole question when stripping left nothing to search for.
    subject = asked.subject or query
    _min_sim, _z_margin = configured_thresholds()
    semantic = semantic_search(
        session, subject, embeddings, limit=FUSION_DEPTH,
        min_similarity=_min_sim, relative_z_margin=_z_margin,
    )
    keyword = keyword_search(session, subject, limit=FUSION_DEPTH)
    # Kept before the range narrows them below, so a subject match outside
    # the stated window is still reachable as a fallback (see "outside the
    # window you named" further down) without a second, identical search.
    semantic_any_time, keyword_any_time = semantic, keyword
    # Captured here, before range-filtering or `_rank`/`_fuse` collapse both
    # lists into one ordered-by-relevance list of entries and lose the
    # per-entry detail: a cosine score means something, a fused rank
    # position doesn't. Range-filtering only removes candidates, never
    # changes their score, so looking these up by id later stays correct
    # regardless of what the caller keeps or drops afterwards.
    sem_scores = {entry.id: score for entry, score in semantic} if semantic is not None else {}
    kw_terms = _meaningful_terms(subject)

    # A range alongside a subject narrows the candidates before they are
    # ranked, so "the allotment, last week" cannot be answered with a note from
    # March that happens to be a better match.
    #
    # **Except when the range is soft.** "Recently" is a lean, not a boundary, 
    # see `Understood.soft`, and filtering on it is what made "jokes I have
    # saved recently" come back with a note about a gym routine: the two notes
    # tagged `jokes` were 16 and 30 days old, the fortnight window dropped both,
    # and the empty-handed fallback below listed whatever *was* in the window.
    # A soft range still sorts (newest first, below) and still labels; it does
    # not exclude.
    if asked.has_range and not asked.soft:
        if semantic is not None:
            semantic = [
                (entry, score)
                for entry, score in semantic
                if _within(entry, asked.since, asked.until)
            ]
        keyword = [e for e in keyword if _within(e, asked.since, asked.until)]
    elif asked.soft:
        # Recency as a tiebreak rather than a gate: of the notes that match the
        # subject, the newer ones come first, which is the whole of what the
        # word was asking for.
        keyword = sorted(keyword, key=_written_at, reverse=True)
        if semantic is not None:
            semantic = sorted(semantic, key=lambda pair: _written_at(pair[0]), reverse=True)

    entries, mode = _rank(semantic, keyword, limit)

    if not entries:
        # Nothing matched. The "never look empty" fallback is recent notes, 
        # but **not when the question named a date range.** "What did I write
        # about the allotment last week", with nothing about the allotment that
        # week, would otherwise come back with unrelated notes from any time at
        # all, labelled `recent`, silently dropping the one constraint the
        # person actually stated. Answering the wrong question confidently is
        # worse than answering none.
        #
        # So a dated question that finds nothing falls back *within its range*,
        # and if the range is genuinely empty it returns nothing and says
        # `dated`, which is a true answer the caller can render as "nothing
        # that week".
        #
        # **Only when the question was about time alone.** With a subject, this
        # fallback drops the more specific of the two constraints and hands
        # back every note in the window, which is how "jokes I have saved
        # recently" was answered with a gym routine. Listing the window is a
        # true answer to "what did I write last week"; presented as the answer
        # to "which jokes", it is a confident answer to a question nobody
        # asked, and the person has no way to tell it apart from a real hit.
        # Nothing, labelled `dated`, is the honest reply, and the caller
        # renders it as "nothing about that in this window".
        if asked.has_range and not asked.subject:
            in_window = in_range(session, asked.since, asked.until, limit=limit)
            return _without_private(in_window), "dated"
        if asked.has_range:
            # A subject was named and nothing matched it *inside* the
            # window: reported directly: a note tagged joke/jokes/funny,
            # asked about as "two weeks ago", was actually written three
            # weeks ago, and came back empty rather than found-but-
            # mislabelled. This is not the fallback rejected above: that one
            # dropped the *subject* and kept the date ("jokes... recently"
            # answered with a gym routine); this drops the date and keeps
            # the subject, so it can never return something unrelated to
            # what was asked for, only the same match, outside the window
            # the person's memory of *when* turned out to be wrong about.
            #
            # **Bounded, not unbounded**: widened by the window's own span
            # rather than searched across the whole notebook. Without a
            # bound this reintroduces the *other* shape of the rejected
            # fallback: "the allotment, last week" must still answer nothing
            # when the only allotment note is three months old, the same
            # test that pins the fallback above pins this one too (a
            # subject match 90 days from a 7-day window is not "the person's
            # memory was a little off", it's a different note weighing in
            # on a question it wasn't asked). "Two weeks" that was actually
            # three is one window-span away; that's the case this catches.
            since_wide = asked.since - (asked.until - asked.since) if asked.since and asked.until else asked.since
            until_wide = asked.until + (asked.until - asked.since) if asked.since and asked.until else asked.until
            outside, _mode = _rank(
                [(e, s) for e, s in semantic_any_time if _within(e, since_wide, until_wide)]
                if semantic_any_time is not None
                else None,
                [e for e in keyword_any_time if _within(e, since_wide, until_wide)],
                limit,
            )
            if outside:
                return _without_private(outside), "outside_range"
            return [], "dated"
        recent = recent_entries(session, limit=RECENT_FALLBACK_LIMIT)
        if recent:
            return _without_private(recent), "recent"

    entries = _without_private(entries)
    # Why each of these is here, built before graph expansion appends any
    # connected notes, so "connected" always wins over an incidental keyword
    # overlap for those (a neighbour that also happens to share a word with
    # the question is still here *because it's linked*, not because it
    # matched).
    match_info = {}
    for entry in entries:
        content = (entry.content or "").lower()
        matched_terms = [t for t in kw_terms if t in content]
        if entry.id in sem_scores and matched_terms:
            match_info[entry.id] = {
                "type": "hybrid",
                "score": round(sem_scores[entry.id], 2),
                "terms": matched_terms,
            }
        elif entry.id in sem_scores:
            match_info[entry.id] = {"type": "semantic", "score": round(sem_scores[entry.id], 2)}
        elif matched_terms:
            match_info[entry.id] = {"type": "keyword", "terms": matched_terms}
    if expand_graph and entries:
        # Appended, never interleaved: a connected note is context and a match
        # is an answer, and a prompt that has to drop something should drop the
        # context first. The order encodes that.
        neighbours, neighbour_reasons, neighbour_hops = graph_expansion(session, entries)
        for neighbour in neighbours:
            if all(neighbour.id != entry.id for entry in entries):
                entries.append(neighbour)
                found["connected"].add(neighbour.id)
                # A second-hop note (item 33) is real evidence but weaker, 
                # linked to something linked to a match, not to the match
                # itself: so it gets its own badge type rather than being
                # indistinguishable from a direct neighbour.
                two_hops = neighbour_hops.get(neighbour.id) == 2
                info = {"type": "connected_2hop" if two_hops else "connected"}
                if neighbour.id in neighbour_reasons:
                    info["reason"] = neighbour_reasons[neighbour.id]
                match_info[neighbour.id] = info
    found["match_info"] = match_info

    # One final filter covering every mode. Private notes are also excluded by
    # the individual queries and have no embeddings to match on, but retrieval
    # feeds the AI's context: a single missed path would hand a private note
    # to the model, so it's checked once more here where every route converges.
    return _learned_order(session, query, _without_private(entries)), mode


def _learned_order(session: Session, query: str, entries: list[Entry]) -> list[Entry]:
    """Move what the person opened last time a question like this was asked.

    WORLD_CLASS_PLAN I7. The ranking above has no memory: asked the same
    question next week it returns the same order, including the order that
    was wrong enough that the person scrolled past the first result to open
    the third. An `open_after_ask` correction records which one they opened,
    and this puts it back on top.

    Deliberately a *reorder of what was already found*, never an addition: a
    boost that could inject a note the search did not match would make one
    click permanently change what the notebook appears to contain, which is
    the failure mode of every recommender that learns too eagerly. If the
    note is not in this result, it stays out of it.

    "A question like this" is word overlap against the recorded question, so
    "sourdough notes" and "my sourdough notes" are the same question and
    "sourdough" and "tax return" are not. Half the recorded question's words,
    at least one, which is strict enough that two unrelated questions sharing
    "notes" do not match.
    """
    if not entries:
        return entries
    importlib = __import__("importlib")
    # Imported at the call site: `search` is imported by `ai`, so a module
    # level `from memorymap.ai import learning` here is a cycle, and
    # `tests/test_no_import_cycles.py` counts the statement wherever it sits.
    learning = importlib.import_module("memorymap.ai.learning")
    boosts = learning.boosts(session, kind="search")
    if not boosts:
        return entries
    asked = learning._words(query)
    if not asked:
        return entries
    by_id = {entry.id: entry for entry in entries}
    promoted: list[tuple[float, int]] = []
    for (question, entry_id), weight in boosts.items():
        if entry_id not in by_id:
            continue
        words = learning._words(question)
        if not words:
            continue
        shared = len(words & asked)
        if shared and shared * 2 >= len(words):
            promoted.append((weight, entry_id))
    if not promoted:
        return entries
    promoted.sort(reverse=True)
    order = [by_id[entry_id] for _weight, entry_id in promoted]
    seen = {entry.id for entry in order}
    order.extend(entry for entry in entries if entry.id not in seen)
    return order


def _without_private(entries: list[Entry]) -> list[Entry]:
    return [entry for entry in entries if not getattr(entry, "is_private", False)]
