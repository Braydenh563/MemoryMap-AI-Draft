"""Archiving a document (BACKLOG §30b's named remaining scope, after notes
got this first): same shape as `test_archive.py`'s entry tests: kept,
never deleted, out of the way, reachable again from the Library's Shelved
filter."""

from __future__ import annotations


def _doc(client, title="Untitled"):
    return client.post("/documents", json={"title": title}).json()


def test_archiving_removes_a_document_from_the_normal_list(client):
    keep = _doc(client, "Keep me")
    shelve = _doc(client, "Archive me")

    body = client.put(f"/documents/{shelve['id']}/archive").json()
    assert body["archived_at"] is not None

    titles = {d["id"] for d in client.get("/documents").json()}
    assert keep["id"] in titles
    assert shelve["id"] not in titles


def test_archiving_a_document_is_not_deleting_it(client):
    doc = _doc(client, "Archive, don't delete")
    client.put(f"/documents/{doc['id']}/archive")

    body = client.get(f"/documents/{doc['id']}").json()
    assert body["archived_at"] is not None
    assert body["title"] == "Archive, don't delete"


def test_unarchiving_returns_a_document_to_the_normal_list(client):
    doc = _doc(client, "Temporarily shelved")
    client.put(f"/documents/{doc['id']}/archive")
    client.put(f"/documents/{doc['id']}/unarchive")

    ids = {d["id"] for d in client.get("/documents").json()}
    assert doc["id"] in ids


def test_archiving_twice_is_a_no_op_not_an_error(client):
    doc = _doc(client, "Archive me twice")
    first = client.put(f"/documents/{doc['id']}/archive").json()
    second = client.put(f"/documents/{doc['id']}/archive").json()
    assert first["archived_at"] == second["archived_at"]


def test_archiving_shows_up_in_the_librarys_shelved_filter(client):
    doc = _doc(client, "Shelve me for the library test")
    client.put(f"/documents/{doc['id']}/archive")

    shelved = [i for i in client.get("/library").json()["items"] if i["kind"] == "shelved"]
    match = next((i for i in shelved if i["subtype"] == "document" and i["id"] == doc["id"]), None)
    assert match is not None
    assert match["title"] == "Shelve me for the library test"
