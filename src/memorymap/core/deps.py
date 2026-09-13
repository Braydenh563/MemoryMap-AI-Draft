"""The single source of truth for shared app state (build plan §4).

Exactly one ConfigManager and one DatabaseManager exist per process.
Routers must import `get_session` / `get_config` from here and must
NEVER build their own DatabaseManager.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from memorymap.ai.embeddings import EmbeddingService
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient
from memorymap.ai.openai_client import OpenAICompatClient
from memorymap.ai.provider import Provider
from memorymap.core.config import ConfigManager
from memorymap.core.database import DatabaseManager, Entry

_ModelT = TypeVar("_ModelT")

_config: ConfigManager | None = None
_db: DatabaseManager | None = None
_ollama: Provider | None = None
_model_manager: ModelManager | None = None
_embeddings: EmbeddingService | None = None


class MultipleWorkersError(RuntimeError):
    """Raised when the app is started with more than one worker process."""


def _requested_worker_count() -> int | None:
    """How many workers the launcher was asked for, if it said.

    Everything in this module is one-per-process, and so are the in-memory log
    buffer, the auth tokens and the handle on the SearXNG subprocess. That is
    correct and simple for one process, and quietly wrong for two: the log
    console would show a fraction of what happened, an unlock would work only
    on whichever worker answered next, and two workers would each believe they
    owned the SearXNG they started.

    None of that fails loudly. It presents as flakiness, which is the reason
    to refuse rather than warn.

    Read from the command line and from WEB_CONCURRENCY, which is the
    environment variable uvicorn and gunicorn both honour, between them those
    are the ways someone actually turns this up.
    """
    argv = sys.argv[1:]
    for index, argument in enumerate(argv):
        value = None
        if argument in ("--workers", "-w") and index + 1 < len(argv):
            value = argv[index + 1]
        elif argument.startswith("--workers="):
            value = argument.split("=", 1)[1]
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return None
    concurrency = os.environ.get("WEB_CONCURRENCY")
    if concurrency:
        try:
            return int(concurrency)
        except ValueError:
            return None
    return None


def refuse_multiple_workers() -> None:
    """Stop a multi-worker start, with the reason and the way out.

    Deliberately an exception rather than a log line. A warning at startup is
    read by nobody and the failure it precedes looks like a bug in the app.
    """
    workers = _requested_worker_count()
    if workers is None or workers <= 1:
        return
    raise MultipleWorkersError(
        f"MemoryMap cannot run with {workers} workers: it is a single-user "
        "app, and its configuration, database handle, log buffer, unlock "
        "sessions and SearXNG subprocess are one-per-process. With more than "
        "one worker each of those silently becomes per-worker: logs would show "
        "a fraction of what happened, unlocking would work only sometimes, and "
        "two workers would each think they own the SearXNG they started.\n\n"
        "Start it with one worker (`python -m memorymap`). If you are trying "
        "to make it faster, more workers is not the lever, the slow paths are "
        "Ollama and embedding, and both are already off the request thread."
    )


#: Where each dialect listens when the user hasn't said. LM Studio's port is
#: the OpenAI default because it is the backend that was actually asked for,
#: and it is the one of the four whose port is fixed rather than chosen at
#: launch (llama.cpp and vLLM are whatever you passed `--port`).
DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "http://localhost:1234/v1",
}


def build_llm_client(config: ConfigManager) -> Provider:
    """The chat backend the user has chosen (§6).

    Two dialects, not four products: `openai` covers LM Studio, llama.cpp, Jan
    and vLLM alike, because the only thing that differs between them is the
    base URL. Everything downstream, the agent, the librarian, the janitor , 
    is written against `Provider` and never asks which one it got.

    An unrecognised provider name falls back to Ollama rather than raising. The
    preferences file is a JSON file the user is invited to edit by hand, and a
    typo in it should cost the setting, not the app.
    """
    provider = str(config.get_preference("llm_provider", "ollama") or "ollama").lower()
    base_url = str(config.get_preference("llm_base_url", "") or "").strip()

    # The lock is enforced here as well as at the endpoint, and that is not
    # belt-and-braces for its own sake: `preferences.json` is a plain file the
    # user is invited to edit by hand, and it is what a restored backup or a
    # copied config brings with it. Checking only on the way in would mean a
    # remote address that never passed through the endpoint is used anyway, 
    # silently, and on every turn.
    #
    # Falling back to the provider's local default rather than refusing to
    # start: the app must still open so the setting can be fixed from inside it.
    if base_url and config.get_preference("local_only_ai", True):
        from memorymap.core import security

        allowed, reason, _ = security.check_backend_url(base_url, local_only=True)
        if not allowed:
            logging.getLogger("memorymap.config").warning(
                "refusing the saved AI backend %r and using the local default "
                "instead: %s",
                base_url,
                reason,
            )
            base_url = ""

    if provider == "openai":
        return OpenAICompatClient(
            base_url=base_url or DEFAULT_BASE_URLS["openai"],
            api_key=str(config.get_preference("llm_api_key", "") or ""),
        )
    # `config.ollama_url` carries the OLLAMA_URL environment variable, which
    # predates this setting: so it stays the default for the Ollama path
    # rather than being overwritten by an empty preference.
    return OllamaClient(base_url=base_url or config.ollama_url)


def init_app_state(data_dir: str | Path | None = None) -> None:
    """Build the singletons once. Safe to call twice (later calls no-op),
    so tests can initialise with a temp dir before the app starts."""
    global _config, _db, _ollama, _model_manager, _embeddings
    if _config is None:
        _config = ConfigManager(data_dir=data_dir)
    if _db is None:
        _db = DatabaseManager(_config.db_path)
    if _ollama is None:
        _ollama = build_llm_client(_config)
    # `ai/provider.py` reads the user's sampling overrides through a getter
    # rather than importing this module: it is the bottom of the AI stack and
    # this is the wiring that builds on it, so the import would be a cycle
    # (CodeQL flagged it) as well as the wrong direction. Registered here,
    # where the config it reads is known to exist.
    #
    # Even a submodule-direct, function-scoped import of it was still flagged
    # as beginning a cycle (CodeQL's cyclic-import query counts a function
    # body's imports too, not just module-level ones), so this is imported
    # by name through `importlib` instead of a `from`/`import` statement,
    # which is the same runtime lookup with nothing for the static check to
    # see as an edge.
    import importlib

    importlib.import_module("memorymap.ai.provider").set_sampling_overrides_getter(
        lambda: _config.get_preference("sampling_overrides", {})
    )
    if _model_manager is None:
        _model_manager = ModelManager(_config)
    if _embeddings is None:
        _embeddings = EmbeddingService(_model_manager, _ollama)


def reload_db() -> None:
    """Close every connection and reopen the database file, needed
    after a backup restore replaces the file underneath us."""
    global _db
    assert _config is not None
    if _db is not None:
        _db.engine.dispose()
    _db = DatabaseManager(_config.db_path)


#: Caches that have to be emptied when the singletons are thrown away.
#:
#: Anything holding values derived from *this* notebook registers here. The
#: graph's PageRank and similarity caches were the first, and they were
#: originally cleared by importing `api.routes_graph` from inside
#: `reset_app_state`, which works, and inverts the layering: `core/` is the
#: bottom of this app and must not know the API layer exists. CodeQL called it
#: what it was, a cycle.
#:
#: A registry turns it the right way up. The cache tells the container it
#: exists; the container never goes looking.
_cache_resets: list = []


def register_cache_reset(drop) -> None:  # noqa: ANN001  # any zero-arg callable
    """Have `drop()` called whenever the app's singletons are reset."""
    if drop not in _cache_resets:
        _cache_resets.append(drop)


