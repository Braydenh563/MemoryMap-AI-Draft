"""The retrieval engine: one search, three signals, every hit explained.

WORLD_CLASS_PLAN B3, SESSION_BRIEFS Brief 11, spec in
`tests/test_search_engine_spec.py`.

One `search()` over every kind, answering with `Hit`s that carry all three of
their scores rather than one blended number. That is the part worth stating
plainly: **"why this result" is a rendering here, not a guess.** The list can
say "matched the title, similar meaning, linked to the note you have open"
because those three numbers came back with the row, and a person who disagrees
with the ranking can see which signal did it.

The three signals, and where each comes from:

- **bm25**, from `search_index` (`search/index.py`), which covers notes,
  documents, boards, files' extracted text, bookmarks and reminders. SQLite's
  own IDF-weighted relevance, no dependency, and the only signal that works
  with the model switched off, which is why it carries the most weight.
- **cosine**, from the vectors already stored in `embeddings`, through the
  process-level matrix below. The matrix is the change: `semantic_search`
  selects every `EmbeddingRecord` row on **every request** and stacks them
  into a fresh array each time (ANALYSIS §34 measured the older, worse version
  of that at ~7s on 50k notes). Here the array is built once and kept up to
  date by the writes themselves.
- **graph proximity** to what the person is looking at: 1 / (1 + hops) over
  the link tables, at most two hops, computed only for the candidates that
  already matched. A note linked to the note you have open is a better answer
  to a question you asked while reading it, and no amount of text similarity
  knows that.

What this does **not** replace: `search_manager.retrieve()` is what /chat
uses, and it stays. It fuses keyword and semantic results by rank, expands the
graph for context and reads a question's time phrases, all of which is tuned
against its own tests. This engine is the *search surface*: one query, every
kind, explained, fast. The two share `search/query.py` (one parser) and this
module reuses `search_manager`'s stopword list and term splitter rather than
writing a second one.
"""
from __future__ import annotations

import importlib
import logging
import math
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import event, or_, select, text
from sqlalchemy.orm import Session

from memorymap.core.database import Attachment, EmbeddingRecord, Entry, EntryLink
from memorymap.search import index as search_index
from memorymap.search import query as query_understanding

logger = logging.getLogger("memorymap.search.engine")

#: How the three signals are weighted into one order. Keyword relevance leads
#: because it is the signal that is always there: a notebook with no embedding
#: backend still has to rank well, and an app whose search quality depends on a
#: model being warm is not an offline app. Cosine is the second because it is
#: what finds the note you cannot remember the words of. Graph proximity is
#: deliberately the smallest: it is context, not evidence, the same judgement
#: `search_manager.graph_expansion` already makes by appending rather than
#: interleaving its neighbours.
WEIGHTS = {"bm25": 0.5, "cosine": 0.35, "graph": 0.15}

#: How many FTS candidates go on to the expensive signals. Cosine over 200
#: rows is one small matrix slice and the graph walk is two queries; over the
#: whole notebook both are a scan. Anything ranked past 200 by words alone was
#: not going to reach a twenty-row answer on a 0.35 weight.
CANDIDATE_DEPTH = 200

#: Graph proximity stops here. A third hop reaches most of a well-linked
#: notebook, at which point the signal says nothing about any one note.
MAX_HOPS = 2

#: Below this blended score a hit is noise and is dropped rather than shown at
#: the bottom of the list. Deliberately low: the keyword index only returns
#: rows that matched at all, so this is a floor against near-zero graph-only
#: dust, not a relevance opinion.
MIN_SCORE = 0.01


@dataclass
class Hit:
    """One result, with the whole of why it is here."""

    kind: str
    ref_id: int
    source: str
    title: str
    snippet: str
    #: `{"bm25": .., "cosine": .., "graph": ..}`, each 0 to 1. Always all
    #: three keys, even when a signal was unavailable: a missing key and a
    #: zero score render identically to a person and mean opposite things to
    #: a maintainer, so the zero is explicit and `available` says which.
    scores: dict[str, float]
    #: The blended score the list is ordered by.
    score: float
    #: Why this matched, in words, ready to render.
    explain: list[str] = field(default_factory=list)
    space: str = "default"
    written: str = ""
    flags: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.ref_id,
            "source": self.source,
            "title": self.title,
            "snippet": self.snippet,
            "scores": {name: round(value, 4) for name, value in self.scores.items()},
            "score": round(self.score, 4),
            "explain": self.explain,
            "space": self.space,
            "written": self.written,
            "flags": self.flags.split() if self.flags else [],
        }


