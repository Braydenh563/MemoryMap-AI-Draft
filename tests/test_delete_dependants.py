"""Deleting a thing must not be blocked by the things attached to it.

`PRAGMA foreign_keys=ON` is set (core/database.py), and none of the join
tables declare a cascade, so every parent's delete has to clear its children
by hand. Three of the four parents in this schema got that wrong, and each
failure looked the same from the outside: a 500, and the thing still there.

- a document with a note attached could not be deleted (`DocumentLink`,
  `DocumentBookmark`),
- a note with a saved link, a recognised person or a resurfacing score could
  not be purged (`EntryBookmark`, `EntityMention`, `NoteScore`),
- a bookmark attached to either could not be deleted (both join tables).

In all three the *integration* was what made the thing permanent, which is
why no single feature's own tests caught any of them: each table was added
by the feature that needed it, and the delete on the other side belonged to
somebody else.

`test_recycle_bin.py` holds the schema-driven check for `entries`. This file
is the behavioural half, one test per parent, each doing what a person does.
"""

from __future__ import annotations

from sqlalchemy import func, select

from memorymap.core.database import (
    DocumentBookmark,
    DocumentLink,
    EntryBookmark,
)


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_a_bookmark_attached_to_a_note_and_a_document_can_be_deleted(client, session):
    note = client.post("/entries", json={"content": "a note"}).json()
    document = client.post("/documents", json={"title": "Doc", "content": "body"}).json()
    bookmark = client.post(
        "/bookmarks", json={"title": "A link", "url": "https://example.invalid/x"}
    ).json()
    assert client.post(
        f"/entries/{note['id']}/bookmarks", json={"bookmark_id": bookmark["id"]}
    ).status_code == 201
    assert client.post(
        f"/documents/{document['id']}/bookmarks", json={"bookmark_id": bookmark["id"]}
    ).status_code == 201
    session.commit()
    assert _count(session, EntryBookmark) == 1
    assert _count(session, DocumentBookmark) == 1

    removed = client.delete(f"/bookmarks/{bookmark['id']}")
    assert removed.status_code == 200, removed.text
    session.expire_all()
    assert _count(session, EntryBookmark) == 0
    assert _count(session, DocumentBookmark) == 0
    # The join row goes; what it was attached to does not.
    assert client.get(f"/entries/{note['id']}").status_code == 200
    assert client.get(f"/documents/{document['id']}").status_code == 200


def test_a_document_a_note_is_attached_to_can_be_deleted(client, session):
    note = client.post("/entries", json={"content": "a note"}).json()
    document = client.post("/documents", json={"title": "Doc", "content": "body"}).json()
    assert client.post(
        f"/documents/{document['id']}/notes", json={"entry_id": note["id"]}
    ).status_code == 201
    session.commit()
    assert _count(session, DocumentLink) == 1

    removed = client.delete(f"/documents/{document['id']}")
    assert removed.status_code == 200, removed.text
    session.expire_all()
    assert _count(session, DocumentLink) == 0
    assert client.get(f"/entries/{note['id']}").status_code == 200
