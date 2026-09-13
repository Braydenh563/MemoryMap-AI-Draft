"""Recent questions, most-accessed entries, user profile."""

from __future__ import annotations

from memorymap.ai import librarian
from memorymap.core import deps
from tests.fakes import FakeOllama


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def _ask(client, question):
    response = client.post("/chat", json={"question": question})
    assert response.status_code == 200
    return response.json()


def test_recent_questions_last_five_distinct(client):
    for i in range(7):
        _ask(client, f"question {i}")
    _ask(client, "question 6")  # repeat: must not duplicate

    recent = client.get("/chat/recent").json()
    assert recent == ["question 6", "question 5", "question 4", "question 3", "question 2"]


def test_access_counts_and_most_accessed(ai_client):
    joke = _save(ai_client, "a funny scarecrow joke")
    _save(ai_client, "buy milk and eggs")

    # Matching a question and opening the entry both count as "used".
    _ask(ai_client, "any funny jokes?")
    ai_client.get(f"/entries/{joke['id']}")

    top = ai_client.get("/entries/most-accessed").json()
    assert [e["id"] for e in top] == [joke["id"]]
    assert top[0]["access_count"] == 2

    # Untouched entries never appear in the dashboard.
    assert len(ai_client.get("/entries/most-accessed").json()) == 1


def test_profile_used_only_when_enabled(app_state):
    ollama = FakeOllama()
    notes = [{"content": "note", "category": "X"}]
    manager = deps.get_model_manager()

    librarian.answer("q?", notes, manager, ollama, profile="I live in Brisbane")
    assert "I live in Brisbane" in ollama.chat_calls[-1][0]["content"]

    librarian.answer("q?", notes, manager, ollama, profile="")
    assert "Brisbane" not in ollama.chat_calls[-1][0]["content"]


def test_chat_respects_profile_opt_out(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    ai_client.put(
        "/preferences",
        json={"user_profile": "I collect dad jokes", "profile_enabled": False},
    )
    _ask(ai_client, "any funny jokes?")
    assert "I collect dad jokes" not in fake_ollama.chat_calls[-1][0]["content"]

    ai_client.put("/preferences", json={"profile_enabled": True})
    _ask(ai_client, "any funny jokes?")
    assert "I collect dad jokes" in fake_ollama.chat_calls[-1][0]["content"]


def test_profile_delete_via_preferences(client):
    client.put("/preferences", json={"user_profile": "secret", "profile_enabled": True})
    client.put("/preferences", json={"user_profile": "", "profile_enabled": False})
    prefs = client.get("/preferences").json()
    assert prefs["user_profile"] == "" and prefs["profile_enabled"] is False
