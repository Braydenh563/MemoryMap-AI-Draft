"""Notes untouched for a long time with nothing else pointing at them
(ROADMAP.md item 31): the detection function, kept deliberately arithmetic
the same way `test_duplicates.py` covers the arithmetic dedupe finder.
"""

from __future__ import annotations

from datetime import timedelta

from memorymap.core.database import Entry, utcnow
from memorymap.entry import staleness


def _age(session, entry_id, days):
    entry = session.get(Entry, entry_id)
    entry.updated_at = utcnow() - timedelta(days=days)
    session.commit()


def test_a_fresh_note_is_not_stale(client, session):
    saved = client.post("/entries", json={"content": "just written"}).json()
    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert saved["id"] not in ids


def test_an_old_disconnected_note_is_flagged(client, session):
    saved = client.post("/entries", json={"content": "forgotten thought"}).json()
    _age(session, saved["id"], 120)

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert saved["id"] in ids


def test_an_old_note_is_not_stale_until_it_crosses_the_threshold(client, session):
    saved = client.post("/entries", json={"content": "a bit old"}).json()
    _age(session, saved["id"], 10)

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session, days=90)]
    assert saved["id"] not in ids


def test_a_linked_old_note_is_not_flagged(client, session):
    a = client.post("/entries", json={"content": "old note with a friend"}).json()
    b = client.post("/entries", json={"content": "the friend"}).json()
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})
    _age(session, a["id"], 120)
    _age(session, b["id"], 120)

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert a["id"] not in ids
    assert b["id"] not in ids


def test_a_reply_and_its_parent_are_not_flagged(client, session):
    parent = client.post("/entries", json={"content": "the original thought"}).json()
    reply = client.post(
        "/entries", json={"content": "a reply to it", "parent_id": parent["id"]}
    ).json()
    _age(session, parent["id"], 120)
    _age(session, reply["id"], 120)

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert parent["id"] not in ids
    assert reply["id"] not in ids


def test_a_pinned_old_note_is_not_flagged(client, session):
    saved = client.post("/entries", json={"content": "kept close on purpose"}).json()
    client.put(f"/entries/{saved['id']}", json={"pinned": True})
    _age(session, saved["id"], 120)

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert saved["id"] not in ids


def test_a_binned_note_is_not_flagged(client, session):
    saved = client.post("/entries", json={"content": "on its way out"}).json()
    _age(session, saved["id"], 120)
    client.delete(f"/entries/{saved['id']}")

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert saved["id"] not in ids


def test_an_archived_note_is_not_flagged(client, session):
    saved = client.post("/entries", json={"content": "put away deliberately"}).json()
    _age(session, saved["id"], 120)
    client.post(f"/entries/{saved['id']}/archive")

    ids = [e.id for e in staleness.find_stale_orphaned_notes(session)]
    assert saved["id"] not in ids