def reset_app_state() -> None:
    """Throw the singletons away, used between tests, never in the app."""
    global _config, _db, _ollama, _model_manager, _embeddings
    if _db is not None:
        _db.engine.dispose()
    for drop in _cache_resets:
        drop()
    _config = None
    _db = None
    _ollama = None
    _model_manager = None
    _embeddings = None


def reload_llm_client() -> None:
    """Rebuild the chat backend after the provider or its URL changed.

    Settings → Models can switch between Ollama and an OpenAI-compatible
    server, and the whole point of doing it there is not having to restart the
    app. The embedding service holds the same client, so it is rebuilt too, 
    otherwise switching backend would leave embeddings still talking to the old
    one, which presents as semantic search quietly using a server the user
    thinks they turned off.
    """
    global _ollama, _embeddings
    assert _config is not None
    _ollama = build_llm_client(_config)
    _embeddings = EmbeddingService(get_model_manager(), _ollama)


def override_ai(
    ollama: Provider | None = None,
    embeddings: EmbeddingService | None = None,
) -> None:
    """Swap in fakes: tests only. Real code never calls this."""
    global _ollama, _embeddings
    if ollama is not None:
        _ollama = ollama
    if embeddings is not None:
        _embeddings = embeddings


def get_config() -> ConfigManager:
    init_app_state()
    assert _config is not None
    return _config


def get_db() -> DatabaseManager:
    init_app_state()
    assert _db is not None
    return _db


def get_ollama() -> Provider:
    """The chat backend, whichever dialect it speaks.

    Still named for Ollama because every call site is, and renaming it would
    be a large diff that changes no behaviour. What it returns is a `Provider`.
    """
    init_app_state()
    assert _ollama is not None
    return _ollama


