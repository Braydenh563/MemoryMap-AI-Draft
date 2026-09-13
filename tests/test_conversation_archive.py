"""Archiving a saved chat (BACKLOG §30b's named remaining scope, after
notes got this first), same shape as `test_archive.py`'s entry tests:
kept, never deleted, out of the way, reachable again from the Library's
Shelved filter."""

from __future__ import annotations


def _chat(client, question="a question"):
    return client.post("/conversations", json={"question": question, "answer": "an answer"}).json()


def test_archiving_removes_a_chat_from_the_normal_list(client):
    keep = _chat(client, "keep me")
    shelve = _chat(client, "archive me")

    body = client.put(f"/conversations/{shelve['id']}/archive").json()
    assert body["archived_at"] is not None

    ids = {c["id"] for c in client.get("/conversations").json()}
    assert keep["id"] in ids
    assert shelve["id"] not in ids


def test_archiving_a_chat_is_not_deleting_it(client):
    chat = _chat(client)
    client.put(f"/conversations/{chat['id']}/archive")

    # Still fetchable directly: it never left the database.
    body = client.get(f"/conversations/{chat['id']}").json()
    assert body["archived_at"] is not None


def test_unarchiving_returns_a_chat_to_the_normal_list(client):
    chat = _chat(client)
    client.put(f"/conversations/{chat['id']}/archive")
    client.put(f"/conversations/{chat['id']}/unarchive")

    ids = {c["id"] for c in client.get("/conversations").json()}
    assert chat["id"] in ids


def test_archiving_twice_is_a_no_op_not_an_error(client):
    chat = _chat(client)
    first = client.put(f"/conversations/{chat['id']}/archive").json()
    second = client.put(f"/conversations/{chat['id']}/archive").json()
    assert first["archived_at"] == second["archived_at"]


def test_archiving_shows_up_in_the_librarys_shelved_filter(client):
    chat = _chat(client, "shelve me for the library test")
    client.put(f"/conversations/{chat['id']}/archive")

    shelved = [i for i in client.get("/library").json()["items"] if i["kind"] == "shelved"]
    match = next((i for i in shelved if i["subtype"] == "chat" and i["id"] == chat["id"]), None)
    assert match is not None
    assert match["title"]
