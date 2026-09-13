"""The recycle bin: emptying it, and getting rid of one note for good.

**"Empty now" has been reported broken three times** and driven end to end in a
real browser twice: dialog, POST, empty bin, toast, server reporting zero
binned notes. So these tests pin the server half, and the frontend's half of
the fix is that a failure is now *visible*: every path through that handler
used to swallow its error, which is indistinguishable from a button that does
nothing.

The per-note purge is new, and it is the one route in the app that destroys
something with no undo, hence the rule it enforces: a note has to be in the
bin already, so permanent loss is always the second deliberate step.
"""

from __future__ import annotations

import json
from datetime import timedelta

from memorymap.core import deps
from memorymap.core.database import (
    Attachment,
    Document,
    DocumentLink,
    EmbeddingRecord,
    Entry,
    EntryDate,
    EntryLink,
    EntryRevision,
    Reminder,
    WhiteboardNode,
    WhiteboardObject,
    WhiteboardSketch,
    utcnow,
)


def _note(session, content, tags=None, parent_id=None):
    entry = Entry(content=content, tags=json.dumps(tags or []), parent_id=parent_id)
    session.add(entry)
    session.commit()
    return entry


def test_emptying_the_bin_removes_only_binned_notes(client, session):
    keep = _note(session, "a note I am still using")
    bin_me = _note(session, "a note I binned")
    client.delete(f"/entries/{bin_me.id}")

    body = client.post("/recycle-bin/empty").json()
    assert body["removed"] == 1
    assert client.get("/entries?deleted=true").json() == []
    assert [n["id"] for n in client.get("/entries").json()] == [keep.id]


def test_emptying_an_empty_bin_is_not_an_error(client, session):
    """It reports zero rather than failing. A button that errors when there is
    nothing to do reads as broken, which is the report this whole area is
    fighting."""
    body = client.post("/recycle-bin/empty").json()
    assert body["removed"] == 0


def test_one_note_can_be_deleted_for_good(client, session):
    keep = _note(session, "still in the bin, and staying there")
    goner = _note(session, "this one goes for good")
    client.delete(f"/entries/{keep.id}")
    client.delete(f"/entries/{goner.id}")

    response = client.delete(f"/entries/{goner.id}/purge")
    assert response.status_code == 200
    assert response.json()["purged"] == 1

    remaining = client.get("/entries?deleted=true").json()
    assert [n["id"] for n in remaining] == [keep.id]
    # The route committed through its own session, so this one still holds the
    # row in its identity map. Expunged rather than expired: expiring a row
    # that has since been deleted raises on the next access instead of
    # returning None, which reads as a failure when it is bookkeeping.
    session.expunge_all()
    assert session.get(Entry, goner.id) is None


def test_a_note_still_in_the_notebook_cannot_be_purged(client, session):
    """The soft-delete step is not optional. Without this, one mis-routed
    request destroys a note that was never binned, and there is no undo to
    reach for, which is exactly why the rule lives on the server."""
    live = _note(session, "a note I am still using")

    response = client.delete(f"/entries/{live.id}/purge")
    assert response.status_code == 400
    assert "recycle bin" in response.json()["detail"]
    assert session.get(Entry, live.id) is not None


def test_purging_one_note_takes_its_vectors_links_and_files_with_it(client, session, tmp_path):
    """The whole point of sharing `_hard_delete` between the two paths. A purge
    that left an embedding behind would leave a note that is gone from every
    list and still turns up in semantic search."""
    from memorymap.core import deps

    other = _note(session, "the note on the other end of the link")
    goner = _note(session, "the note being purged")
    session.add(EntryLink(source_entry_id=goner.id, target_entry_id=other.id))
    session.add(
        EmbeddingRecord(
            entry_id=goner.id, embedding=b"\x00" * 8, dim=2, model_version="test"
        )
    )
    uploads = deps.get_config().uploads_dir
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "purge-me.png").write_bytes(b"png")
    session.add(
        Attachment(
            entry_id=goner.id,
            filename="purge-me.png",
            stored_name="purge-me.png",
            mime="image/png",
            size=3,
        )
    )
    session.commit()
    client.delete(f"/entries/{goner.id}")

    client.delete(f"/entries/{goner.id}/purge")

    session.expunge_all()
    assert session.get(Entry, goner.id) is None
    assert session.query(EmbeddingRecord).filter_by(entry_id=goner.id).count() == 0
    assert session.query(EntryLink).count() == 0
    assert not (uploads / "purge-me.png").exists()
    # The note at the other end is untouched, a link is a connection, not a
    # dependency.
    assert session.get(Entry, other.id) is not None