# --- the vector matrix --------------------------------------------------------
#
# One float32 matrix per process, rows already unit-normalised so a top-k is a
# single matmul and nothing divides at query time. Rebuilt when the notebook or
# the embedding backend changes underneath it (a test opens a new database per
# test; a person can switch embedding models in Settings), and otherwise kept
# in step by the flush hook below rather than by a reload.


@dataclass
class _Matrix:
    key: str
    ids: list[int]
    rows: np.ndarray
    position: dict[int, int]

    def top_k(self, vector: np.ndarray, k: int, exclude: int | None = None) -> list[tuple[int, float]]:
        if not self.ids:
            return []
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return []
        scores = self.rows @ (vector.astype("float32") / norm)
        # `argpartition` rather than a full sort: at 50k vectors the sort is
        # most of the cost of the whole call, and only the top k is wanted.
        take = min(k + (1 if exclude is not None else 0), len(self.ids))
        best = np.argpartition(-scores, take - 1)[:take]
        ordered = best[np.argsort(-scores[best])]
        out = [(self.ids[i], float(scores[i])) for i in ordered if self.ids[i] != exclude]
        return out[:k]

    def scores_for(self, vector: np.ndarray, wanted: list[int]) -> dict[int, float]:
        """Cosine for a named handful of ids, no scan: this is the search
        path, where the candidates are already chosen by the keyword index."""
        rows = [(entry_id, self.position[entry_id]) for entry_id in wanted if entry_id in self.position]
        if not rows:
            return {}
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return {}
        slice_ = self.rows[[position for _id, position in rows]]
        scores = slice_ @ (vector.astype("float32") / norm)
        return {entry_id: float(score) for (entry_id, _p), score in zip(rows, scores)}


_matrix: _Matrix | None = None


def _matrix_key(session: Session, backend_id: str) -> str:
    bind = session.get_bind()
    return f"{getattr(bind, 'url', '')}|{backend_id}"


def _load_all_vectors(session: Session, backend_id: str) -> _Matrix:
    """The one full scan of `embeddings`, run once per process.

    Named, private and called from exactly one place on purpose: the spec
    (`test_similarity_does_not_scan_every_vector`) patches this function and
    asserts a request never reaches it. If a future change makes a per-request
    path call it again, that test fails, which is the whole point of it having
    a name rather than being inline.
    """
    records = session.execute(
        select(EmbeddingRecord.entry_id, EmbeddingRecord.embedding).where(
            # Vectors from another backend live in a different space; mixing
            # them gives nonsense (plan §6.5), the same filter
            # `semantic_search` applies.
            EmbeddingRecord.model_version == backend_id
        )
    ).all()
    ids: list[int] = []
    vectors: list[np.ndarray] = []
    widths: dict[int, int] = {}
    for entry_id, blob in records:
        vector = _unit(np.frombuffer(blob, dtype="float32"))
        widths[vector.shape[0]] = widths.get(vector.shape[0], 0) + 1
        ids.append(int(entry_id))
        vectors.append(vector)
    if widths and len(widths) > 1:
        # A model swapped inside one backend leaves rows at the old width, and
        # stacking a ragged list raises and takes every search down with it
        # (`semantic_search`'s own comment records that outage). The widest
        # family wins; the rest come back when the reindex refills them.
        keep = max(widths, key=lambda width: widths[width])
        logger.info(
            "vectors at %d widths in one backend; indexing the %d at width %d, reindex for the rest",
            len(widths),
            widths[keep],
            keep,
        )
        pairs = [(entry_id, vector) for entry_id, vector in zip(ids, vectors) if vector.shape[0] == keep]
        ids = [entry_id for entry_id, _v in pairs]
        vectors = [vector for _id, vector in pairs]
    rows = np.stack(vectors) if vectors else np.zeros((0, 1), dtype="float32")
    return _Matrix(
        key=_matrix_key(session, backend_id),
        ids=ids,
        rows=rows,
        position={entry_id: i for i, entry_id in enumerate(ids)},
    )


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return (vector / norm).astype("float32") if norm else vector.astype("float32")


