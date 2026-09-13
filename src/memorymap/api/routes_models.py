"""Model Manager endpoints (plan §6.5).

Everything is written so the app degrades gracefully: Ollama being
absent turns into flags in /models/status, never an error.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from memorymap.ai import embeddings as embeddings_module
from memorymap.ai import sampling
from memorymap.ai import model_manager as jobs
from memorymap.ai.model_manager import SUGGESTED_MODELS
from memorymap.ai.ollama_client import OllamaError
from memorymap.core import deps, ocr, security
from memorymap.core.deps import get_session
from memorymap.entry.manager import log_action

router = APIRouter(prefix="/models", tags=["models"])


class ChatModelBody(BaseModel):
    name: str


class EmbeddingBackendBody(BaseModel):
    backend: Literal["sentence-transformers", "ollama"]
    model: str | None = None  # required when backend == "ollama"


class PullBody(BaseModel):
    name: str


class UtilityModelBody(BaseModel):
    # "" means "use the chat model".
    name: str = ""


class VisionModelBody(BaseModel):
    # "" means "auto-detect", the first installed model that declares the
    # "vision" capability. See ModelManager.resolve_vision_model.
    name: str = ""


class ProviderBody(BaseModel):
    """Which backend serves the chat model, and where it lives (§6).

    `base_url` empty means "the default for that provider", which is the
    common case: Ollama on 11434, LM Studio on 1234. Anyone running llama.cpp
    or vLLM has chosen their own port and fills it in.
    """

    provider: Literal["ollama", "openai"]
    base_url: str = ""
    api_key: str | None = None  # None = leave whatever is stored alone


#: What to call the backend in a message the user reads. "Ollama isn't
#: running" is confusing advice when the app was pointed at LM Studio.
_BACKEND_LABELS = {"ollama": "Ollama", "openai": "the model server"}


def _backend_label() -> str:
    provider = str(
        deps.get_config().get_preference("llm_provider", "ollama") or "ollama"
    )
    return _BACKEND_LABELS.get(provider, "the model server")


def _installed_models(running: bool) -> list[dict]:
    if not running:
        return []
    try:
        return [
            {"name": m.get("name", ""), "size": m.get("size", 0)}
            for m in deps.get_ollama().list_models()
        ]
    except OllamaError:
        return []


def _name_matches(wanted: str, installed: list[dict]) -> bool:
    """'llama3.2' should match an installed 'llama3.2:latest'."""
    names = {m["name"] for m in installed}
    names |= {name.split(":")[0] for name in names}
    return wanted in names


@router.get("/status")
def status() -> dict:
    """One call that tells the UI everything: is Ollama up, what's
    installed, what's active, and whether any job is running."""
    ollama = deps.get_ollama()
    manager = deps.get_model_manager()
    embeddings = deps.get_embeddings()

    # is_running() and list_models() both hit Ollama's own /api/tags: 
    # calling both in sequence (as this used to) can take up to 7s (2s + 5s)
    # for one poll, which used to be longer than the frontend's
    # AbortSignal.timeout on this exact call (app.js refreshModelStatus): 
    # since raised from 5s to 8s, but still worth beating rather than
    # trusting that margin. That mismatch read as "AI unavailable" on a
    # backend that is genuinely up but momentarily slow to answer, one
    # round-trip now serves both purposes.
    try:
        installed = [
            {"name": m.get("name", ""), "size": m.get("size", 0)}
            for m in ollama.list_models()
        ]
        running = True
    except OllamaError:
        installed = []
        running = False
    chat_model = manager.chat_model()
    # Resolved once. It walks the installed models asking each whether it can
    # see, which is an HTTP call per model on a cold cache.
    resolved_vision = manager.resolve_vision_model(ollama, installed) if running else None

    config = deps.get_config()
    provider = str(config.get_preference("llm_provider", "ollama") or "ollama")
    # Judged on every status poll, not only when the address is changed. A
    # warning that appears once and vanishes on the next reload is a warning
    # about a condition that has not gone away, and this one is about notes
    # leaving the machine, which is the app's central promise.
    local_only = bool(config.get_preference("local_only_ai", True))
    _, privacy_note, is_local = security.check_backend_url(ollama.base_url)

    return {
        # Named for Ollama because the whole UI is, and it means "the chat
        # backend is answering", which is the question the pill asks whoever
        # is answering it.
        "ollama_running": running,
        # Which dialect is actually in use (§6), so the UI can say so rather
        # than claiming Ollama when the answers came from LM Studio.
        "provider": provider,
        "base_url": ollama.base_url,
        "provider_default_base_urls": deps.DEFAULT_BASE_URLS,
        # False means notes leave this machine to be answered. Reported on
        # every poll so the warning persists rather than showing once.
        "is_local": is_local,
        "privacy_note": privacy_note,
        "local_only_ai": local_only,
        # Only Ollama can download a model on request; the others are handed
        # one that is already on disk. The download panel hides itself rather
        # than offering a button that cannot work.
        "supports_pull": ollama.supports_pull(),
        "installed_models": installed,
        "chat_model": chat_model,
        # None = unknown because Ollama is off (don't warn about nothing)
        "chat_model_installed": _name_matches(chat_model, installed) if running else None,
        # "" means "same as chat model" (utility model).
        "utility_model": manager._config.get_preference("utility_model", ""),
        # "" means "auto-detect" (vision model). The resolved field is what
        # an image-carrying turn would actually use right now, None if
        # nothing installed declares vision and no explicit choice is set, 
        # so Settings can show "auto: currently: llama3.2-vision" rather
        # than making the user guess what auto-detect will do.
        "vision_model": manager.vision_model(),
        "vision_model_resolved": resolved_vision,
        "ocr_model": manager.ocr_model(),
        # Derived from the vision answer rather than resolved again, see
        # `resolve_ocr_model`. Doing both independently walked every installed
        # model twice and pushed this poll past the frontend's 5s abort.
        "ocr_model_resolved": (
            manager.resolve_ocr_model(ollama, installed, vision_fallback=resolved_vision or "")
            if running
            else None
        ),
        "embedding_backend": manager.embedding_backend(),
        # The Ollama model *setting*, only meaningful on that backend.
        "embedding_model": manager.embedding_model(),
        # What is actually embedding right now, whichever backend that is.
        # The UI used to hard-code the built-in name and was two model
        # changes out of date.
        "active_embedding_model": embeddings.active_model(),
        "embedding_ready": embeddings.is_ready(),
        # Lets the UI tell "still loading" from "failed" (pill fix).
        "embedding_warming": embeddings_module.warmup_running(),
        "embedding_warming_failed": embeddings_module.warmup_failed(),
        "embedding_error": embeddings.last_error,
        "reindex": jobs.reindex_status(),
        #: How many notes have arrived or gone in bulk since the index was
        #: last rebuilt: asked for as "suggest rebuilding the search index
        #: upon large changes". The status poll already runs; a second
        #: endpoint for one integer would be a second thing to keep in step.
        "index_stale_notes": deps.index_stale_notes(),
        "index_stale_suggest_at": deps.INDEX_STALE_SUGGEST_AT,
        "pulls": jobs.pull_statuses(),
        # Reported directly: the local-OCR button ("Read text offline") was
        # always shown enabled, so pressing it without the `tesseract` system
        # binary installed (never automatable the way the pip half is, see
        # core/ocr.py's own module docstring) just silently produced nothing,
        # with no way to tell "it ran and found no text" from "it never ran
        # at all". A `shutil.which` check, cheap enough for every poll.
        "tesseract_available": ocr.tesseract_available(),
    }


