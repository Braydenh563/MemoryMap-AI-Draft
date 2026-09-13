"""Attaching a saved bookmark to a document, the same References concept
notes already got this session (§30: "should bookmarks show in documents
... as well?")."""

from __future__ import annotations


def _make_document(client):
    return client.post("/documents", json={"title": "A doc", "content": "hello"}).json()


def test_attach_and_list_bookmark_on_document(client):
    document = _make_document(client)
    bookmark = client.post("/bookmarks", json={"url": "a.com", "title": "A"}).json()

    response = client.post(
        f"/documents/{document['id']}/bookmarks", json={"bookmark_id": bookmark["id"]}
    )
    assert response.status_code == 201

    listed = client.get(f"/documents/{document['id']}/bookmarks").json()
    assert len(listed) == 1
    assert listed[0]["id"] == bookmark["id"]
    assert listed[0]["url"] == "https://a.com"


def test_attaching_twice_is_idempotent(client):
    document = _make_document(client)
    bookmark = client.post("/bookmarks", json={"url": "a.com"}).json()
    client.post(f"/documents/{document['id']}/bookmarks", json={"bookmark_id": bookmark["id"]})
    client.post(f"/documents/{document['id']}/bookmarks", json={"bookmark_id": bookmark["id"]})
    assert len(client.get(f"/documents/{document['id']}/bookmarks").json()) == 1


def test_detach_bookmark(client):
    document = _make_document(client)
    bookmark = client.post("/bookmarks", json={"url": "a.com"}).json()
    client.post(f"/documents/{document['id']}/bookmarks", json={"bookmark_id": bookmark["id"]})

    response = client.delete(f"/documents/{document['id']}/bookmarks/{bookmark['id']}")
    assert response.json() == {"detached": True}
    attached = client.get(f"/documents/{document['id']}/bookmarks")
    assert attached.json() == []


def test_attach_to_missing_document_is_404(client):
    bookmark = client.post("/bookmarks", json={"url": "a.com"}).json()
    response = client.post("/documents/999999/bookmarks", json={"bookmark_id": bookmark["id"]})
    assert response.status_code == 404


def test_attach_missing_bookmark_is_404(client):
    document = _make_document(client)
    response = client.post(f"/documents/{document['id']}/bookmarks", json={"bookmark_id": 999999})
    assert response.status_code == 404


def test_a_document_with_no_bookmarks_returns_empty_list(client):
    document = _make_document(client)
    attached = client.get(f"/documents/{document['id']}/bookmarks")
    assert attached.json() == []


def test_a_notes_bookmarks_and_a_documents_bookmarks_are_independent(client):
    entry = client.post("/entries", json={"content": "a note", "tags": []}).json()
    document = _make_document(client)
    bookmark = client.post("/bookmarks", json={"url": "a.com"}).json()
    client.post(f"/entries/{entry['id']}/bookmarks", json={"bookmark_id": bookmark["id"]})
    attached = client.get(f"/documents/{document['id']}/bookmarks")
    assert attached.json() == []
