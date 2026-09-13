"""Note edit history: the undo that the recycle bin never covered.

The bin catches deletion. Rewriting a note destroyed what it used to say with
no way back, and the AI can rewrite notes too, which makes this more than a
nicety.

These cover the `revisions` half of `GET /entries/{id}/history`: the capped
per-edit snapshots (`EntryRevision`) and the route that puts one back. The
`items` half, the event log Brief 7 added beside them, is specified in
`tests/test_events.py`; `test_the_events_view_is_there_too` below is only the
seam between the two.
"""

from __future__ import annotations

from memorymap.entry import manager


def _make(client, content, tags=None):
    return client.post("/entries", json={"content": content, "tags": tags or []}).json()


def test_editing_records_the_previous_version(client):
    entry = _make(client, "the original wording")
    client.put(f"/entries/{entry['id']}", json={"content": "the new wording"})

    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert [h["content"] for h in history] == ["the original wording"]


def test_history_is_newest_first(client):
    entry = _make(client, "version one")
    client.put(f"/entries/{entry['id']}", json={"content": "version two"})
    client.put(f"/entries/{entry['id']}", json={"content": "version three"})

    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert [h["content"] for h in history] == ["version two", "version one"]


def test_a_new_note_has_no_history(client):
    entry = _make(client, "brand new")
    assert client.get(f"/entries/{entry['id']}/history").json()["revisions"] == []


def test_an_edit_that_changes_nothing_records_nothing(client):
    entry = _make(client, "unchanged")
    client.put(f"/entries/{entry['id']}", json={"content": "unchanged"})
    assert client.get(f"/entries/{entry['id']}/history").json()["revisions"] == []


def test_changing_only_tags_is_still_recorded(client):
    entry = _make(client, "same text", ["one"])
    client.put(f"/entries/{entry['id']}", json={"tags": ["one", "two"]})

    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert len(history) == 1
    assert history[0]["tags"] == ["one"]


def test_restoring_puts_the_old_text_back(client):
    entry = _make(client, "the good version")
    client.put(f"/entries/{entry['id']}", json={"content": "a regrettable rewrite"})
    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]

    restored = client.post(
        f"/entries/{entry['id']}/history/{history[0]['id']}/restore"
    ).json()
    assert restored["content"] == "the good version"


def test_restoring_is_itself_undoable(client):
    """Undoing an undo has to work, or this is a trap rather than a safety net."""
    entry = _make(client, "first")
    client.put(f"/entries/{entry['id']}", json={"content": "second"})
    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    client.post(f"/entries/{entry['id']}/history/{history[0]['id']}/restore")

    after = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert "second" in [h["content"] for h in after]


def test_history_is_capped(client):
    """A note edited hundreds of times must not become the biggest thing here."""
    entry = _make(client, "v0")
    for i in range(1, manager.MAX_REVISIONS + 6):
        client.put(f"/entries/{entry['id']}", json={"content": f"v{i}"})

    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert len(history) == manager.MAX_REVISIONS
    assert history[0]["content"] == f"v{manager.MAX_REVISIONS + 4}"  # newest kept


def test_restoring_a_version_from_another_note_is_refused(client):
    mine = _make(client, "mine")
    theirs = _make(client, "theirs")
    client.put(f"/entries/{theirs['id']}", json={"content": "theirs edited"})
    other_revision = client.get(f"/entries/{theirs['id']}/history").json()["revisions"][0]

    response = client.post(
        f"/entries/{mine['id']}/history/{other_revision['id']}/restore"
    )
    assert response.status_code == 404


def test_a_private_notes_history_is_encrypted_at_rest(client, session):
    """A revision must never be the one place a private note sits in the clear."""
    from sqlalchemy import select

    from memorymap.core import crypto, vault
    from memorymap.core.database import EntryRevision

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()

    entry = _make(client, "the first secret")
    client.post(f"/entries/{entry['id']}/privacy", json={"private": True})
    client.put(f"/entries/{entry['id']}", json={"content": "the second secret"})

    stored = session.scalars(select(EntryRevision)).all()
    assert stored, "the edit should have been recorded"
    assert all(crypto.is_encrypted(r.content) for r in stored)
    assert not any("first secret" in r.content for r in stored)

    # And it reads back correctly while unlocked.
    history = client.get(f"/entries/{entry['id']}/history").json()["revisions"]
    assert history[0]["content"] == "the first secret"
    vault.close()


def test_the_events_view_is_there_too(client):
    """The seam: the same route carries the event log beside the snapshots.

    What each event means, and that every write records exactly one, is
    `tests/test_events.py`. This only proves the two halves arrive together
    and that the events half says who did it.
    """
    entry = _make(client, "written once")
    client.put(f"/entries/{entry['id']}", json={"content": "written twice"})

    body = client.get(f"/entries/{entry['id']}/history").json()
    assert [item["action"] for item in body["items"]][-1] == "created"
    assert body["items"][-1]["content"] == "written once"
    assert {item["actor"] for item in body["items"]} == {"user"}
    assert body["next_cursor"] is None
    assert [revision["content"] for revision in body["revisions"]] == ["written once"]


def test_a_long_history_pages_and_says_so(client):
    """A note edited past one page hands back a cursor, and the next page
    continues from it without repeating or skipping an event.

    The sheet in `frontend/app.js` reads both: before this was wired up it
    took the first page and dropped the cursor, so a note with more changes
    than one page showed its newest fifty and looked complete.
    """
    from memorymap.api.routes_entries import HISTORY_PAGE

    entry = _make(client, "edit 0")
    for i in range(1, HISTORY_PAGE + 10):
        client.put(f"/entries/{entry['id']}", json={"content": f"edit {i}"})

    first = client.get(f"/entries/{entry['id']}/history").json()
    assert len(first["items"]) == HISTORY_PAGE
    assert first["next_cursor"] == first["items"][-1]["id"]

    second = client.get(
        f"/entries/{entry['id']}/history?before={first['next_cursor']}"
    ).json()
    assert second["items"], "the cursor pointed at nothing"
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)), "a page repeated an event"
    assert ids == sorted(ids, reverse=True), "the pages are not one newest-first list"
    # The oldest page ends at the note being created, and there is nothing
    # older than that to ask for.
    assert second["items"][-1]["action"] == "created"
    assert second["next_cursor"] is None


def test_every_row_of_a_long_history_shows_its_own_version(client):
    """Page two says what the note said then, the same as page one.

    The per-row text is a fold of every event up to that row, and it is
    folded once per page rather than once per row (`events.states_at`). A
    fold that stopped in the wrong place, or kept the wrong row's copy,
    would show a row somebody else's text, which looks like the history
    being wrong about what was written rather than like a bug in a loop.
    """
    from memorymap.api.routes_entries import HISTORY_PAGE

    edits = HISTORY_PAGE + 9
    entry = _make(client, "edit 0")
    for i in range(1, edits + 1):
        client.put(f"/entries/{entry['id']}", json={"content": f"edit {i}"})

    items = []
    cursor = None
    while True:
        url = f"/entries/{entry['id']}/history"
        page = client.get(f"{url}?before={cursor}" if cursor else url).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert [item["content"] for item in items] == [
        f"edit {i}" for i in range(edits, -1, -1)
    ]
