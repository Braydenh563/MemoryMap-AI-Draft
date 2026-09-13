"""Conversations: lifecycle, turns, retitling, personas.

(The embedding status-pill tests that used to live here moved to
test_models_api.py: same domain as the rest of /models/status's
coverage.)"""

from __future__ import annotations

from memorymap.ai import librarian


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- conversations ----------------------------------------------------------------


def test_conversation_lifecycle(client):
    created = client.post(
        "/conversations",
        json={"question": "what jokes have I saved?", "answer": "A scarecrow one."},
    ).json()
    assert created["title"].startswith("what jokes")
    assert created["turns"] == 1

    client.post(
        f"/conversations/{created['id']}/turns",
        json={"question": "any more?", "answer": "No.", "thinking": "hmm"},
    )
    full = client.get(f"/conversations/{created['id']}").json()
    assert full["turns"] == 2
    assert full["messages"][2]["content"] == "any more?"
    assert full["messages"][3]["thinking"] == "hmm"

    client.put(f"/conversations/{created['id']}", json={"title": "Joke hunt"})
    assert client.get("/conversations").json()[0]["title"] == "Joke hunt"

    client.delete(f"/conversations/{created['id']}")
    assert client.get("/conversations").json() == []


def test_browsing_conversations_sees_as_many_as_searching_does(client):
    """The no-search-term branch capped at 50 while the with-term branch
    capped at 200: browsing without typing a search saw fewer chats than
    searching for one did, with no way to reach the rest either way."""
    for i in range(60):
        client.post("/conversations", json={"question": f"q{i}", "answer": "a"})
    assert len(client.get("/conversations").json()) == 60


def test_retitle_uses_ai(ai_client, fake_ollama):
    created = ai_client.post(
        "/conversations", json={"question": "what jokes have I saved?", "answer": "A few."}
    ).json()
    fake_ollama.librarian_reply = "Saved jokes"
    named = ai_client.post(f"/conversations/{created['id']}/retitle").json()
    assert named["title"] == "Saved jokes"
    assert named["ai_named"] is True


def test_retitle_is_sentence_cased(ai_client, fake_ollama):
    created = ai_client.post(
        "/conversations", json={"question": "any jokes?", "answer": "One."}
    ).json()
    fake_ollama.librarian_reply = "saved jokes"
    named = ai_client.post(f"/conversations/{created['id']}/retitle").json()
    assert named["title"] == "Saved jokes"


def test_retitle_uses_the_active_persona(ai_client, fake_ollama):
    ai_client.put(
        "/preferences",
        json={
            "personas": [{"name": "Pirate", "prompt": "You are a pirate captain."}],
            "active_persona": "Pirate",
        },
    )
    created = ai_client.post(
        "/conversations", json={"question": "where is the treasure?", "answer": "Here."}
    ).json()
    fake_ollama.librarian_reply = "Treasure hunt"
    ai_client.post(f"/conversations/{created['id']}/retitle")
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "pirate captain" in system.lower()


def test_retitle_falls_back_without_ai(ai_client, fake_ollama):
    created = ai_client.post(
        "/conversations", json={"question": "how do I bake bread?", "answer": "Slowly."}
    ).json()
    fake_ollama.running = False
    named = ai_client.post(f"/conversations/{created['id']}/retitle").json()
    assert named["ai_named"] is False
    assert named["title"].startswith("how do I bake bread")


def test_retitle_rejects_a_rambling_title(ai_client, fake_ollama):
    created = ai_client.post(
        "/conversations", json={"question": "tell me about pasta", "answer": "Sure."}
    ).json()
    fake_ollama.librarian_reply = (
        "Of course! Here is a great title for this particular conversation about food."
    )
    named = ai_client.post(f"/conversations/{created['id']}/retitle").json()
    assert named["ai_named"] is False
    assert named["title"].startswith("tell me about pasta")