@router.get("/spec")
def model_spec(name: str = "") -> dict:
    """What the backend says about one model, size, quantisation, window,
    and what it can actually do.

    The app read a context length and nothing else, so Settings → Models could
    not tell you how big a model was, how it was quantised, or whether it
    supports tool calls: which is the first thing worth knowing when "agent
    mode does nothing", and until now was only discoverable by trying it and
    reading the failure.

    `supports_tools` and `supports_thinking` are deliberately tri-state: True,
    False, or null for "this backend doesn't say". Null is not False, an older
    Ollama reports no capability list at all, and rendering its silence as
    "can't use tools" would be a confident lie about a model that works fine.
    """
    client = deps.get_ollama()
    model = name.strip() or deps.get_model_manager().chat_model()
    try:
        return client.model_spec(model)
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class SamplingBody(BaseModel):
    """Only the fields the user actually changed.

    Sparse on purpose: see `ai/sampling.py`. Storing a full set the moment the
    panel opens would pin one model's recommendations onto every other model
    the user ever runs, which is the exact failure the auto-detection exists to
    avoid.
    """

    overrides: dict[str, float] = Field(default_factory=dict)


@router.get("/sampling")
def sampling_settings(name: str = "") -> dict:
    """The advanced response settings, and where each value comes from.

    Asked for directly: expose top-k, top-p, repeat penalty and the rest,
    "because different models require different parameters to get the same
    result", and detect the right ones per model if that is possible.

    It is, and without guessing. A GGUF carries its author's recommended
    sampling parameters, Ollama reports them in `/api/show`, and this app was
    already fetching and caching that payload for the context window and the
    capability list while dropping that one field. So `model` below is what the
    model itself asks for, not a table someone maintained by hand.

    `sources` is why this returns more than numbers: "0.6 because this model
    recommends it" and "0.6 because you set it" need different controls beside
    them, and only the second has anything to revert to.
    """
    client = deps.get_ollama()
    model = name.strip() or deps.get_model_manager().chat_model()
    try:
        shown = client.show(model) if hasattr(client, "show") else {}
    except Exception:  # noqa: BLE001  # an unreachable backend is not an error here
        shown = {}
    model_defaults = sampling.parse_model_parameters(shown)
    # Read from settings here rather than through the provider. The provider
    # has its own accessor because every generation path goes through
    # `runtime_options` and threading a settings dict through all of them would
    # mean each one could forget, but this route is *about* the setting, and
    # asking the backend for it would couple a settings screen to whichever
    # client happens to be configured.
    overrides = deps.get_config().get_preference("sampling_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
    return {
        "model": model,
        "knobs": sampling.as_dicts(),
        "model_defaults": model_defaults,
        "overrides": overrides,
        "effective": sampling.resolve(model_defaults, None, overrides),
        "sources": sampling.explain(model_defaults, None, overrides),
        # The OpenAI dialect has no endpoint reporting a model's own
        # parameters, and accepts only two of these knobs. Said plainly rather
        # than leaving the panel to imply otherwise.
        "reports_model_defaults": bool(shown),
    }


@router.put("/sampling")
def save_sampling_settings(body: SamplingBody) -> dict:
    """Replace the overrides. An empty dict is how "use the model's own
    recommendations again" is expressed: there is no separate reset route,
    because reset *is* having no override."""
    clean = {
        key: value
        for key, value in body.overrides.items()
        if key in sampling.KNOBS_BY_NAME
    }
    deps.get_config().set_preference("sampling_overrides", clean)
    return {"overrides": clean}


@router.get("/suggested")
def suggested() -> dict:
    """The shortlist, with the real download size wherever we know it.

    Reported: "the approximate sizes for the suggested models are not
    correct" (§35J). They are hand-written: §33 defends the hand-written
    *list* against odysseus's Cookbook, and that argument still holds, but a
    hand-written *number* is a different thing: it goes stale every time a
    publisher re-quantises a tag, and a wrong number is worse than none, since
    it is the figure someone checks their free disk against.

    Two halves, and only one of them is guessable. For a model that is
    installed, the backend knows exactly how many bytes it took, so that
    number replaces the guess and is marked `measured`. For one that is not,
    there is no local source of truth, so the shipped figure is passed
    through and marked `approximate` rather than quietly presented as fact.
    The alternative, asking a registry over the network, is a call this app
    should not make just to draw a settings list.
    """
    installed: dict[str, int] = {}
    try:
        for model in deps.get_ollama().list_models():
            size = model.get("size")
            if size:
                installed[str(model.get("name", ""))] = int(size)
    except Exception:  # noqa: BLE001  # the backend being off is not an error here
        installed = {}

    def described(entry: dict) -> dict:
        real = installed.get(entry["name"])
        if real:
            return {**entry, "size": _human_bytes(real), "size_source": "measured"}
        return {**entry, "size_source": "approximate"}

    return {kind: [described(m) for m in models] for kind, models in SUGGESTED_MODELS.items()}


def _human_bytes(count: int) -> str:
    """Bytes as the size a download dialog would show."""
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f} GB"
    return f"{round(count / 1_000_000)} MB"


