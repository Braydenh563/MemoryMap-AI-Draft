"""The ONE active embedding backend (plan §2, resolution 1).

Default: sentence-transformers `BAAI/bge-small-en-v1.5`, no Ollama needed.
Optional: an Ollama embedding model (user's choice).

Both hide behind `embed_text()`, which returns None whenever embeddings
are unavailable. Callers must treat None as "skip semantic features",
never as an error, capture and keyword search keep working (plan §4).
"""

from __future__ import annotations

import json

import logging
import threading
import time

import numpy as np
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError
from memorymap.core.database import Attachment, Category, EmbeddingRecord, Entry

# The built-in embedding model. It was all-MiniLM-L6-v2 and is not any more,
# which is exactly why nothing user-facing may hard-code a name: the Models
# screen went on saying "Built-in (all-MiniLM)" long after this changed, and
# the only way to find out what was really running was to watch it download
# from Hugging Face in the log. Anything that shows the name asks
# `EmbeddingService.active_model()`.
DEFAULT_ST_MODEL = "BAAI/bge-small-en-v1.5"

logger = logging.getLogger("memorymap.embeddings")

# Warm-up bookkeeping so the UI can tell "still loading" from "failed"
# (a silently failed load used to look like eternal "warming up…").
_warmup = {"running": False, "started": False, "error": False}


def start_warmup(service: "EmbeddingService", session_factory=None) -> None:  # noqa: ANN001
    """Load the embedding model in a background thread at startup, so the
    user's first save doesn't stall. Idempotent per process.

    The session factory is passed in rather than looked up. This module is
    imported by the dependency container, so reaching back into it would make
    the import cycle real instead of merely deferred.
    """
    if _warmup["started"]:
        return
    _warmup["started"] = True

    def run() -> None:
        _warmup["running"] = True
        _warmup["error"] = False
        started = time.monotonic()
        try:
            service.embed_text("warm up")
        except Exception:
            _warmup["error"] = True
        finally:
            _warmup["running"] = False
            if _warmup["error"]:
                from memorymap.core import taskhistory
                taskhistory.record(
                    "embeddings",
                    "Loading embedding model",
                    "failed",
                    "Failed to load",
                    duration_ms=(time.monotonic() - started) * 1000,
                )
        # Now that the model is up, catch any notes that missed out.
        if session_factory is not None and not _warmup["error"]:
            backfill_missing(service, session_factory)
            # ...and build the retrieval engine's vector matrix once, here,
            # on the thread that already waited for the model rather than on
            # whichever request happens to be first (Brief 11). Before the
            # model is ready there is no backend id to build against, which
            # is why this is at the end of the warm-up and not in
            # `create_app`. A failure is logged and dropped: a cold matrix
            # means "no similarity yet", never a failed startup.
            try:
                # `importlib`, not an `import` statement: this module is a
                # leaf that `search/engine.py` sits on top of (through
                # `search_manager`), so naming the engine here closes
                # `ai.embeddings -> search.engine -> search.search_manager ->
                # ai.embeddings`. `tests/test_no_import_cycles.py` counts the
                # statement wherever it sits, because CodeQL does.
                import importlib

                search_engine = importlib.import_module("memorymap.search.engine")

                session = session_factory()
                try:
                    held = search_engine.warm_vectors(session)
                finally:
                    session.close()
                logging.getLogger("memorymap.embeddings").info(
                    "retrieval matrix warm with %d vector(s)", held
                )
            except Exception:  # noqa: BLE001  # see above
                logging.getLogger("memorymap.embeddings").warning(
                    "could not warm the retrieval matrix", exc_info=True
                )

    threading.Thread(target=run, name="embedding-warmup", daemon=True).start()


# How many gaps to close per startup. Bounded so a huge notebook doesn't spend
# minutes embedding on every launch; the next start picks up where this stopped.
BACKFILL_LIMIT = 200

# Enough to cover the repeated embeds within a single save, with headroom.
_EMBED_CACHE_MAX = 32