def test_delete_conversation_turn(client):
    created = client.post(
        "/conversations",
        json={"question": "first?", "answer": "one"},
    ).json()
    client.post(
        f"/conversations/{created['id']}/turns",
        json={"question": "second?", "answer": "two"},
    )
    client.post(
        f"/conversations/{created['id']}/turns",
        json={"question": "third?", "answer": "three"},
    )

    # Drop the middle exchange (turn index 1).
    summary = client.delete(f"/conversations/{created['id']}/turns/1").json()
    assert summary["turns"] == 2

    full = client.get(f"/conversations/{created['id']}").json()
    contents = [m["content"] for m in full["messages"]]
    assert contents == ["first?", "one", "third?", "three"]

    # Out-of-range index is a clean 404, not a crash. The request is made
    # outside the assert so it still runs under `python -O`.
    missing = client.delete(f"/conversations/{created['id']}/turns/9")
    assert missing.status_code == 404


def test_conversation_persists_tool_chips(client):
    """Tool-activity chips are saved on the turn so they survive a reload."""
    created = client.post(
        "/conversations",
        json={
            "question": "tidy my tags",
            "answer": "Done.",
            "tools": [{"label": "Merged 2 tags", "ok": True}],
        },
    ).json()
    full = client.get(f"/conversations/{created['id']}").json()
    assert full["messages"][1]["tools"][0]["label"] == "Merged 2 tags"
    assert full["messages"][1]["tools"][0]["ok"] is True


def test_conversation_persists_which_mode_answered(client):
    """ROADMAP §89.4: a saved turn remembers whether Ask or Request answered
    it, so a conversation that spans mode switches shows the right label on
    reload instead of whatever the live toggle happens to show now."""
    created = client.post(
        "/conversations",
        json={"question": "search my notes", "answer": "Found 3.", "used_tools": False},
    ).json()
    client.post(
        f"/conversations/{created['id']}/turns",
        json={"question": "tag them all urgent", "answer": "Done.", "used_tools": True},
    )
    full = client.get(f"/conversations/{created['id']}").json()
    assistants = [m for m in full["messages"] if m["role"] == "assistant"]
    assert assistants[0]["used_tools"] is False
    assert assistants[1]["used_tools"] is True


def test_conversation_omits_used_tools_when_not_sent(client):
    """Older/unset turns get no key at all, not a misleading False."""
    created = client.post(
        "/conversations", json={"question": "hi", "answer": "hello"}
    ).json()
    full = client.get(f"/conversations/{created['id']}").json()
    assistant = [m for m in full["messages"] if m["role"] == "assistant"][0]
    assert "used_tools" not in assistant


def test_replace_last_turn_swaps_answer_in_place(client):
    """Regenerate replaces the last answer instead of appending a new one."""
    created = client.post(
        "/conversations",
        json={"question": "sum up my week", "answer": "first take"},
    ).json()
    cid = created["id"]
    client.post(f"/conversations/{cid}/turns", json={"question": "again", "answer": "v1"})

    resp = client.put(
        f"/conversations/{cid}/turns/last",
        json={"question": "again", "answer": "v2 (better)"},
    )
    assert resp.status_code == 200
    full = client.get(f"/conversations/{cid}").json()
    assert full["turns"] == 2  # not 3: the last pair was replaced, not added
    assert full["messages"][-1]["content"] == "v2 (better)"


def test_delete_turn_removes_one_exchange(client):
    created = client.post(
        "/conversations",
        json={"question": "q1", "answer": "a1"},
    ).json()
    cid = created["id"]
    client.post(f"/conversations/{cid}/turns", json={"question": "q2", "answer": "a2"})

    # Delete the first exchange (index 0): the second should remain and shift up.
    resp = client.delete(f"/conversations/{cid}/turns/0")
    assert resp.status_code == 200
    full = client.get(f"/conversations/{cid}").json()
    assert full["turns"] == 1
    assert full["messages"][0]["content"] == "q2"

    # Deleting the last remaining exchange removes the whole conversation.
    resp = client.delete(f"/conversations/{cid}/turns/0")
    assert resp.json().get("conversation_deleted") is True
    assert client.get("/conversations").json() == []