def test_purging_a_parent_leaves_its_replies_as_roots(client, session):
    """A reply whose parent is destroyed becomes a thread root rather than a
    note pointing at an id that no longer exists."""
    parent = _note(session, "the note that started a thread")
    reply = _note(session, "a reply to it", parent_id=parent.id)
    client.delete(f"/entries/{parent.id}")

    client.delete(f"/entries/{parent.id}/purge")

    session.expunge_all()
    assert session.get(Entry, reply.id).parent_id is None


def test_a_note_with_every_kind_of_attached_row_can_still_be_destroyed(client, session):
    """Reported twice in one sitting: "request failed (500) when I tried to
    empty the bin", and two particular notes that would not delete at all.

    One cause. `PRAGMA foreign_keys=ON` is set, and `_hard_delete` cleaned
    three of the seven tables that point at an entry, so a row left in any of
    the other four made `DELETE FROM entries` raise IntegrityError, which the
    API returned as a 500 and the bin was left exactly as it had been. The two
    notes in the report both carried a resolved time phrase (the `ph:clock this week
    → week of 27 July` chip is an `entry_dates` row), which is why those two
    and not the rest.

    This builds a note with **one row in every table that references an
    entry** and destroys it. Anything that gains a `ForeignKey("entries.id")`
    later has to be handled in `_hard_delete`, and this fails until it is.
    """
    goner = _note(session, "a note with everything hanging off it")
    other = _note(session, "another note")
    document = Document(title="Compiled notes", content="x")
    session.add(document)
    session.flush()
    session.add_all(
        [
            EntryDate(entry_id=goner.id, phrase="this week", at=utcnow(), precision="week"),
            EntryRevision(entry_id=goner.id, content="an earlier draft", tags="[]"),
            DocumentLink(document_id=document.id, entry_id=goner.id),
            Reminder(entry_id=goner.id, text="water the tomatoes", due_at=utcnow()),
            EntryLink(source_entry_id=goner.id, target_entry_id=other.id),
            EmbeddingRecord(entry_id=goner.id, embedding=b"\x00" * 4, dim=1, model_version="test"),
            Attachment(
                entry_id=goner.id,
                filename="x.png",
                stored_name="stored-x.png",
                mime="image/png",
                size=1,
            ),
            # Whiteboard: two different relationships to the same entry.
            # `entry_id` is the card's own note: added to the schema after
            # this test was first written, and not handled until it was.
            WhiteboardNode(entry_id=goner.id),
            # `board_id` names which board a card/sketch lives *on*, a
            # different note, so it belongs on `other`, not `goner`.
            WhiteboardNode(entry_id=other.id, board_id=goner.id),
            WhiteboardSketch(data="M0 0 L1 1", board_id=goner.id),
            # Images and text boxes: no entry_id relationship at all (neither
            # wraps a note), only board_id, same detach-not-delete rule.
            WhiteboardObject(kind="text", data='{"content": "hi"}', board_id=goner.id),
        ]
    )
    session.commit()
    client.delete(f"/entries/{goner.id}")

    response = client.delete(f"/entries/{goner.id}/purge")

    assert response.status_code == 200, response.text
    session.expunge_all()
    assert session.get(Entry, goner.id) is None
    assert session.query(EntryDate).filter_by(entry_id=goner.id).count() == 0
    assert session.query(EntryRevision).filter_by(entry_id=goner.id).count() == 0
    assert session.query(DocumentLink).filter_by(entry_id=goner.id).count() == 0
    # The card whose own note was purged is gone with it...
    assert session.query(WhiteboardNode).filter_by(entry_id=goner.id).count() == 0
    # ...but the card that merely lived *on* the purged board survives,
    # detached to the default board rather than deleted.
    survivor = session.query(WhiteboardNode).filter_by(entry_id=other.id).one()
    assert survivor.board_id is None
    assert session.query(WhiteboardSketch).filter_by(board_id=goner.id).count() == 0
    assert session.query(WhiteboardObject).filter_by(board_id=goner.id).count() == 0
    assert session.query(WhiteboardObject).filter_by(kind="text").one().board_id is None


