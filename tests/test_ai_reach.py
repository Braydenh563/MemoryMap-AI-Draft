"""The AI reaching documents, past chats, and skills.

Three things the assistant couldn't do. Documents are deliberately kept out
of retrieval: a note is a captured thought, a document is something you sat
down and wrote, and mixing them would put every half-finished draft into
every search result. But "never retrieved automatically" had become "cannot
be read at all, even when asked". Past conversations were the same: each turn
only ever saw its own thread, so "what did we decide last week?" had no
answer. Skills could only be managed by hand.
"""

from __future__ import annotations

import json

from memorymap.ai import tools
from memorymap.core import deps


def _doc(client, title, content):
    response = client.post("/documents", json={"title": title, "content": content})
    assert response.status_code == 201
    return response.json()


def _chat(client, question, answer):
    response = client.post(
        "/conversations", json={"question": question, "answer": answer}
    )
    assert response.status_code == 201
    return response.json()


# --- documents --------------------------------------------------------------------


def test_the_model_can_list_and_read_documents(client, session):
    long_body = "The full plan. " + ("Detail sentence. " * 60)
    doc = _doc(client, "Sailing trip", long_body)
    _doc(client, "Tax notes", "Nothing to do with sailing.")

    listed = tools.execute_tool(session, "list_documents", {})
    assert listed["total_matching"] == 2
    preview = next(d for d in listed["documents"] if d["id"] == doc["id"])
    assert len(preview["preview"]) <= tools.PREVIEW_CHARS + 1
    assert preview["words"] > 50

    full = tools.execute_tool(session, "get_document", {"document_id": doc["id"]})
    assert full["content"] == long_body
    assert full["truncated"] is False


def test_documents_can_be_searched_by_body_text(client, session):
    wanted = _doc(client, "Untitled", "the spinnaker halyard needs replacing")
    _doc(client, "Other", "unrelated words entirely")

    found = tools.execute_tool(session, "list_documents", {"query": "spinnaker"})
    assert [d["id"] for d in found["documents"]] == [wanted["id"]]
    # The total must describe the same set as the rows, not everything.
    assert found["total_matching"] == 1


def test_a_very_long_document_is_capped_rather_than_flooding_the_window(client, session):
    doc = _doc(client, "Novel", "x" * (tools.DOCUMENT_CHARS + 5_000))
    full = tools.execute_tool(session, "get_document", {"document_id": doc["id"]})
    assert len(full["content"]) <= tools.DOCUMENT_CHARS
    assert full["truncated"] is True


def test_reading_a_missing_document_is_an_error_not_a_crash(client, session):
    result = tools.execute_tool(session, "get_document", {"document_id": 4321})
    assert "error" in result


def test_get_document_with_a_query_returns_the_relevant_paragraphs(client, session):
    """A query narrows a long document down to its most relevant chunks
    instead of a plain head-of-document truncation, RAG snippet extraction."""
    from tests.fakes import FakeEmbeddingService

    deps.override_ai(embeddings=FakeEmbeddingService(available=True))
    body = (
        "The 100m sprint final is the highlight of the athletics carnival.\n\n"
        "Why did the scarecrow win an award? He was outstanding in his field.\n\n"
        "One more unrelated thought that says nothing about any of this.\n\n"
        "Need to buy milk and eggs from the shops this week."
    )
    doc = _doc(client, "Mixed notes", body)

    result = tools.execute_tool(
        session, "get_document", {"document_id": doc["id"], "query": "milk"}
    )
    # The shopping paragraph is the only one that matches the query's topic: 
    # it should rank first even though it's last in the document.
    assert result["content"].startswith("Need to buy milk")
    assert "(extracted snippets for query)" in result["label"]


# --- past conversations ------------------------------------------------------------


def test_the_model_can_look_through_earlier_chats(client, session):
    _chat(client, "which tent did we settle on?", "The two-person Hilleberg.")
    _chat(client, "what's for dinner?", "Pasta.")

    found = tools.execute_tool(session, "search_chat_history", {"query": "tent"})
    assert found["found"] == 1
    texts = " ".join(e["text"] for e in found["conversations"][0]["excerpts"])
    assert "Hilleberg" in texts
    # The model must know this came from a past chat, not from their notes.
    assert "past conversation" in found["note_to_model"]


def test_an_empty_query_returns_the_most_recent_chats(client, session):
    _chat(client, "first", "a")
    _chat(client, "second", "b")
    found = tools.execute_tool(session, "search_chat_history", {})
    assert found["found"] == 2
    assert found["conversations"][0]["title"] == "second"