def warm_vectors(session: Session, backend_id: str | None = None) -> int:
    """Build the matrix. Called at startup, and by nothing per request.

    Returns how many vectors it holds, so a caller can log it. Cheap to call
    again: a matrix already built for this notebook and backend is kept.
    """
    global _matrix
    backend = backend_id or _backend_id()
    if backend is None:
        return 0
    key = _matrix_key(session, backend)
    if _matrix is not None and _matrix.key == key:
        return len(_matrix.ids)
    _matrix = _load_all_vectors(session, backend)
    return len(_matrix.ids)


def _backend_id() -> str | None:
    """The embedding backend's id, or None when there is no embedding at all.

    Reached through the dependency container rather than passed in, because
    every caller of `search()` would otherwise have to know about embeddings
    to ask a keyword question.
    """
    try:
        # `importlib`, not an `import` statement, and the difference is the
        # whole point: this is a leaf naming the dependency container that
        # *builds* the things it reads, which closes
        # `ai.embeddings -> search.engine -> core.deps -> ai.embeddings`.
        # `tests/test_no_import_cycles.py` counts the statement wherever it
        # sits, because CodeQL does, so moving it into this function body
        # would hide the cycle from a naive reader and leave the alert open.
        deps = importlib.import_module("memorymap.core.deps")

        embeddings = deps.get_embeddings()
        return embeddings.backend_id() if embeddings.is_ready() else None
    except Exception:  # noqa: BLE001  # a bare-session script with no app state
        return None


def _live_matrix(session: Session) -> _Matrix | None:
    """The matrix if it is built for this notebook, else None. Never builds.

    This is what keeps `related()` off the scan path: a cold matrix means "no
    similarity yet", not "go and read fifty thousand rows while someone waits".
    Startup warms it (`api/app.py`), so cold only ever means the first moments
    of a process.
    """
    backend = _backend_id()
    if backend is None or _matrix is None:
        return None
    return _matrix if _matrix.key == _matrix_key(session, backend) else None


@event.listens_for(Session, "after_flush")
def _keep_matrix_in_step(session: Session, flush_context) -> None:  # noqa: ANN001
    """A stored vector joins the matrix without a reload; a deleted one leaves.

    The same reasoning as the index's own hook (`search/index.py`): every
    writer participates by construction. A bulk `DELETE FROM embeddings`
    through `session.execute` is the one shape this cannot see. Of the three
    that exist, two (`routes_entries.py`, re-embedding after an edit) store a
    fresh vector immediately afterwards, so the row is replaced rather than
    left stale; the third (`manager.set_private`) stores nothing, because a
    private note is never embedded, and calls `forget_vector` instead.
    """
    if _matrix is None:
        return
    for obj in session.new:
        if isinstance(obj, EmbeddingRecord):
            _remember(obj)
    for obj in session.deleted:
        if isinstance(obj, EmbeddingRecord):
            _forget(int(obj.entry_id))


def _remember(record: EmbeddingRecord) -> None:
    global _matrix
    if _matrix is None:
        return
    vector = _unit(np.frombuffer(record.embedding, dtype="float32"))
    if _matrix.rows.size and vector.shape[0] != _matrix.rows.shape[1]:
        return  # a different width: the reindex that follows a model switch rebuilds
    entry_id = int(record.entry_id)
    existing = _matrix.position.get(entry_id)
    if existing is not None:
        _matrix.rows[existing] = vector
        return
    rows = np.vstack([_matrix.rows, vector]) if _matrix.rows.size else vector.reshape(1, -1)
    _matrix.ids.append(entry_id)
    _matrix.position[entry_id] = len(_matrix.ids) - 1
    _matrix.rows = rows


def forget_vector(entry_id: int) -> None:
    """Drop one note's vector from the matrix, now.

    For the writes the ORM hook cannot see. There is exactly one that matters
    and it is a privacy one: `manager.set_private` deletes a note's
    `EmbeddingRecord` with a bulk `delete()` statement and stores nothing in
    its place, because a private note is never embedded. Without this the
    matrix would go on holding a vector *derived from the text the
    encryption exists to hide*, and every similarity query would keep
    answering questions about it.
    """
    _forget(int(entry_id))


