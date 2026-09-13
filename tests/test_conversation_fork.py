"""Forking a conversation.

Asked for directly: "ability to fork conversations". The need is the one every
chat interface grows into, a thread reaches a good state and you want to try
a different direction *without losing the one you have*. Before this the only
way was to keep asking and then delete what you did not want, which is
destructive and cannot be undone.
"""

from __future__ import annotations

import json


def _chat(client, title, turns):
    made = client.post("/conversations", json={"question": turns[0][0], "answer": turns[0][1]})
    assert made.status_code == 201, made.text
    conversation_id = made.json()["id"]
    for question, answer in turns[1:]:
        client.post(f"/conversations/{conversation_id}/turns", json={"question": question, "answer": answer})
    client.put(f"/conversations/{conversation_id}", json={"title": title})
    return conversation_id


def _messages(client, conversation_id):
    return client.get(f"/conversations/{conversation_id}").json()["messages"]


def test_a_fork_copies_the_whole_thread_by_default(client):
    original = _chat(client, "Planning", [("one?", "1"), ("two?", "2")])
    fork = client.post(f"/conversations/{original}/fork", json={})
    assert fork.status_code == 201, fork.text
    assert _messages(client, fork.json()["id"]) == _messages(client, original)


def test_a_fork_can_stop_at_a_turn(client):
    original = _chat(client, "Planning", [("one?", "1"), ("two?", "2"), ("three?", "3")])
    fork = client.post(f"/conversations/{original}/fork", json={"up_to": 0}).json()
    kept = _messages(client, fork["id"])
    assert [m["content"] for m in kept] == ["one?", "1"]


def test_the_original_is_untouched(client):
    """A copy, not a move. The whole point is keeping the thread you have."""
    original = _chat(client, "Planning", [("one?", "1"), ("two?", "2")])
    before = _messages(client, original)
    client.post(f"/conversations/{original}/fork", json={"up_to": 0})
    assert _messages(client, original) == before


def test_editing_the_fork_cannot_reach_its_parent(client):
    """A copy rather than a branch pointer, see the route's own docstring for
    why a tree with shared ancestry is the wrong size of machinery here."""
    original = _chat(client, "Planning", [("one?", "1"), ("two?", "2")])
    fork = client.post(f"/conversations/{original}/fork", json={}).json()
    client.delete(f"/conversations/{fork['id']}/turns/0")
    assert len(_messages(client, original)) == 4


def test_the_fork_says_where_it_came_from(client):
    """Two identically-named chats in the Library is what makes forking
    unusable: you cannot tell which one you are about to open."""
    original = _chat(client, "Planning", [("one?", "1")])
    fork = client.post(f"/conversations/{original}/fork", json={}).json()
    assert fork["title"] == "Planning (fork)"


def test_a_given_title_wins(client):
    original = _chat(client, "Planning", [("one?", "1")])
    fork = client.post(f"/conversations/{original}/fork", json={"title": "Other direction"}).json()
    assert fork["title"] == "Other direction"


def test_forking_before_the_first_turn_gives_an_empty_chat(client):
    """Not an error: a fork with nothing in it is a new chat, which is a
    reasonable thing to have asked for."""
    original = _chat(client, "Planning", [("one?", "1")])
    fork = client.post(f"/conversations/{original}/fork", json={"up_to": -1}).json()
    assert _messages(client, fork["id"]) == []


def test_a_missing_conversation_is_a_404(client):
    assert client.post("/conversations/9999/fork", json={}).status_code == 404


def test_the_fork_is_listed_like_any_other_chat(client):
    original = _chat(client, "Planning", [("one?", "1")])
    fork = client.post(f"/conversations/{original}/fork", json={}).json()
    listed = {row["id"] for row in client.get("/conversations").json()}
    assert fork["id"] in listed and original in listed
    assert json.loads("[]") == []