def test_chat_excerpts_are_clipped(client, session):
    _chat(client, "tell me about rope", "rope rope rope " * 200)
    found = tools.execute_tool(session, "search_chat_history", {"query": "rope"})
    for excerpt in found["conversations"][0]["excerpts"]:
        assert len(excerpt["text"]) <= tools.PREVIEW_CHARS + 1


# --- skills -------------------------------------------------------------------------


def _own(listed: dict) -> list[dict]:
    """The user's own skills: list_skills also returns the built-in ones now,
    because the model used to answer "you have no skills" while the interface
    showed ten."""
    return [skill for skill in listed["skills"] if not skill["builtin"]]


def test_the_model_can_list_create_update_and_delete_skills(client, session, app_state):
    assert _own(tools.execute_tool(session, "list_skills", {})) == []

    created = tools.execute_tool(
        session, "save_skill", {"name": "Weekly review", "prompt": "Summarise my week."}
    )
    assert created["updated"] is False
    listed = _own(tools.execute_tool(session, "list_skills", {}))
    assert len(listed) == 1
    assert listed[0]["name"] == "Weekly review"

    # Same name = update, not a duplicate.
    updated = tools.execute_tool(
        session,
        "save_skill",
        {"name": "Weekly review", "prompt": "Summarise my week, with next steps."},
    )
    assert updated["updated"] is True
    again = _own(tools.execute_tool(session, "list_skills", {}))
    assert len(again) == 1
    assert "next steps" in again[0]["prompt"]

    tools.execute_tool(session, "delete_skill", {"name": "Weekly review"})
    assert _own(tools.execute_tool(session, "list_skills", {})) == []


def test_the_model_sees_the_built_in_skills_too(client, session, app_state):
    """They lived in app.js, so "what skills do I have?" was answered without
    the ten the user could see on screen."""
    listed = tools.execute_tool(session, "list_skills", {})
    names = [skill["name"] for skill in listed["skills"]]
    assert any("Summarise my week" in name for name in names)
    assert all(skill["builtin"] for skill in listed["skills"])


def test_skills_survive_into_the_users_preferences(client, session, app_state):
    """The model writes to the same place the Settings UI reads."""
    tools.execute_tool(session, "save_skill", {"name": "Tidy", "prompt": "Tidy up."})
    saved = deps.get_config().get_preference("skills", [])
    assert [s for s in saved if s["name"] == "Tidy" and s["prompt"] == "Tidy up."]
    assert client.get("/preferences").json()["skills"][0]["name"] == "Tidy"


def test_a_bad_skill_is_refused_with_a_reason(client, session, app_state):
    for args in [
        {"name": "", "prompt": "something"},
        {"name": "ok", "prompt": ""},
        {"name": "x" * 50, "prompt": "something"},
    ]:
        result = tools.execute_tool(session, "save_skill", args)
        assert "error" in result, args


def test_deleting_a_skill_that_is_not_there_says_so(client, session, app_state):
    result = tools.execute_tool(session, "delete_skill", {"name": "Nonexistent"})
    assert "error" in result and "Nonexistent" in result["error"]


def test_deleting_a_skill_needs_the_users_confirmation(app_state):
    """Everything destructive is parked for a human, and the confirm card has
    to name what's about to happen rather than "Run delete_skill"."""
    assert tools.TOOLS["delete_skill"].destructive is True
    label = tools.confirm_label("delete_skill", {"name": "Weekly review"})
    assert "Weekly review" in label


def test_the_new_tools_are_offered_to_the_model(app_state):
    offered = {t["function"]["name"] for t in tools.ollama_tools()}
    assert {
        "list_documents",
        "get_document",
        "search_chat_history",
        "list_skills",
        "save_skill",
        "delete_skill",
    } <= offered


def test_none_of_the_new_tools_leak_a_private_note(client, session):
    """Documents and chats are separate stores, but a tool added later is
    exactly where the private-note rule gets forgotten."""
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    try:
        entry = client.post("/entries", json={"content": "codeword ELDERFLOWER"}).json()
        client.post(f"/entries/{entry['id']}/privacy", json={"private": True})

        for name in ["list_documents", "search_chat_history", "list_skills"]:
            blob = json.dumps(tools.execute_tool(session, name, {}))
            assert "ELDERFLOWER" not in blob, name
    finally:
        vault.close()