def _forget(entry_id: int) -> None:
    global _matrix
    if _matrix is None:
        return
    position = _matrix.position.pop(entry_id, None)
    if position is None:
        return
    # The row is zeroed rather than removed: deleting from the middle of the
    # array would renumber every position after it. A zero row scores zero
    # against every query, which is exactly "not a match", and the next
    # `warm_vectors` on a fresh process rebuilds without it.
    _matrix.rows[position] = 0.0
    _matrix.ids[position] = -1


# --- the search ---------------------------------------------------------------


def index_counts(session: Session) -> dict[str, int]:
    """How many rows the index holds per kind. See `index.counts`."""
    return search_index.counts(session)


def _match_expression(terms: list[str], phrases: list[str], excluded: list[str], mode: str) -> str:
    """An FTS5 MATCH expression from what the person typed.

    `terms` are already `\\W`-stripped by `query.search_terms`, so
    none of them can carry FTS5 syntax; a phrase is quoted, which is FTS5's own
    phrase operator, and the quotes inside one are stripped for the same
    reason. `mode` is "all", "prefix" or "any", the same three stages
    `keyword_search` walks and for the same reason: an empty page for one
    transposed letter is the worst answer a search box gives.
    """
    parts: list[str] = []
    if mode == "prefix":
        parts.extend(f"{term}*" if len(term) >= 4 else term for term in terms)
    else:
        parts.extend(terms)
    joiner = " OR " if mode == "any" else " AND "
    # Parenthesised before anything is appended. FTS5 binds AND tighter than
    # OR and reads NOT as a binary operator, so `a OR b AND "phrase"` means
    # `a OR (b AND "phrase")`: the phrase the person quoted would be optional
    # for half the results, and `a OR b NOT c` would exclude `c` from only
    # half. One pair of brackets is the whole fix.
    expression = f"({joiner.join(parts)})" if parts else ""
    for phrase in phrases:
        cleaned = phrase.replace('"', " ").strip()
        if cleaned:
            expression = f'{expression} AND "{cleaned}"' if expression else f'"{cleaned}"'
    for word in excluded:
        safe = "".join(ch for ch in word if ch.isalnum() or ch in "_-")
        if safe and expression:
            expression = f"({expression}) NOT {safe}"
    return expression


def _candidates(
    session: Session,
    expression: str,
    kinds: list[str],
    space: str | None,
    since,
    until,
    depth: int,
) -> list[dict]:
    """The keyword pass: one query, every kind, filters applied in SQL.

    Filtering here rather than in Python is the difference between "read the
    top 200 rows" and "read the notebook": `kind`, `space` and the date bounds
    are stored on the index row precisely so they can narrow a MATCH instead of
    trimming its results.
    """
    sql = [
        f"SELECT rowid, kind, ref_id, source, title, body, tags, space, flags, written, "
        f"bm25(search_index, {', '.join(str(w) for w in search_index.BM25_WEIGHTS)}) AS score "
        "FROM search_index WHERE search_index MATCH :expr"
    ]
    params: dict = {"expr": expression, "depth": depth}
    if kinds:
        names = {f"kind{i}": kind for i, kind in enumerate(kinds)}
        sql.append("AND kind IN (" + ", ".join(f":{name}" for name in names) + ")")
        params.update(names)
    if space:
        sql.append("AND space = :space")
        params["space"] = space
    # ISO dates sort as text, which is the whole reason the column holds them
    # that way; a row with no date is kept, the same choice `search_manager`
    # makes, since dropping it would be filtering on an absence.
    if since is not None:
        sql.append("AND (written = '' OR written >= :since)")
        params["since"] = since.isoformat()
    if until is not None:
        sql.append("AND (written = '' OR written <= :until)")
        params["until"] = until.isoformat()
    sql.append("ORDER BY score LIMIT :depth")
    rows = session.execute(text(" ".join(sql)), params).mappings().all()
    return [dict(row) for row in rows]