# --- personas ---------------------------------------------------------------------


def test_build_messages_keeps_grounding_with_persona():
    messages = librarian.build_messages(
        "q?", [{"content": "n", "category": "c"}], persona_prompt="You are a pirate."
    )
    system = messages[0]["content"]
    assert system.startswith("You are a pirate.")
    assert "ONLY the notes provided" in system  # grounding survives any persona


def test_chat_uses_selected_persona(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    ai_client.put(
        "/preferences",
        json={"personas": [{"name": "Pirate", "prompt": "You are a pirate captain."}]},
    )

    ai_client.post("/chat", json={"question": "any jokes?", "persona": "Pirate"})
    assert "pirate captain" in fake_ollama.chat_calls[-1][0]["content"].lower()

    # Built-ins work too, and unknown names fall back to the default.
    ai_client.post("/chat", json={"question": "any jokes?", "persona": "Coach"})
    assert "coach" in fake_ollama.chat_calls[-1][0]["content"].lower()
    ai_client.post("/chat", json={"question": "any jokes?", "persona": "Ghost"})
    assert "librarian" in fake_ollama.chat_calls[-1][0]["content"].lower()


def test_edited_builtin_persona_overrides_and_resets(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    # Editing a built-in stores an override under the same name…
    ai_client.put(
        "/preferences",
        json={"personas": [{"name": "Librarian", "prompt": "You are a grumpy archivist."}]},
    )
    ai_client.post("/chat", json={"question": "any jokes?", "persona": "Librarian"})
    assert "grumpy archivist" in fake_ollama.chat_calls[-1][0]["content"].lower()

    # …and removing the override resets to the default prompt.
    ai_client.put("/preferences", json={"personas": []})
    ai_client.post("/chat", json={"question": "any jokes?", "persona": "Librarian"})
    assert "librarian of the user's personal notebook" in fake_ollama.chat_calls[-1][0][
        "content"
    ].lower()


def test_active_persona_preference_is_default(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    ai_client.put(
        "/preferences",
        json={
            "personas": [{"name": "Robot", "prompt": "You are a terse robot."}],
            "active_persona": "Robot",
        },
    )
    ai_client.post("/chat", json={"question": "any jokes?"})  # no persona sent
    assert "terse robot" in fake_ollama.chat_calls[-1][0]["content"].lower()


def test_truncate_drops_a_turn_and_everything_after_it(client):
    """Editing a question must clear the replies to the old wording."""
    created = client.post(
        "/conversations", json={"question": "q1", "answer": "a1"}
    ).json()
    cid = created["id"]
    client.post(f"/conversations/{cid}/turns", json={"question": "q2", "answer": "a2"})
    client.post(f"/conversations/{cid}/turns", json={"question": "q3", "answer": "a3"})

    result = client.post(f"/conversations/{cid}/truncate", json={"from_turn": 1}).json()
    assert result["removed"] == 2
    assert result["conversation_deleted"] is False

    full = client.get(f"/conversations/{cid}").json()
    assert [m["content"] for m in full["messages"]] == ["q1", "a1"]


def test_truncating_from_the_first_turn_removes_the_conversation(client):
    created = client.post(
        "/conversations", json={"question": "only", "answer": "one"}
    ).json()
    result = client.post(
        f"/conversations/{created['id']}/truncate", json={"from_turn": 0}
    ).json()
    assert result["conversation_deleted"] is True
    assert client.get("/conversations").json() == []


def test_truncating_past_the_end_changes_nothing(client):
    created = client.post("/conversations", json={"question": "q", "answer": "a"}).json()
    result = client.post(
        f"/conversations/{created['id']}/truncate", json={"from_turn": 9}
    ).json()
    assert result["removed"] == 0
    full = client.get(f"/conversations/{created['id']}").json()
    assert len(full["messages"]) == 2


def test_a_turn_can_record_the_agent_run_step_by_step(client):
    """The chat shows the agent's work as an ordered timeline, so reopening a
    conversation has to reproduce that order rather than a flattened summary.

    Steps live alongside the existing answer/thinking/tools fields rather than
    replacing them, so a chat saved before steps existed still renders.
    """
    steps = [
        {"kind": "thinking", "text": "I should look this up."},
        {"kind": "tool", "label": "ph:magnifying-glass Searched notes", "ok": True},
        {"kind": "answer", "text": "You have three notes about it."},
    ]
    created = client.post(
        "/conversations",
        json={
            "question": "what do I know?",
            "answer": "You have three notes about it.",
            "thinking": "I should look this up.",
            "tools": [{"label": "ph:magnifying-glass Searched notes", "ok": True}],
            "steps": steps,
        },
    ).json()

    messages = client.get(f"/conversations/{created['id']}").json()["messages"]
    assistant = messages[1]
    assert assistant["steps"] == steps
    # The flattened fields stay, so nothing that reads them breaks.
    assert assistant["content"] == "You have three notes about it."
    assert assistant["tools"] == [{"label": "ph:magnifying-glass Searched notes", "ok": True}]


def test_a_turn_without_steps_still_saves(client):
    """Older clients (and the plain non-agent path) send no steps at all."""
    created = client.post(
        "/conversations", json={"question": "hi", "answer": "hello"}
    ).json()
    assistant = client.get(f"/conversations/{created['id']}").json()["messages"][1]
    assert "steps" not in assistant


def test_a_chat_past_the_page_is_still_reachable_and_findable(client):
    """**The old cap made an old chat unreachable, and unsearchable too.**

    `list_conversations` was a flat `.limit(200)` with no offset, and the
    search filtered *after* it: the post-filter ran over the 200 most recent
    rows, so a chat older than that could not be opened from the sidebar and
    could not be found by searching for its own words either. Same finding as
    INBOX 117 on documents, reminders and media, one list later.
    """
    from memorymap.api import routes_conversations

    size = routes_conversations.CONVERSATIONS_PAGE_SIZE
    oldest = client.post(
        "/conversations", json={"question": "zarquon the marmoset", "answer": "yes"}
    ).json()["id"]
    for index in range(size + 5):
        client.post("/conversations", json={"question": f"Chat {index}", "answer": "ok"})

    first = client.get("/conversations")
    assert len(first.json()) == size
    assert first.headers["X-Total-Count"] == str(size + 6)

    rest = client.get("/conversations", params={"offset": size})
    assert len(rest.json()) == 6
    seen = {c["id"] for c in first.json()} | {c["id"] for c in rest.json()}
    assert oldest in seen, "the oldest chat is past the first page and must still be listed"

    # And searchable: the word is only in the chat the first page does not hold.
    found = client.get("/conversations", params={"q": "zarquon"})
    assert [c["id"] for c in found.json()] == [oldest]
    assert found.headers["X-Total-Count"] == "1"


def test_a_search_pages_over_its_own_matches(client):
    """A searched page counts matches, not rows scanned: a caller paging a
    search must not loop past the end of its own results."""
    for index in range(5):
        client.post("/conversations", json={"question": f"marmoset {index}", "answer": "ok"})
    client.post("/conversations", json={"question": "something else", "answer": "ok"})

    page = client.get("/conversations", params={"q": "marmoset", "limit": 2})
    assert len(page.json()) == 2
    assert page.headers["X-Total-Count"] == "5"
    tail = client.get("/conversations", params={"q": "marmoset", "limit": 2, "offset": 4})
    assert len(tail.json()) == 1