@router.post("/chat-model")
def set_chat_model(body: ChatModelBody, session: Session = Depends(get_session)) -> dict:
    """Switching the chat model applies immediately, no re-index (§6.5)."""
    ollama = deps.get_ollama()
    if not ollama.is_running():
        raise HTTPException(
            status_code=409, detail=f"{_backend_label()} isn't running"
        )
    if not _name_matches(body.name, _installed_models(True)):
        raise HTTPException(
            status_code=400,
            detail=f"'{body.name}' isn't available on {_backend_label()}",
        )
    deps.get_model_manager().set_chat_model(body.name)
    log_action(session, "edited", "preferences", detail=f"chat_model={body.name}")
    session.commit()
    return {"chat_model": body.name}


@router.post("/utility-model")
def set_utility_model(body: UtilityModelBody, session: Session = Depends(get_session)) -> dict:
    """Point background jobs (filing, digest, writing fixes) at a small
    fast model, separate from the chat model. Empty name = use
    the chat model."""
    name = body.name.strip()
    if name and deps.get_ollama().is_running():
        if not _name_matches(name, _installed_models(True)):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' isn't available on {_backend_label()}",
            )
    deps.get_model_manager().set_utility_model(name)
    log_action(session, "edited", "preferences", detail=f"utility_model={name or '(chat)'}")
    session.commit()
    return {"utility_model": name}