def _filter_only(
    session: Session,
    kinds: list[str],
    space: str | None,
    since,
    until,
    depth: int,
) -> list[dict]:
    """The rows a query with no words at all asks for.

    `kind:document`, `is:pinned`, `after:2026-01-01`: a filter is a question
    too, and an FTS5 MATCH needs something to match. Newest first, because
    with nothing to rank by, recency is the only honest order. `score` is
    zeroed so the caller's normalisation leaves every bm25 at zero rather
    than inventing a relevance nobody computed.
    """
    sql = [
        "SELECT rowid, kind, ref_id, source, title, body, tags, space, flags, written, "
        "0.0 AS score FROM search_index WHERE 1 = 1"
    ]
    params: dict = {"depth": depth}
    if kinds:
        names = {f"kind{i}": kind for i, kind in enumerate(kinds)}
        sql.append("AND kind IN (" + ", ".join(f":{name}" for name in names) + ")")
        params.update(names)
    if space:
        sql.append("AND space = :space")
        params["space"] = space
    if since is not None:
        sql.append("AND (written = '' OR written >= :since)")
        params["since"] = since.isoformat()
    if until is not None:
        sql.append("AND (written = '' OR written <= :until)")
        params["until"] = until.isoformat()
    sql.append("ORDER BY written DESC, rowid DESC LIMIT :depth")
    rows = session.execute(text(" ".join(sql)), params).mappings().all()
    return [dict(row) for row in rows]


def _mentions(row: dict, words: list[str]) -> bool:
    """Does this row use any of these words, anywhere a query can see?"""
    haystack = " ".join(
        str(row.get(column) or "") for column in ("title", "body", "tags")
    ).lower()
    return any(word.lower() in haystack for word in words)


def _keyword_pass(
    session: Session,
    terms: list[str],
    asked,
    kinds: list[str],
    space: str | None,
    depth: int,
) -> list[dict]:
    for mode in ("all", "prefix", "any"):
        expression = _match_expression(terms, asked.phrases, asked.excluded, mode)
        if not expression:
            return []
        try:
            rows = _candidates(session, expression, kinds, space, asked.since, asked.until, depth)
        except Exception:  # noqa: BLE001  # a malformed MATCH is a typed query, not a bug
            # The expression is built from what somebody typed, so it stays
            # out of the log line (CodeQL, log injection): a newline in a
            # search box must not be able to forge a log entry. The stage and
            # the term count say as much as the text would for debugging.
            logger.debug("FTS match failed at the %s stage over %d term(s)", mode, len(terms))
            return []
        if rows:
            return rows
    return []


def _hops_from(session: Session, root_id: int, wanted: set[int]) -> dict[int, int]:
    """How many links away each wanted note is from the open one, up to two.

    Breadth-first over `entry_links` and reply threads, one query per hop, and
    only ever asked about the candidates: this is the same walk
    `search_manager._linked_neighbours` does for chat context, kept separate
    because that one collects *neighbours to add* and this one answers *how
    far is this hit*, which wants no truncation and no strength ordering.
    """
    hops: dict[int, int] = {}
    frontier = {root_id}
    seen = {root_id}
    for distance in range(1, MAX_HOPS + 1):
        if not frontier:
            break
        neighbours: set[int] = set()
        links = session.scalars(
            select(EntryLink).where(
                or_(
                    EntryLink.source_entry_id.in_(frontier),
                    EntryLink.target_entry_id.in_(frontier),
                )
            )
        )
        for link in links:
            neighbours.add(link.source_entry_id)
            neighbours.add(link.target_entry_id)
        for parent_id, child_id in session.execute(
            select(Entry.parent_id, Entry.id).where(
                or_(Entry.parent_id.in_(frontier), Entry.id.in_(frontier)),
                Entry.parent_id.is_not(None),
            )
        ).all():
            neighbours.add(parent_id)
            neighbours.add(child_id)
        neighbours -= seen
        for entry_id in neighbours:
            if entry_id in wanted:
                hops[entry_id] = distance
        seen |= neighbours
        frontier = neighbours
    return hops


def _normalised_bm25(raw: float, best: float) -> float:
    """FTS5's bm25 as a 0-to-1 score, best in this result set being 1.

    bm25() is negative and lower-is-better, which is neither comparable with a
    cosine nor renderable. Dividing by the best score in the same result set
    keeps the *order* exactly as FTS5 ranked it while putting it on the scale
    the other two signals live on. Deliberately relative: an absolute mapping
    would need a constant that depends on notebook size and document length,
    which is precisely the tuning-per-notebook that RRF exists to avoid
    elsewhere in this app.
    """
    if best == 0:
        return 0.0
    return max(0.0, min(1.0, raw / best))