def backfill_missing(
    service: "EmbeddingService",
    session_factory,  # noqa: ANN001  # a callable returning a Session
    limit: int = BACKFILL_LIMIT,
) -> int:
    """Embed notes that have no vector, and report how many were fixed.

    Notes saved while the model was still warming up got no embedding, and
    nothing ever went back for them, so they stayed invisible to semantic
    search permanently, while looking perfectly normal in the list. The gap
    closes itself on the next start instead.

    Private notes are skipped, deliberately: store_for_entry refuses them, and
    a vector would leak what the note is about.
    """
    from sqlalchemy import select

    from memorymap.core.database import EmbeddingRecord, Entry

    if not service.is_ready():
        return 0
    fixed = 0
    try:
        session = session_factory()
    except Exception:  # noqa: BLE001  # startup helper, never fatal
        return 0
    try:
        missing = session.scalars(
            select(Entry)
            .outerjoin(EmbeddingRecord, EmbeddingRecord.entry_id == Entry.id)
            .where(
                Entry.is_deleted == False,  # noqa: E712
                Entry.is_private == False,  # noqa: E712
                EmbeddingRecord.id.is_(None),
            )
            .limit(limit)
        ).all()
        for entry in missing:
            if service.store_for_entry(session, entry):
                fixed += 1
        if fixed:
            session.commit()
            logging.getLogger("memorymap.embeddings").info(
                "backfilled %d note(s) that had no embedding", fixed
            )
    except Exception:  # noqa: BLE001  # a failed backfill must not stop startup
        session.rollback()
    finally:
        session.close()
    return fixed


def warmup_running() -> bool:
    return _warmup["running"]


def warmup_failed() -> bool:
    return _warmup["error"]


def clean_orphaned_vectors(session_factory) -> int:  # noqa: ANN001
    """Delete vectors whose note is gone, and say how many went.

    Nothing prunes the embeddings table when an entry is hard-deleted, the
    recycle bin's purge removes the row and leaves the vector behind, so it
    grows forever and every semantic search scans rows that can never match.

    This function is called by the background pass, and for a while it was
    *only* called: it did not exist, and the call sat inside a `try/except`
    broad enough to swallow the `AttributeError`, so the orphan cleanup was
    reported as running and silently never ran. Hence the return value and the
    log line: a maintenance job that cannot say what it did is a maintenance
    job nobody can tell is broken.

    `session_factory` is required rather than defaulted from `deps`. Defaulting
    it meant this module importing `core.deps`, which imports `EmbeddingService`
    from this module: a cycle CodeQL flagged, and a layering inversion besides:
    `ai/` sits below the dependency container, not above it. Every caller
    already holds a factory, so the parameter costs them nothing.
    """
    with session_factory() as session:
        orphans = list(
            session.scalars(
                select(EmbeddingRecord).where(
                    EmbeddingRecord.entry_id.notin_(select(Entry.id))
                )
            )
        )
        for row in orphans:
            session.delete(row)
        if orphans:
            session.commit()

    if orphans:
        logger.info("removed %d embedding(s) whose note no longer exists", len(orphans))
    return len(orphans)


def embedding_text(session: Session, entry: Entry) -> str:
    """What actually gets embedded for a note: its own words, plus what the
    pictures in it say.

    Asked for directly: "allow captions if they accompany images of sketches
    to be read by the ai if they appear in semantic searches." A note that is
    a drawing and one line of caption used to embed as that one line, the
    vision model's description of the drawing was on the `MediaUpload` row and
    the vector knew nothing about it, so "the diagram of the pond" matched
    nothing at all.

    The note is never modified: this is derived on the way past, which also
    means a picture captioned later improves search on the next re-index
    rather than needing the note rewritten. Falls back to the note's own text
    whenever there is nothing to add, so the vector for a plain note is
    exactly what it was before this existed.
    """
    import importlib

    media_process = importlib.import_module("memorymap.core.media_process")

    parts: list[str] = [entry.content]

    # **How the note is filed is part of what it is about.** Reported
    # directly: "I have a whole category called hobbies but basically none
    # came up in the semantic search." Nothing was broken: the word
    # "hobbies" appears in the *category*, and a category has never been part
    # of what gets embedded, so a note about the gym filed under Hobbies had
    # no more relation to the query "hobbies" than to any other word the note
    # does not contain. Naming the category and the tags in the embedded text
    # is what makes "what do I have under hobbies" a question the vectors can
    # actually answer, and it costs one short line per note.
    # Queried by id rather than read off a relationship: this app's models
    # declare foreign keys but no ORM `relationship()` anywhere, so
    # `entry.category` is not an attribute that exists, a `getattr` version
    # of this would have returned None forever and quietly indexed nothing.
    try:
        labels: list[str] = []
        if entry.category_id is not None:
            name = session.scalar(
                select(Category.name).where(Category.id == entry.category_id)
            )
            if name and str(name).lower() not in {"uncategorised", "uncategorized"}:
                labels.append(str(name))
        raw_tags = json.loads(entry.tags or "[]")
        labels += [str(tag) for tag in raw_tags if str(tag).strip()][:12]
        if labels:
            parts.append("Filed under: " + ", ".join(labels))
    except Exception:  # noqa: BLE001  # enrichment must never block an embedding
        pass

    # What this note's own attached files say. The same reasoning as the
    # media captions below, for the half of the app that stores files as
    # `Attachment` rows: a scanned lecture PDF attached to a two-word note
    # was, to the vectors, a two-word note. Now the caption a vision model
    # wrote and the text either extractor read are searchable with it.
    try:
        attachments = session.scalars(
            select(Attachment).where(Attachment.entry_id == entry.id)
        ).all()
        for attachment in attachments:
            found = [
                getattr(attachment, "caption", None),
                getattr(attachment, "ocr_text", None) or getattr(attachment, "vision_ocr_text", None),
            ]
            text = " ".join(str(item).strip() for item in found if item)
            if text:
                parts.append(f"{attachment.filename}: {text[:2000]}")
    except Exception:  # noqa: BLE001
        pass

    try:
        extra = media_process.media_text_for(session, entry.content)
        if extra:
            parts.append(extra)
    except Exception:  # noqa: BLE001  # enrichment must never block an embedding
        pass
    return "\n".join(parts)


