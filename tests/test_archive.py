"""Archive: a third state between active and binned (BACKLOG §30b).

Archiving a note is not deleting it, nothing about it is bound for
auto-clear or purge, and there is no confirmation, because nothing is at
risk of being lost. It's excluded from ordinary listings the same way a
binned note is, for a different reason: kept, but out of the way.
"""

from __future__ import annotations

import json

from memorymap.core.database import Entry


def _note(session, content):
    entry = Entry(content=content, tags=json.dumps([]))
    session.add(entry)
    session.commit()
    return entry


def test_archiving_removes_a_note_from_the_normal_list(client, session):
    keep = _note(session, "a note I am still using")
    shelve = _note(session, "a note I archived")

    body = client.post(f"/entries/{shelve.id}/archive").json()
    assert body["archived_at"] is not None

    ids = {e["id"] for e in client.get("/entries").json()}
    assert keep.id in ids
    assert shelve.id not in ids


def test_archiving_is_not_deleting(client, session):
    """An archived note is not in the bin, and vice versa, the two
    states are independent, not aliases of each other."""
    entry = _note(session, "archive me, not delete me")
    client.post(f"/entries/{entry.id}/archive")

    assert entry.id not in {e["id"] for e in client.get("/entries?deleted=true").json()}

    body = client.get(f"/entries/{entry.id}").json()
    assert body["archived_at"] is not None
    assert body["deleted_at"] is None


def test_the_archive_view_lists_only_archived_notes(client, session):
    active = _note(session, "still active")
    shelved = _note(session, "shelved")
    client.post(f"/entries/{shelved.id}/archive")

    ids = {e["id"] for e in client.get("/entries?archived=true").json()}
    assert ids == {shelved.id}
    assert active.id not in ids


def test_unarchiving_returns_a_note_to_the_normal_list(client, session):
    entry = _note(session, "temporarily shelved")
    client.post(f"/entries/{entry.id}/archive")
    assert entry.id not in {e["id"] for e in client.get("/entries").json()}

    body = client.post(f"/entries/{entry.id}/unarchive").json()
    assert body["archived_at"] is None
    assert entry.id in {e["id"] for e in client.get("/entries").json()}


def test_archiving_twice_is_a_no_op_not_a_new_timestamp(client, session):
    entry = _note(session, "archive me twice")
    first = client.post(f"/entries/{entry.id}/archive").json()["archived_at"]
    second = client.post(f"/entries/{entry.id}/archive").json()["archived_at"]
    assert first == second


def test_archived_note_is_still_readable_directly_by_id(client, session):
    """Unlike a binned note (which 404s unless ?deleted=true), an archived
    note stays normally reachable, it's kept, not hidden."""
    entry = _note(session, "still findable by id")
    client.post(f"/entries/{entry.id}/archive")
    response = client.get(f"/entries/{entry.id}")
    assert response.status_code == 200


def test_archived_notes_are_excluded_from_most_accessed(client, session):
    entry = _note(session, "was popular, now shelved")
    entry.access_count = 10
    session.commit()
    client.post(f"/entries/{entry.id}/archive")

    ids = {e["id"] for e in client.get("/entries/most-accessed").json()}
    assert entry.id not in ids