def _explain(scores: dict[str, float], row: dict, terms: list[str], hop: int | None) -> list[str]:
    """Why this hit is here, in the words the Notes list renders.

    Ordered by which signal actually carried it, so the first phrase is the
    true reason rather than a fixed sentence with numbers in it.
    """
    said: list[tuple[float, str]] = []
    title = (row.get("title") or "").lower()
    body = " ".join((row.get("body") or "").split()).lower()
    # A note's "title" is its own first line, so on a one-line note the title
    # and the body are the same words and "matched the title" would be a
    # distinction the person cannot see. Only say it when there is a title to
    # match that the body does not repeat.
    has_real_title = bool(title) and body != title
    if scores["bm25"] > 0:
        if has_real_title and any(term in title for term in terms):
            said.append((scores["bm25"] * WEIGHTS["bm25"] + 0.01, "matched the title"))
        elif (row.get("tags") or "") and any(term in (row.get("tags") or "").lower() for term in terms):
            said.append((scores["bm25"] * WEIGHTS["bm25"], "matched a tag"))
        else:
            said.append((scores["bm25"] * WEIGHTS["bm25"], "matched your words"))
    if scores["cosine"] > 0:
        said.append((scores["cosine"] * WEIGHTS["cosine"], "similar meaning"))
    if scores["graph"] > 0:
        said.append(
            (
                scores["graph"] * WEIGHTS["graph"],
                "linked to the open note" if hop == 1 else "two links from the open note",
            )
        )
    said.sort(key=lambda pair: -pair[0])
    words = [phrase for _weight, phrase in said]
    if not words:
        # Reachable when a filter alone selected the row (`kind:document`
        # with no words). Saying so beats an empty line that reads like a bug.
        words = ["matched your filters"]
    return words