def vector_to_bytes(vector: np.ndarray) -> bytes:
    """Raw float32 bytes: never pickle (plan §4)."""
    return np.asarray(vector, dtype="float32").tobytes()


def bytes_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="float32")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """1.0 = same direction, 0.0 = unrelated. Zero vectors score 0."""
    norms = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if norms == 0.0:
        return 0.0
    return float(np.dot(a, b) / norms)


#: How many notes' vectors to compare against the rest at a time.
#:
#: "All pairs at once" is the obvious way to write this and the reason it is
#: not written that way: `vectors @ vectors.T` allocates an N×N float matrix,
#: and `np.triu` of it allocates a second. At 5,000 notes that is 400 MB for a
#: graph refresh, at 10,000 it is 1.6 GB, and the notebook this app is built
#: for is explicitly allowed to get that big (ANALYSIS.md §34 scale-tests it).
#: A row block at a time is the same arithmetic with a ceiling on the memory.
SIMILARITY_BLOCK = 512


def similar_pairs(
    vectors: dict[int, np.ndarray], threshold: float
) -> list[tuple[int, int, float]]:
    """Every pair of ids scoring at or above `threshold`, best first.

    Vectors of a width other than the majority's are dropped rather than
    stacked: a notebook part-way through an embedding-model change holds both
    widths at once, and `np.stack` on a ragged list raises, which took out the
    graph and the link suggestions entirely rather than degrading them.
    """
    if not vectors:
        return []

    by_width: dict[int, list[int]] = {}
    for node_id, vector in vectors.items():
        by_width.setdefault(vector.shape[0], []).append(node_id)
    # The width most of the notebook is on. Everything else is mid-reindex.
    widest = max(by_width, key=lambda w: len(by_width[w]))
    ids = sorted(by_width[widest])
    if len(ids) < 2:
        return []

    matrix = np.stack([vectors[node_id] for node_id in ids]).astype("float32")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix /= np.where(norms == 0, 1.0, norms)

    found: list[tuple[int, int, float]] = []
    for start in range(0, len(ids), SIMILARITY_BLOCK):
        block = matrix[start : start + SIMILARITY_BLOCK]
        scores = block @ matrix.T
        # Keep each pair once: only look to the right of the diagonal.
        rows, cols = np.where(scores >= threshold)
        for row, col in zip(rows, cols):
            left = start + int(row)
            right = int(col)
            if right <= left:
                continue
            found.append((ids[left], ids[right], float(scores[row, col])))

    found.sort(key=lambda pair: pair[2], reverse=True)
    return found