@router.post("/vision-model")
def set_vision_model(body: VisionModelBody, session: Session = Depends(get_session)) -> dict:
    """Which model an image-carrying chat turn uses. Empty name = auto-detect
    (the first installed model that declares the "vision" capability)."""
    name = body.name.strip()
    if name and deps.get_ollama().is_running():
        if not _name_matches(name, _installed_models(True)):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' isn't available on {_backend_label()}",
            )
    deps.get_model_manager().set_vision_model(name)
    log_action(session, "edited", "preferences", detail=f"vision_model={name or '(auto)'}")
    session.commit()
    return {"vision_model": name}


@router.post("/ocr-model")
def set_ocr_model(body: VisionModelBody, session: Session = Depends(get_session)) -> dict:
    """Which model reads text off an image or a rasterised PDF page.

    Empty name falls back to the vision model, and then to auto-detect, see
    `ModelManager.ocr_model` for why reading a page and describing a picture
    deserve separate settings even though both take an image.
    """
    name = body.name.strip()
    if name and deps.get_ollama().is_running():
        if not _name_matches(name, _installed_models(True)):
            raise HTTPException(
                status_code=400,
                detail=f"'{name}' isn't available on {_backend_label()}",
            )
    deps.get_model_manager().set_ocr_model(name)
    log_action(session, "edited", "preferences", detail=f"ocr_model={name or '(vision)'}")
    session.commit()
    return {"ocr_model": name}


@router.post("/provider")
def set_provider(body: ProviderBody, session: Session = Depends(get_session)) -> dict:
    """Point the app at a different chat backend (§6).

    Applies immediately rather than at the next restart, switching backend is
    exactly the moment someone wants to see whether it worked, and "restart the
    app to find out" turns one question into three.

    The probe result is reported, not enforced. A server that is down right now
    is a perfectly reasonable thing to configure, you set the URL, then you
    start LM Studio: so this saves the setting either way and tells the UI
    what it found, rather than refusing a setting that will be correct in
    thirty seconds.
    """
    config = deps.get_config()
    base_url = body.base_url.strip()

    # A backend address is a new outbound surface: the server posts the user's
    # notes to whatever it names, on every turn. Private and loopback
    # addresses are the *normal* case here and are allowed, that is the whole
    # product: but the narrow set nobody serves a model from is refused, and
    # a backend that would take notes off this machine is reported rather than
    # blocked. See core.security.check_backend_url.
    effective = base_url or deps.DEFAULT_BASE_URLS.get(body.provider, "")
    allowed, reason, is_local = security.check_backend_url(
        effective, local_only=bool(config.get_preference("local_only_ai", True))
    )
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)

    config.set_preference("llm_provider", body.provider)
    config.set_preference("llm_base_url", base_url)
    if body.api_key is not None:
        config.set_preference("llm_api_key", body.api_key.strip())
    deps.reload_llm_client()

    client = deps.get_ollama()
    running = client.is_running()
    models: list[dict] = []
    if running:
        try:
            models = client.list_models()
        except OllamaError:
            models = []

    log_action(
        session,
        "edited",
        "preferences",
        detail=f"llm_provider={body.provider} base_url={base_url or '(default)'}",
    )
    session.commit()
    return {
        "provider": body.provider,
        "base_url": client.base_url,
        "reachable": running,
        "supports_pull": client.supports_pull(),
        "installed_models": models,
        # False means the notes leave this machine to be answered. The app's
        # headline promise is that they don't, so this is said out loud rather
        # than decided on the user's behalf.
        "is_local": is_local,
        "privacy_note": reason,
    }


@router.post("/jobs/cancel")
def cancel_job(kind: str, name: str = "") -> dict:
    """Quit a stuck or slow background job from Settings → Tasks.
    kind is 'reindex' or 'pull' (with the model name for a pull)."""
    if kind == "reindex":
        stopped = jobs.cancel_reindex()
    elif kind == "pull":
        stopped = jobs.cancel_pull(name)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown job kind '{kind}'")
    if not stopped:
        raise HTTPException(status_code=404, detail="No such job is running")
    return {"cancelling": True, "kind": kind, "name": name}