def _snippet(body: str, terms: list[str], width: int = 160) -> str:
    """A line of the body around the first matching word, or its opening."""
    flat = " ".join((body or "").split())
    if not flat:
        return ""
    lowered = flat.lower()
    at = -1
    for term in terms:
        at = lowered.find(term)
        if at >= 0:
            break
    if at < 0:
        return flat[:width]
    start = max(0, at - width // 3)
    return ("…" if start else "") + flat[start : start + width]


def _flag_filters(asked) -> tuple[list[str], list[str]]:
    """`is:` and `has:` as the flag words the index row carries."""
    wanted_is = [value.lower() for value in asked.filters.get("is", [])]
    wanted_has = [value.lower() for value in asked.filters.get("has", [])]
    return wanted_is, wanted_has


def _has_attachment_ids(session: Session, entry_ids: list[int]) -> set[int]:
    """Which of these notes have a file attached. One query, candidates only.

    `has:file` is the one filter a row cannot answer about itself (see
    `index.Row.flags`), so it is answered here, over the handful of rows that
    already matched, instead of by a join on every save.
    """
    if not entry_ids:
        return set()
    return set(
        session.scalars(select(Attachment.entry_id).where(Attachment.entry_id.in_(entry_ids)))
    )


def search(
    session: Session,
    q: str,
    ctx: dict | None = None,
    *,
    limit: int = 20,
    hybrid: bool = True,
    kinds: list[str] | None = None,
    depth: int = CANDIDATE_DEPTH,
) -> list[Hit]:
    """Search everything, and say why each answer is an answer.

    `ctx` is what the person is looking at: `{"entry_id": 12, "space": "work"}`.
    Both parts are optional; without an `entry_id` the graph signal is zero for
    every hit, which is honest rather than absent, and the other two still
    rank.

    `hybrid=False` is the keyword-only path: the perf gate the spec sets (an
    FTS-only answer in under 50ms on 5,000 notes) and the mode a notebook with
    no embedding backend is permanently in.
    """
    asked = query_understanding.understand(q)
    # The words to match on. The raw query is the fallback only when the
    # reader found nothing *and* there were no operators to find: with
    # operators, falling back would feed `kind:document` to the index as the
    # two words "kind" and "document", which match nothing and turn a filter
    # into an empty page.
    subject = asked.subject or ("" if (asked.has_operators or asked.has_range) else q)
    terms = query_understanding.search_terms(subject)
    for phrase in asked.phrases:
        terms.extend(
            word for word in query_understanding.search_terms(phrase) if word not in terms
        )
    context = ctx or {}
    space = context.get("space") or (asked.filters["space"][0] if asked.filters["space"] else None)
    wanted_kinds = [kind for kind in (kinds or asked.filters["kind"]) if kind in search_index.KINDS]

    # Something has to be *asked for*. An empty box, or a query that is only
    # `-rice`, names nothing to find: listing the whole notebook for it would
    # be the search box answering a question nobody put. The Notes list is
    # already showing every note when the box is empty; a search that also
    # returns every note is not an answer, it is noise with a scrollbar.
    asks_for_something = bool(
        terms or asked.phrases or any(asked.filters.values()) or asked.has_range
    )
    if not asks_for_something:
        return []

    if terms or asked.phrases:
        rows = _keyword_pass(session, terms, asked, wanted_kinds, space, depth)
    else:
        # Nothing to match on, but something to filter by: `kind:document`,
        # `is:pinned`, `after:2026-01-01`. Answering those with an empty page
        # would be the app refusing to do the one thing §5.1 promises works
        # with no model running.
        rows = _filter_only(session, wanted_kinds, space, asked.since, asked.until, depth)
        if asked.excluded:
            # There is no MATCH to hang a `NOT` on here, so the exclusion is
            # applied to the rows the filters selected. Over a page of
            # candidates rather than the notebook, the same place `has:file`
            # is answered.
            rows = [row for row in rows if not _mentions(row, asked.excluded)]
    if not rows:
        return []

    wanted_is, wanted_has = _flag_filters(asked)
    if wanted_is:
        rows = [row for row in rows if all(flag in (row["flags"] or "").split() for flag in wanted_is)]
    if wanted_has:
        note_ids = [row["ref_id"] for row in rows if row["kind"] in ("note", "board")]
        with_file = _has_attachment_ids(session, note_ids) if "file" in wanted_has else set()
        kept = []
        for row in rows:
            ok = True
            for want in wanted_has:
                if want == "file":
                    ok = ok and (row["kind"] == "file" or row["ref_id"] in with_file)
                else:
                    ok = ok and want in (row["flags"] or "").split()
            if ok:
                kept.append(row)
        rows = kept
    wanted_tags = [tag.lower() for tag in asked.filters["tag"]]
    if wanted_tags:
        # Substring rather than word equality: the tags column is a space-
        # joined list, and `tag:garden` should find a note tagged "gardening"
        # for the same reason the keyword stage tries prefixes.
        rows = [
            row for row in rows if all(tag in (row["tags"] or "").lower() for tag in wanted_tags)
        ]
    if not rows:
        return []

    best_raw = min(row["score"] for row in rows)  # bm25: more negative is better
    filters_only = best_raw == 0
    cosines: dict[int, float] = {}
    if hybrid:
        cosines = _cosine_scores(session, subject or q, rows)
    hops: dict[int, int] = {}
    open_entry = context.get("entry_id")
    if open_entry:
        note_ids = {row["ref_id"] for row in rows if row["kind"] in ("note", "board")}
        if note_ids:
            hops = _hops_from(session, int(open_entry), note_ids)

    hits: list[Hit] = []
    for row in rows:
        hop = hops.get(row["ref_id"]) if row["kind"] in ("note", "board") else None
        scores = {
            "bm25": _normalised_bm25(row["score"], best_raw),
            "cosine": max(0.0, cosines.get(row["ref_id"], 0.0)) if row["kind"] in ("note", "board") else 0.0,
            "graph": (1.0 / (1 + hop)) if hop else 0.0,
        }
        blended = sum(WEIGHTS[name] * value for name, value in scores.items())
        if filters_only:
            # A filter matched, nothing was ranked: every row is equally an
            # answer, and MIN_SCORE would throw the whole list away.
            blended = max(blended, MIN_SCORE)
        # Three floats from three subsystems: a NaN here would sort
        # unpredictably and do its damage nowhere near its cause, which is a
        # shape this project has already paid an afternoon for once.
        if not math.isfinite(blended) or blended < MIN_SCORE:
            continue
        hits.append(
            Hit(
                kind=row["kind"],
                ref_id=row["ref_id"],
                source=row["source"],
                title=row["title"] or _snippet(row["body"], terms, 60),
                snippet=_snippet(row["body"], terms),
                scores=scores,
                score=blended,
                explain=_explain(scores, row, terms, hop),
                space=row["space"],
                written=row["written"],
                flags=row["flags"],
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.kind, -hit.ref_id))
    return hits[:limit]


def _cosine_scores(session: Session, subject: str, rows: list[dict]) -> dict[int, float]:
    """Cosine for the candidates, from the matrix, without loading anything.

    Returns `{}` when there is no embedding backend or the matrix is cold,
    which leaves the cosine column at zero and the other two signals ranking:
    the app has to be excellent with the model off (WORLD_CLASS_PLAN §5).
    """
    matrix = _live_matrix(session)
    if matrix is None:
        # Cold, but this is the search path rather than the "see also" panel,
        # and a person who just typed a query is waiting for the best answer
        # this notebook can give. One build, once per process; `related()`
        # deliberately does not do this (see its own docstring).
        backend = _backend_id()
        if backend is None:
            return {}
        warm_vectors(session, backend)
        matrix = _live_matrix(session)
        if matrix is None:
            return {}
    try:
        # The same wrong-direction edge as `_backend_id`, broken the same way.
        deps = importlib.import_module("memorymap.core.deps")

        vector = deps.get_embeddings().embed_text(subject)
    except Exception:  # noqa: BLE001  # an embedding failure must not fail a search
        return {}
    if vector is None:
        return {}
    wanted = [row["ref_id"] for row in rows if row["kind"] in ("note", "board")]
    return matrix.scores_for(np.asarray(vector, dtype="float32"), wanted)


def related(session: Session, entry_id: int, k: int = 10) -> list[tuple[int, float]]:
    """Notes that mean something similar to this one, best first.

    `[(entry_id, cosine), …]`, and **no scan**: it reads the matrix that the
    writes keep current and nothing else. That is the behaviour the spec pins
    (`test_similarity_does_not_scan_every_vector`), and the reason is measured
    rather than theoretical: the path this replaces re-read every stored
    vector, stacked a fresh array and rebuilt an ORM entity per candidate, on
    every open of a note.

    A cold matrix returns nothing rather than building one. This is a "see
    also" panel; startup warms the matrix (`api/app.py`), so the empty case is
    the first seconds of a process, and the alternative is every note-open in
    a cold process paying for a full scan.
    """
    matrix = _live_matrix(session)
    if matrix is None:
        return []
    position = matrix.position.get(int(entry_id))
    if position is None:
        return []
    return matrix.top_k(matrix.rows[position], k, exclude=int(entry_id))


def similar_to_vector(session: Session, vector, k: int = 10) -> list[tuple[int, float]]:
    """Top-k for a vector somebody else computed. Same no-scan contract."""
    matrix = _live_matrix(session)
    if matrix is None:
        return []
    return matrix.top_k(np.asarray(vector, dtype="float32"), k)


def vectors_by_id(session: Session, only: set[int] | None = None) -> dict[int, "np.ndarray"]:
    """Every vector the matrix holds, as `{entry_id: unit vector}`.

    For the three whole-notebook features that genuinely do need all of them
    at once (link suggestions, tensions, the graph's similarity edges): they
    compare every pair, so there is no top-k to take. What they no longer do
    is *re-read and re-parse* the blobs: each was selecting every
    `EmbeddingRecord` row and calling `bytes_to_vector` on it, per request,
    for data this process already has in one array.

    Rows are unit-normalised, which is what `embeddings.similar_pairs` does to
    them first thing anyway.
    """
    matrix = _live_matrix(session)
    if matrix is None:
        backend = _backend_id()
        if backend is None:
            return {}
        warm_vectors(session, backend)
        matrix = _live_matrix(session)
        if matrix is None:
            return {}
    return {
        entry_id: matrix.rows[position]
        for entry_id, position in matrix.position.items()
        if only is None or entry_id in only
    }


def stats(session: Session) -> dict:
    """What the engine has to work with, for `/search/stats` and for a report."""
    matrix = _live_matrix(session)
    return {
        "index": index_counts(session),
        "vectors": len(matrix.ids) if matrix else 0,
        "vectors_warm": matrix is not None,
        "weights": dict(WEIGHTS),
    }
