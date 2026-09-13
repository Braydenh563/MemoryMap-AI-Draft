"""The Ask box's browsable history (routes_ask_history.py).

Every notes-only question the Ask box answers is now durable, the request
that led to this: *"I want the ask feature to be basically a personal notes
browser"*. `chat_stream` (routes_chat.py) writes the turn; this file only
reads, searches, pins and deletes.
"""

from __future__ import annotations

import json

from memorymap.entry import manager


def _ask(client, question, **body):
    with client.stream(
        "POST", "/chat/stream", json={"question": question, "notes_only": True, **body}
    ) as r:
        for line in r.iter_lines():
            if line.strip():
                json.loads(line)  # drain the stream


def test_a_real_question_is_saved_to_history(ai_client, fake_ollama, session):
    manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    _ask(ai_client, "what did I write about beans")

    body = ai_client.get("/ask-history").json()
    assert body["total"] == 1
    turn = body["turns"][0]
    assert turn["question"] == "what did I write about beans"
    assert "beans" in turn["answer_preview"].lower()
    assert turn["result_count"] == 1


def test_small_talk_is_not_saved(ai_client, fake_ollama):
    """A greeting on the Ask box never reaches the model (it hints instead),
    so there is no answer to save, see test_ask_focus.py."""
    fake_ollama.librarian_reply = "Hello there!"
    _ask(ai_client, "hey")
    assert ai_client.get("/ask-history").json()["total"] == 0


def test_the_chat_tab_never_writes_ask_history(ai_client, fake_ollama):
    """Only `notes_only` turns are the Ask box's own: the Chat tab already
    gets its own durable history via /conversations."""
    fake_ollama.librarian_reply = "Hello there!"
    with ai_client.stream("POST", "/chat/stream", json={"question": "hey"}) as r:
        for line in r.iter_lines():
            if line.strip():
                json.loads(line)
    assert ai_client.get("/ask-history").json()["total"] == 0


def test_search_matches_question_or_answer_text(ai_client, fake_ollama, session):
    manager.create_entry(session, "Sourdough proving times")
    session.commit()
    fake_ollama.librarian_reply = "Prove it for four hours."
    _ask(ai_client, "how long to prove sourdough")
    fake_ollama.librarian_reply = "You have three meetings."
    _ask(ai_client, "what meetings do I have")

    hits = ai_client.get("/ask-history", params={"q": "sourdough"}).json()["turns"]
    assert len(hits) == 1
    assert "sourdough" in hits[0]["question"].lower()

    hits = ai_client.get("/ask-history", params={"q": "four hours"}).json()["turns"]
    assert len(hits) == 1  # matched the answer text, not the question


def test_pagination_reports_a_total_independent_of_the_page(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    for i in range(3):
        _ask(ai_client, f"question number {i}")
    body = ai_client.get("/ask-history", params={"limit": 1, "offset": 0}).json()
    assert body["total"] == 3
    assert len(body["turns"]) == 1


def test_getting_one_turn_hydrates_its_notes(ai_client, fake_ollama, session):
    entry = manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    _ask(ai_client, "what did I write about beans")

    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]
    turn = ai_client.get(f"/ask-history/{turn_id}").json()
    assert turn["answer"] == "You wrote about netting the beans."
    assert [r["id"] for r in turn["raw_results"]] == [entry.id]
    assert turn["omitted_results"] == 0


def test_a_turn_s_match_info_survives_to_browse_it_back(ai_client, fake_ollama, session):
    """The badge the live Ask answer shows ("Matched 'beans'") must still be
    there when the same turn is reopened from history, the whole point of
    saving match_info/connected_ids alongside the turn (routes_chat.py's
    _save_ask_turn) rather than only the note ids."""
    entry = manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    _ask(ai_client, "what did I write about beans")

    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]
    turn = ai_client.get(f"/ask-history/{turn_id}").json()
    info = turn["match_info"][str(entry.id)]
    assert info["type"] == "keyword"
    assert "beans" in info["terms"]
    assert turn["connected_ids"] == []


def test_a_note_deleted_since_is_dropped_not_shown_stale(ai_client, fake_ollama, session):
    entry = manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    _ask(ai_client, "what did I write about beans")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]

    manager.soft_delete_entry(session, entry)
    session.commit()

    turn = ai_client.get(f"/ask-history/{turn_id}").json()
    assert turn["raw_results"] == []
    assert turn["omitted_results"] == 1


def test_a_note_made_private_since_is_also_dropped(ai_client, fake_ollama, session):
    entry = manager.create_entry(session, "The beans need netting next week")
    session.commit()
    fake_ollama.librarian_reply = "You wrote about netting the beans."
    _ask(ai_client, "what did I write about beans")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]

    entry.is_private = True
    session.commit()

    turn = ai_client.get(f"/ask-history/{turn_id}").json()
    assert turn["raw_results"] == []
    assert turn["omitted_results"] == 1


def test_getting_an_unknown_turn_404s(ai_client):
    assert ai_client.get("/ask-history/999999").status_code == 404


def test_pinning_a_turn(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    _ask(ai_client, "a question")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]

    body = ai_client.put(f"/ask-history/{turn_id}/pin", params={"pinned": True}).json()
    assert body["pinned"] is True
    assert ai_client.get("/ask-history", params={"pinned_only": True}).json()["total"] == 1


def test_deleting_one_turn(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    _ask(ai_client, "a question")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]

    response = ai_client.delete(f"/ask-history/{turn_id}")
    assert response.json() == {"deleted": True}
    assert ai_client.get("/ask-history").json()["total"] == 0


def test_clear_history_keeps_pinned_turns_by_default(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    _ask(ai_client, "keep me")
    _ask(ai_client, "drop me")
    turns = ai_client.get("/ask-history").json()["turns"]
    keep_id = next(t["id"] for t in turns if t["question"] == "keep me")
    ai_client.put(f"/ask-history/{keep_id}/pin", params={"pinned": True})

    body = ai_client.delete("/ask-history").json()
    assert body["deleted"] == 1
    remaining = ai_client.get("/ask-history").json()["turns"]
    assert [t["question"] for t in remaining] == ["keep me"]


def test_clear_history_can_also_wipe_pinned_turns(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    _ask(ai_client, "a question")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]
    ai_client.put(f"/ask-history/{turn_id}/pin", params={"pinned": True})

    body = ai_client.delete("/ask-history", params={"keep_pinned": False}).json()
    assert body["deleted"] == 1
    assert ai_client.get("/ask-history").json()["total"] == 0


def test_stats_reports_total_and_pinned(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "ok"
    _ask(ai_client, "one")
    _ask(ai_client, "two")
    turn_id = ai_client.get("/ask-history").json()["turns"][0]["id"]
    ai_client.put(f"/ask-history/{turn_id}/pin", params={"pinned": True})

    stats = ai_client.get("/ask-history/stats").json()
    assert stats == {"total": 2, "pinned": 1}