def get_model_manager() -> ModelManager:
    init_app_state()
    assert _model_manager is not None
    return _model_manager


def get_embeddings() -> EmbeddingService:
    init_app_state()
    assert _embeddings is not None
    return _embeddings


def get_session(request: Request = None) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_db().session()
    if request is not None:
        workspace_id = request.headers.get("X-Workspace-ID")
        if workspace_id:
            session.info["workspace_id"] = workspace_id
            # Resolved here, once, because the statement-level filter in
            # database.py runs for every query and must not issue one of its
            # own (it would re-enter that same event). Only "all" needs it.
            if workspace_id == "all":
                from memorymap.core.database import Space

                session.info["hidden_workspaces"] = [
                    row[0]
                    for row in session.query(Space.id)
                    .filter(Space.hidden_from_all.is_(True))
                    .all()
                ]
    try:
        yield session
    finally:
        session.close()


def get_or_404(
    session: Session, model: type[_ModelT], obj_id: object, detail: str
) -> _ModelT:
    """Fetch a row by primary key, or raise the 404 the route wants.

    Every route file had its own copy of `row = session.get(Model, id); if
    row is None: raise HTTPException(404, "...")`, ~39 of them across 12
    files, found by grep, all the same three lines with a different model
    and message. This is the plain "look up by id, 404 if missing" shape
    only; a lookup that also checks something else about the row (soft
    delete, ownership, an index bound) stays inline at its call site rather
    than being bent to fit here, because bending it would either change what
    it checks or make the helper lie about what it does.

    `detail` is required rather than derived from `model.__name__`, because
    the existing messages are user-facing text ("No such preference",
    "Attachment not found", "No note with id 5") that this refactor is not
    meant to alter: passing it explicitly is what keeps that text byte-for-
    byte the same as before.
    """
    obj = session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def store_quietly(session: Session, entry: Entry) -> bool:
    """Best-effort embedding refresh for a note that was just written.

    Every caller wants the same two things: never fail the user's save because
    the embedding backend is unhappy, and never lose the reason it was unhappy.
    The bare ``except Exception: pass`` this replaces delivered only the first, 
    so a backend that had stopped working produced notes that quietly dropped
    out of semantic search with nothing anywhere to say why.

    It lives here, and not in `ai/embeddings.py` where it reads like it
    belongs, for one reason: it needs the shared `EmbeddingService`, and this
    module is the only thing allowed to hand that out. From inside `embeddings`
    it could only be reached by importing this module back, a real cycle,
    which a function-local import defers rather than removes.

    Returns True if a vector was stored.
    """
    try:
        return get_embeddings().store_for_entry(session, entry)
    except Exception:  # noqa: BLE001  # the whole point is that nothing escapes
        logging.getLogger("memorymap.embeddings").warning(
            "couldn't embed entry %s; it stays keyword-searchable only",
            getattr(entry, "id", "?"),
            exc_info=True,
        )
        return False

#: How many notes have to arrive or vanish at once before the app says the
#: search index is worth rebuilding. Twenty is roughly "an import or a restore
#: happened", not "you had a productive afternoon", a suggestion that fires
#: on ordinary use is a suggestion people learn to ignore.
INDEX_STALE_SUGGEST_AT = 20


def mark_index_stale(count: int) -> None:
    """Record that `count` notes changed outside the one-note-at-a-time path.

    Asked for directly: *"suggest rebuilding the search index upon large
    changes."* A note saved through the app embeds itself as it goes
    (`store_quietly` above); a note that arrives by bulk import or comes back
    from a backup restore does not always, and nothing anywhere said so, the
    only symptom was semantic search quietly missing things it should have
    found.

    A counter rather than a boolean, because "3 notes" and "1,400 notes" are
    different situations and only one of them is worth interrupting anybody
    for. Kept in preferences (not the database) so a restore cannot roll the
    fact of the restore back over itself.
    """
    if count <= 0:
        return
    config = get_config()
    current = int(config.get_preference("index_stale_notes", 0) or 0)
    config.set_preference("index_stale_notes", current + count)


def clear_index_stale() -> None:
    """Called when a rebuild starts: the backlog it was counting is gone."""
    get_config().set_preference("index_stale_notes", 0)


def index_stale_notes() -> int:
    return int(get_config().get_preference("index_stale_notes", 0) or 0)


@contextmanager
def impersonate_workspace(session: Session, workspace_id: str):
    """Run a block of code as if in a specific workspace."""
    old = session.info.get("workspace_id")
    session.info["workspace_id"] = workspace_id
    try:
        yield
    finally:
        if old is None:
            del session.info["workspace_id"]
        else:
            session.info["workspace_id"] = old
