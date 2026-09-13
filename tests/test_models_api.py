"""The Model Manager endpoints, fully offline via fakes."""

from __future__ import annotations

import time

from sqlalchemy import select

from memorymap.ai.embeddings import EmbeddingService
from memorymap.core import deps
from memorymap.core.database import EmbeddingRecord
from tests.fakes import FakeOllama


def _wait_for(client, check, timeout: float = 5.0) -> dict:
    """Poll /models/status until `check(status)` is true (background jobs)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/models/status").json()
        if check(body):
            return body
        time.sleep(0.05)
    raise AssertionError("timed out waiting for background job")


def test_status_with_all_ai_down(client):
    body = client.get("/models/status").json()
    assert body["ollama_running"] is False
    assert body["installed_models"] == []
    assert body["chat_model"] == "llama3.2"
    assert body["chat_model_installed"] is None  # unknown while Ollama is off
    assert body["embedding_backend"] == "sentence-transformers"
    assert body["embedding_ready"] is False
    assert body["pulls"] == {}


def test_suggested_catalog(client):
    body = client.get("/models/suggested").json()
    assert "llama3.2" in [m["name"] for m in body["text"]]
    assert "nomic-embed-text" in [m["name"] for m in body["embedding"]]


# --- the status pill: warming vs failed -----------------------------------------


def test_status_reports_embedding_error(client):
    body = client.get("/models/status").json()
    assert "embedding_warming" in body
    assert "embedding_error" in body


def test_embedding_failure_is_recorded_not_swallowed(app_state, monkeypatch):
    # Force the model load to fail deterministically. An offline machine
    # fails because the model isn't cached, but a networked CI runner would
    # download the real model and succeed, which isn't what this test is
    # about. We're checking that a genuine failure is RECORDED (last_error)
    # and not swallowed into a forever "warming up…" state (user-reported bug).
    service = EmbeddingService(deps.get_model_manager(), FakeOllama(running=False))

    def boom():
        raise RuntimeError("no embedding model available (forced for test)")

    monkeypatch.setattr(service, "_load_st_model", boom)
    assert service.embed_text("hello") is None
    assert service.last_error is not None
    assert service.is_ready() is False


def test_set_chat_model_requires_installed(ai_client):
    denied = ai_client.post("/models/chat-model", json={"name": "qwen2.5:3b"})
    assert denied.status_code == 400

    ok = ai_client.post("/models/chat-model", json={"name": "llama3.2"})
    assert ok.status_code == 200
    assert deps.get_config().get_preference("chat_model") == "llama3.2"


def test_set_chat_model_needs_ollama(client):
    assert client.post("/models/chat-model", json={"name": "llama3.2"}).status_code == 409


def test_pull_streams_progress_to_status(ai_client, fake_ollama):
    assert ai_client.post("/models/pull", json={"name": "nomic-embed-text"}).status_code == 200

    body = _wait_for(
        ai_client, lambda b: b["pulls"].get("nomic-embed-text", {}).get("status") == "success"
    )
    job = body["pulls"]["nomic-embed-text"]
    assert job["total"] == 1_000 and job["done"] == 1_000
    # The fake now reports it installed, like real Ollama would.
    assert any(m["name"] == "nomic-embed-text" for m in body["installed_models"])


def test_switch_embedding_backend_reindexes_everything(ai_client, fake_embeddings):
    ai_client.post("/entries", json={"content": "a funny scarecrow joke"})
    ai_client.post("/entries", json={"content": "buy milk and eggs"})

    response = ai_client.post(
        "/models/embedding-backend",
        json={"backend": "ollama", "model": "nomic-embed-text"},
    )
    assert response.status_code == 200

    _wait_for(ai_client, lambda b: (b["reindex"] or {}).get("status") == "success")

    config = deps.get_config()
    assert config.get_preference("embedding_backend") == "ollama"
    assert config.get_preference("embedding_model") == "nomic-embed-text"

    # Every entry got a fresh vector from the (fake) active backend.
    session = deps.get_db().session()
    try:
        records = list(session.scalars(select(EmbeddingRecord)))
        assert len(records) == 2
        assert {r.model_version for r in records} == {"fake:keywords-v1"}
    finally:
        session.close()


def test_embedding_switch_requires_model_for_ollama(ai_client):
    response = ai_client.post("/models/embedding-backend", json={"backend": "ollama"})
    assert response.status_code == 400


# --- the utility model (separate from the chat model, for cheap background jobs) --


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_utility_model_defaults_to_chat_model(app_state):
    manager = deps.get_model_manager()
    assert manager.utility_model() == manager.chat_model()
    manager.set_utility_model("phi3.5")
    assert manager.utility_model() == "phi3.5"
    manager.set_utility_model("")  # back to "same as chat"
    assert manager.utility_model() == manager.chat_model()


def test_status_reports_utility_model(client):
    body = client.get("/models/status").json()
    assert "utility_model" in body
    assert body["utility_model"] == ""  # unset by default


def test_set_utility_model_offline_still_saves(client):
    # Ollama unavailable in this fixture, an empty name always applies.
    assert client.post("/models/utility-model", json={"name": ""}).status_code == 200


def test_digest_uses_utility_model(ai_client, fake_ollama):
    deps.get_model_manager().set_utility_model("phi3.5")
    _save(ai_client, "a funny scarecrow joke")
    ai_client.post("/insights/digest")
    # The last chat call went to the utility model, not the chat model.
    assert fake_ollama.chat_models[-1] == "phi3.5"


# --- vision model (auto-detect or explicit) ---------------------------------


def test_vision_model_defaults_to_auto(app_state):
    manager = deps.get_model_manager()
    assert manager.vision_model() == ""


def test_resolve_vision_model_explicit_choice_wins(app_state, fake_ollama):
    manager = deps.get_model_manager()
    manager.set_vision_model("llama3.2-vision")
    # Wins even though nothing installed declares "vision", the same trust
    # chat_model() already extends an unverified explicit choice.
    assert manager.resolve_vision_model(fake_ollama) == "llama3.2-vision"


def test_resolve_vision_model_auto_detects_from_capabilities(app_state, fake_ollama):
    manager = deps.get_model_manager()
    fake_ollama.capabilities_declared = ["vision", "tools"]
    assert manager.resolve_vision_model(fake_ollama) == fake_ollama.installed[0]["name"]


def test_resolve_vision_model_is_none_when_nothing_declares_it(app_state, fake_ollama):
    manager = deps.get_model_manager()
    fake_ollama.capabilities_declared = ["tools"]  # no vision
    assert manager.resolve_vision_model(fake_ollama) is None


def test_status_reports_vision_model(client):
    body = client.get("/models/status").json()
    assert body["vision_model"] == ""
    assert body["vision_model_resolved"] is None  # Ollama not running (client fixture)


def test_set_vision_model_offline_still_saves(client):
    assert client.post("/models/vision-model", json={"name": ""}).status_code == 200


def test_set_vision_model_rejects_a_name_not_installed(ai_client):
    response = ai_client.post("/models/vision-model", json={"name": "not-a-real-model"})
    assert response.status_code == 400


def test_set_vision_model_persists(ai_client):
    ai_client.post("/models/vision-model", json={"name": "llama3.2"})
    assert deps.get_model_manager().vision_model() == "llama3.2"
    body = ai_client.get("/models/status").json()
    assert body["vision_model"] == "llama3.2"


# --- rebuilding the search index on demand ---------------------------------------
#
# Until this endpoint existed the *only* way to re-embed a notebook was to
# switch embedding backend and switch back: `set_embedding_backend` starts a
# re-index because it has to (vectors from two models cannot be compared), and
# that side effect was the whole mechanism.
#
# A stale index is not always the user's doing, though. `embedding_text`, what
# a vector is actually built from, has changed in this app to include a note's
# category, tags and attachment text, so vectors written before that encode
# less than the same note would today. Reported directly: "I have a whole
# category called hobbies but basically none came up in the semantic search."


def test_a_rebuild_can_be_asked_for_directly(ai_client, fake_embeddings):
    ai_client.post("/entries", json={"content": "seraphine and warwick", "category": "Hobbies"})
    ai_client.post("/entries", json={"content": "buy milk and eggs"})

    response = ai_client.post("/models/reindex")
    assert response.status_code == 200
    assert response.json()["reindex_started"] is True

    _wait_for(ai_client, lambda b: (b["reindex"] or {}).get("status") == "success")

    session = deps.get_db().session()
    try:
        records = list(session.scalars(select(EmbeddingRecord)))
        assert len(records) == 2
        assert {r.model_version for r in records} == {"fake:keywords-v1"}
    finally:
        session.close()


def test_a_rebuild_does_not_change_which_backend_is_in_use(ai_client, fake_embeddings):
    """It re-embeds with the *current* backend. A rebuild that quietly moved
    the user to a different one would be a settings change wearing a
    maintenance button's clothes."""
    config = deps.get_config()
    before = (
        config.get_preference("embedding_backend"),
        config.get_preference("embedding_model"),
    )
    ai_client.post("/entries", json={"content": "something to embed"})
    assert ai_client.post("/models/reindex").status_code == 200
    _wait_for(ai_client, lambda b: (b["reindex"] or {}).get("status") == "success")
    assert (
        config.get_preference("embedding_backend"),
        config.get_preference("embedding_model"),
    ) == before


def test_a_second_rebuild_while_one_runs_is_refused(ai_client, fake_embeddings, monkeypatch):
    """409, not a second thread racing the first over the same rows."""
    monkeypatch.setattr(
        "memorymap.api.routes_models.jobs.reindex_status",
        lambda: {"status": "running", "done": 1, "total": 9},
    )
    response = ai_client.post("/models/reindex")
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]