@router.post("/embedding-backend")
def set_embedding_backend(
    body: EmbeddingBackendBody, session: Session = Depends(get_session)
) -> dict:
    """Switch how notes are embedded, then re-index everything, vectors
    from different models must never be compared (§6.5)."""
    if body.backend == "ollama" and not body.model:
        raise HTTPException(status_code=400, detail="Pick an Ollama embedding model")
    current = jobs.reindex_status()
    if current is not None and current["status"] == "running":
        raise HTTPException(status_code=409, detail="A re-index is already running")

    deps.get_model_manager().set_embedding_backend(body.backend, body.model)
    log_action(
        session,
        "edited",
        "preferences",
        detail=f"embedding_backend={body.backend} model={body.model or '-'}",
    )
    session.commit()

    # Switching backend is a fresh start: drop any cached failure so the
    # re-index retries right away and the stale error banner clears at once
    # instead of lingering for the retry-cooldown (bug: a fixed torch/Ollama
    # still showed the old "search engine problem" until the cooldown lapsed).
    embeddings = deps.get_embeddings()
    embeddings.reset_failure_state()
    jobs.start_reindex(deps.get_db(), embeddings)
    deps.clear_index_stale()
    return {"reindex_started": True}


@router.post("/reindex")
def rebuild_search_index() -> dict:  # noqa: D401  # see the long docstring below
    """Re-embed every note with the current backend, on demand.

    **Until now the only way to rebuild the index was to switch embedding
    backend and switch back.** `set_embedding_backend` above starts a
    re-index because it must, vectors from two models cannot be compared , 
    and that side effect was the *whole* mechanism: nothing else in the app
    could ask for one.

    That matters because a stale index is not always the user's doing. What a
    note's vector is built from is `embedding_text`, and this app has changed
    it: a note's category, tags and attachment text are part of it now, so
    every vector written before that change encodes less than the same note
    would encode today. Reported directly, and it is exactly the shape that
    produces: *"I have a whole category called hobbies but basically none
    came up in the semantic search."* The fix for that shipped; without a way
    to rebuild, it reaches nobody's existing notes.

    Deliberately cheap to offer and safe to run: re-embedding is idempotent,
    the job is the same one `set_embedding_backend` starts, and while it runs
    semantic search falls back to keywords rather than comparing mismatched
    vectors (§6.5). A 409 rather than a second job if one is already going.
    """
    current = jobs.reindex_status()
    if current is not None and current["status"] == "running":
        raise HTTPException(status_code=409, detail="A re-index is already running")
    embeddings = deps.get_embeddings()
    # Same reset as the backend switch: a cached failure from an earlier run
    # would otherwise make a deliberate rebuild sit behind the retry cooldown
    # and look like it did nothing.
    embeddings.reset_failure_state()
    started = jobs.start_reindex(deps.get_db(), embeddings)
    #: Only on a rebuild that actually started: clearing the backlog for a
    #: request that was refused would hide the very thing it counts.
    if started:
        deps.clear_index_stale()
    return {"reindex_started": bool(started)}


@router.post("/delete")
def delete_model(body: PullBody, session: Session = Depends(get_session)) -> dict:
    """Uninstall a model from Ollama to reclaim disk. Refuses to remove a
    model that's currently in use (chat, utility, or Ollama embeddings), so
    the app can't be left pointing at a model that no longer exists."""
    ollama = deps.get_ollama()
    if not ollama.is_running():
        raise HTTPException(
            status_code=409, detail=f"{_backend_label()} isn't running"
        )
    manager = deps.get_model_manager()
    in_use = {manager.chat_model()}
    if manager._config.get_preference("utility_model", ""):
        in_use.add(manager.utility_model())
    if manager.embedding_backend() == "ollama":
        in_use.add(manager.embedding_model())
    base = body.name.split(":")[0]
    if body.name in in_use or base in {m.split(":")[0] for m in in_use}:
        raise HTTPException(
            status_code=409,
            detail=f"'{body.name}' is in use: switch to another model first, then remove it.",
        )
    try:
        ollama.delete(body.name)
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log_action(session, "deleted", "model", detail=body.name)
    session.commit()
    return {"deleted": True, "name": body.name}


@router.post("/pull")
def pull_model(body: PullBody, session: Session = Depends(get_session)) -> dict:
    if not deps.get_ollama().is_running():
        raise HTTPException(
            status_code=409, detail=f"{_backend_label()} isn't running"
        )
    if not jobs.start_pull(deps.get_ollama(), body.name):
        raise HTTPException(status_code=409, detail=f"Already downloading {body.name}")
    log_action(session, "downloaded", "model", detail=body.name)
    session.commit()
    return {"pull_started": True, "name": body.name}