def test_a_reminder_outlives_the_note_it_came_from(client, session):
    """Detached, not deleted. "Water the tomatoes" is still something the user
    asked to be reminded of after the note that prompted it has gone, and
    deleting it would throw away something they set by hand, which is a
    different act from emptying a bin, and not one they asked for."""
    goner = _note(session, "the note that prompted a reminder")
    session.add(Reminder(entry_id=goner.id, text="water the tomatoes", due_at=utcnow()))
    session.commit()
    client.delete(f"/entries/{goner.id}")

    client.delete(f"/entries/{goner.id}/purge")

    session.expunge_all()
    surviving = session.query(Reminder).all()
    assert [(r.text, r.entry_id) for r in surviving] == [("water the tomatoes", None)]


def test_emptying_the_bin_survives_a_note_with_a_resolved_date(client, session):
    """The reported route, not just the per-note one: "Empty now" walks the
    same `_hard_delete`, so it returned 500 and emptied nothing."""
    for text in ["classes this week", "a plain note"]:
        note = _note(session, text)
        session.add(
            EntryDate(entry_id=note.id, phrase="this week", at=utcnow(), precision="week")
        )
        session.commit()
        client.delete(f"/entries/{note.id}")

    response = client.post("/recycle-bin/empty")

    assert response.status_code == 200, response.text
    session.expunge_all()
    assert session.query(Entry).filter_by(is_deleted=True).count() == 0


# --- reading a binned note in full (§36G) -------------------------------------
#
# The bin panel listed every deleted note with its whole text, so "read it
# before deciding whether to restore it" came free. Deleting that panel means
# the Library's reader is the only way left, and it needs one note at a time.


def test_a_binned_note_can_be_read_when_the_caller_asks_for_it(client, session):
    entry = _note(session, "The note I am deciding about.")
    client.delete(f"/entries/{entry.id}")
    body = client.get(f"/entries/{entry.id}?deleted=true").json()
    assert body["content"] == "The note I am deciding about."


def test_a_binned_note_is_still_absent_from_an_ordinary_read(client, session):
    """The default has to stay a 404. A stale link to a note somebody deleted
    should not quietly resurrect it, reaching into the bin is something the
    caller says it means to do."""
    entry = _note(session, "Deleted, and staying deleted.")
    client.delete(f"/entries/{entry.id}")
    assert client.get(f"/entries/{entry.id}").status_code == 404


def test_reading_a_binned_note_does_not_count_as_using_it(client, session):
    """`access_count` feeds "most accessed". A note climbing that list because
    you looked at it on the way to deleting it for good is the counter lying
    about what you use."""
    entry = _note(session, "On its way out.")
    client.delete(f"/entries/{entry.id}")
    before = session.get(Entry, entry.id).access_count
    client.get(f"/entries/{entry.id}?deleted=true")
    session.expire_all()
    assert session.get(Entry, entry.id).access_count == before


def test_reading_a_live_note_still_counts_as_using_it(client, session):
    """The other half of the rule above, the counter must keep working for
    every note that is not in the bin."""
    entry = _note(session, "Very much in use.")
    before = session.get(Entry, entry.id).access_count
    client.get(f"/entries/{entry.id}?deleted=true")
    session.expire_all()
    assert session.get(Entry, entry.id).access_count == before + 1


# --- delete/restore/empty via the HTTP API (vs. the ORM-level tests above) ----