class EmbeddingService:
    # After a failed model load, wait this long before trying again, 
    # each attempt can hit the network and stall a save otherwise.
    RETRY_AFTER_SECONDS = 300

    def __init__(self, model_manager: ModelManager, ollama_client: OllamaClient) -> None:
        self._models = model_manager
        self._ollama = ollama_client
        self._st_model = None  # loaded lazily, exactly once
        self._load_failed_at: float | None = None
        # Why the last embed failed, for the Models screen, None = fine.
        self.last_error: str | None = None
        # Guards _maybe_auto_install_missing_package: try the self-heal at
        # most once per process, not once per failed embed.
        self._auto_install_attempted = False
        # text -> vector, bounded and FIFO. See embed_text for why.
        self._embed_cache: dict[str, np.ndarray] = {}
        # Written from request threads and the re-index thread at once. A
        # dict survives concurrent get/set, but the eviction iterates it
        # (`next(iter(...))`) while another thread may insert, which raises
        # "dictionary changed size during iteration" inside a save, at
        # random, under load. One lock, held for microseconds; the embedding
        # call itself runs outside it.
        self._cache_lock = threading.Lock()

    def clear_embed_cache(self) -> None:
        """Drop cached vectors: used when the embedding backend changes,
        since the same text then maps to a different vector."""
        with self._cache_lock:
            self._embed_cache.clear()

    def reset_failure_state(self) -> None:
        """Forget a cached load/embed failure so the very next attempt
        retries immediately, and clear the stale error the Models screen
        shows. Called when the user switches search engine, they've
        usually just fixed whatever was wrong (e.g. a broken torch), and
        shouldn't have to wait out the 5-minute retry cooldown or stare at
        an out-of-date banner."""
        self.last_error = None
        self._load_failed_at = None

    def active_model(self) -> str:
        """The model actually doing the work right now, whichever backend."""
        if self._models.embedding_backend() == "ollama":
            return self._models.embedding_model()
        return DEFAULT_ST_MODEL

    def backend_id(self) -> str:
        """Stored as model_version next to every vector, so a backend
        switch is detectable: vectors from different models live in
        different spaces and must never be compared (plan §6.5)."""
        if self._models.embedding_backend() == "ollama":
            return f"ollama:{self._models.embedding_model()}"
        return f"sentence-transformers:{DEFAULT_ST_MODEL}"

    def is_ready(self) -> bool:
        """Can we embed right now without a long first-time load?
        Drives the UI's status pill."""
        if self._models.embedding_backend() == "ollama":
            return self._ollama.is_running()
        return self._st_model is not None

    def embed_text(self, text: str) -> np.ndarray | None:
        """Vector for one text, or None if the backend is unavailable.

        Recent results are cached by exact text. Saving a note embeds it twice
        within milliseconds: once to store the vector, once by the
        near-duplicate check that runs straight afterwards, and embedding is
        the slowest part of a save. Keying on the exact string means a cached
        vector can never be stale: different text is simply a different key.
        """
        with self._cache_lock:
            cached = self._embed_cache.get(text)
        if cached is not None:
            return cached
        vector = self._embed_uncached(text)
        if vector is not None:
            # Small and FIFO: this exists to collapse duplicate work inside one
            # request, not to be a general-purpose store.
            with self._cache_lock:
                if len(self._embed_cache) >= _EMBED_CACHE_MAX:
                    self._embed_cache.pop(next(iter(self._embed_cache)))
                self._embed_cache[text] = vector
        return vector

    def _embed_uncached(self, text: str) -> np.ndarray | None:
        if self._models.embedding_backend() == "ollama":
            try:
                vector = self._ollama.embed(self._models.embedding_model(), text)
                self.last_error = None
                return np.asarray(vector, dtype="float32")
            except OllamaError as exc:
                self.last_error = str(exc)
                return None
        return self._embed_with_sentence_transformers(text)

    def _load_st_model(self):  # noqa: ANN202
        """Load the sentence-transformers model, preferring what's already
        on disk over a live hub round-trip.

        This used to try online first, always, but `SentenceTransformer()`
        with no `local_files_only` still asks the hub whether a cached
        model is current before using it, and that's a real HTTP call this
        offline-first app has no business making on every note save. On a
        network that's merely slow or rate-limited (not simply down), that
        call doesn't fail fast: `huggingface_hub` retries with backoff for
        the better part of a minute before this code ever got a chance to
        fall back to the cache. Trying the cache first sidesteps the
        problem entirely for the common case (already downloaded once);
        the online attempt below is now purely for the genuine first-ever
        download."""
        from sentence_transformers import SentenceTransformer

        try:
            model = SentenceTransformer(DEFAULT_ST_MODEL, local_files_only=True)
            logger.info("embedding model loaded from local cache")
            return model
        except Exception:
            pass  # not cached yet (or the cache is stale/corrupt), fetch it for real
        return SentenceTransformer(DEFAULT_ST_MODEL)

    def _embed_with_sentence_transformers(self, text: str) -> np.ndarray | None:
        if self._st_model is None and self._load_failed_at is not None:
            if time.monotonic() - self._load_failed_at < self.RETRY_AFTER_SECONDS:
                return None  # don't re-stall every save while it's broken
        try:
            if self._st_model is None:
                # Heavy import (pulls in torch): deferred so the app
                # starts fast and still runs if the package is missing.
                self._st_model = self._load_st_model()
                self._load_failed_at = None
            result = np.asarray(self._st_model.encode(text), dtype="float32")
            self.last_error = None
            return result
        except Exception as exc:
            # No semantic features right now; the rest of the app must
            # keep working: but record and LOG why, or a broken install
            # looks like it's "warming up" forever (user-reported bug).
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._load_failed_at = time.monotonic()
            self._maybe_auto_install_missing_package(exc)
            logger.exception("embedding backend failed")
            return None

    def _maybe_auto_install_missing_package(self, exc: Exception) -> None:
        """Self-heal a missing `sentence-transformers` install, once per
        process, instead of leaving it to the user to find Settings ->
        Packages themselves.

        Search-by-meaning is the *default* engine, it already silently
        downloads its own ~130MB model from Hugging Face on first use with
        no separate opt-in, so installing the one PyPI package that makes
        it importable at all is the same "works without being asked" shape,
        not a new consent-requiring action the way turning on web search or
        checking GitHub for updates would be.

        Deliberately narrow: only a genuine "the package flat-out isn't
        there" `ModuleNotFoundError` triggers this. A different failure: 
        a corrupted install, an incompatible wheel, an out-of-memory crash
        - retrying the exact same `pip install` would do nothing but burn
        bandwidth and hide a real problem behind "installing…" forever;
        `is_installed`'s own docstring already notes that import-success
        isn't "it's sound", which is a different, harder problem than this
        (`reinstall`, the manual escape hatch in Settings, exists for that
        one). Reuses `core.extras.start`, the same machinery the Settings ->
        Packages button calls: including this session's `find_system_python`
        fix, so this now actually works on a packaged (frozen) build, not
        just a source checkout.
        """
        if self._auto_install_attempted:
            return
        if not isinstance(exc, ModuleNotFoundError) or "sentence_transformers" not in str(exc):
            return
        self._auto_install_attempted = True
        from memorymap.core import extras

        started, message = extras.start("semantic")
        if not started:
            # Already installed (so this was a *different* failure, sound
            # but broken, `reinstall`'s job, not this one's), already
            # running (someone beat this to it), or genuinely unavailable
            # on this platform. Nothing safe to do automatically either way.
            logger.info("sentence-transformers auto-install not started: %s", message)
            return
        logger.info("sentence-transformers missing: installing it automatically")

        def _retry_once_installed() -> None:
            while extras.current().running:
                time.sleep(1)
            if extras.current().outcome == "completed":
                logger.info(
                    "sentence-transformers auto-install finished: retrying the load"
                )
                # CPython's path-based import finders cache directory
                # listings for speed, so a package that didn't exist the
                # first time this process looked can still come up
                # "missing" on a naive retry even though pip just put it
                # there: invalidate_caches() is the documented fix
                # (importlib docs, "Caching and invalidation"), and is what
                # makes this an actual same-process fix rather than a
                # "restart MemoryMap" instruction in different words.
                import importlib

                importlib.invalidate_caches()
                self.reset_failure_state()

        threading.Thread(
            target=_retry_once_installed, name="embedding-auto-install-watch", daemon=True
        ).start()

    def store_for_entry(self, session: Session, entry: Entry) -> bool:
        """Save an entry's vector. Returns False on failure, which only
        means no semantic search for this entry; it never blocks the
        entry save itself.

        Private notes are never embedded. A vector derived from the text
        encodes what the note is about, so storing one beside the ciphertext
        would leak exactly what the encryption is there to hide."""
        if getattr(entry, "is_private", False):
            return False
        vector = self.embed_text(embedding_text(session, entry))
        if vector is None:
            return False
        # **Storing is storing, not inserting.** `entry_id` is unique, so a
        # second call for the same note raised `UNIQUE constraint failed:
        # embeddings.entry_id` and took whatever was saving with it. Every
        # caller today already deletes the old row first, or selects only
        # notes that have none, so nothing was broken; the duplication of
        # that guard across four call sites was the bug waiting to happen,
        # because the next caller has to know to write it and the name says
        # it does not have to. Their deletes stay, harmlessly, as no-ops.
        session.execute(sa_delete(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry.id))
        session.add(
            EmbeddingRecord(
                entry_id=entry.id,
                embedding=vector_to_bytes(vector),
                dim=int(vector.shape[0]),
                model_version=self.backend_id(),
            )
        )
        session.commit()
        return True


# `store_quietly` used to live here and is now `core.deps.store_quietly`, it
# needs the shared EmbeddingService, and reaching for that from inside this
# module means importing the container that imports this module. See the
# docstring there.