def test_delete_restore_and_bin_view(client):
    saved = client.post("/entries", json={"content": "bin me"}).json()
    # Outside the assert on purpose: `python -O` drops assert statements, and
    # with the delete inside one the test would pass without ever deleting.
    deleted = client.delete(f"/entries/{saved['id']}")
    assert deleted.status_code == 200

    assert client.get("/entries").json() == []
    binned = client.get("/entries", params={"deleted": True}).json()
    assert [e["id"] for e in binned] == [saved["id"]]
    assert binned[0]["deleted_at"] is not None

    client.post(f"/entries/{saved['id']}/restore")
    assert [e["id"] for e in client.get("/entries").json()] == [saved["id"]]
    assert client.get("/entries", params={"deleted": True}).json() == []


def test_empty_bin_now(client):
    saved = client.post("/entries", json={"content": "gone forever"}).json()
    client.delete(f"/entries/{saved['id']}")
    assert client.post("/recycle-bin/empty").json() == {"removed": 1}
    assert client.get("/entries", params={"deleted": True}).json() == []
    assert client.get(f"/entries/{saved['id']}").status_code == 404


def test_expired_bin_entries_purged(client):
    from memorymap.entry import manager

    saved = client.post("/entries", json={"content": "ancient history"}).json()
    client.delete(f"/entries/{saved['id']}")

    # Pretend it was deleted 40 days ago, then run the startup purge.
    session = deps.get_db().session()
    try:
        session.get(Entry, saved["id"]).deleted_at = utcnow() - timedelta(days=40)
        session.commit()
        assert manager.purge_expired_deleted(session, days=30) == 1
    finally:
        session.close()


def test_every_table_pointing_at_an_entry_is_handled_when_one_is_destroyed():
    """The list in `_hard_delete` is checked against the schema, not memory.

    `test_a_note_with_every_kind_of_attached_row_can_still_be_destroyed`
    above promises exactly this and cannot deliver it: it builds one row per
    table **by hand**, so a table added afterwards is simply not in it and
    the test keeps passing. That is not a hypothetical. It was written when
    seven tables pointed at an entry; by 2026-09-12 there were ten, and
    `EntryBookmark`, `EntityMention` and `NoteScore` were all unhandled. A
    note with a saved link on it could not be purged: `FOREIGN KEY
    constraint failed`, a 500, and the note still sitting in the bin.

    So this one reads the foreign keys out of the metadata and asserts each
    is accounted for in `_hard_delete`'s source. A new table referencing
    `entries.id` fails this the moment it is declared, which is the promise
    the docstring above was making.
    """
    import inspect

    from memorymap.core.database import Base
    from memorymap.entry import manager

    # Comments stripped first, and that is not fussiness: the first version
    # of this test searched the raw source, and the paragraph in
    # `_hard_delete` *explaining* which tables it handles was enough to
    # satisfy it. Deleting the real `NoteScore` line left the test passing.
    # A check that a name is mentioned is not a check that it is handled.
    source = "\n".join(
        line.split("#", 1)[0]
        for line in inspect.getsource(manager._hard_delete).splitlines()
    )
    unhandled = []
    for table in Base.metadata.tables.values():
        if table.name == "entries":
            continue
        for column in table.columns:
            for key in column.foreign_keys:
                if key.column.table.name != "entries":
                    continue
                # Handled means named in the function at all: some are
                # deleted, some detached (a reminder outlives its note, a
                # board's cards are not the board's to take), and which is
                # right is a decision per table, recorded there.
                if table.name not in source and _model_name(table) not in source:
                    unhandled.append(f"{table.name}.{column.name}")
    assert not unhandled, (
        "these reference entries.id and `_hard_delete` does not mention them, so "
        f"purging a note that has one raises FOREIGN KEY constraint failed: {sorted(set(unhandled))}"
    )


def _model_name(table) -> str:  # noqa: ANN001
    from memorymap.core.database import Base

    for mapper in Base.registry.mappers:
        if mapper.local_table is table:
            return mapper.class_.__name__
    return table.name
