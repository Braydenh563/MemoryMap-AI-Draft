"""The Connections block: REDESIGN.md §R7.3 item 1, ROADMAP.md item 5.

> *"I really like kortex's use of backlinking and elements for structured
> documents as well."*

Every join tested here already existed in the database before this endpoint:
`EntryLink` in both directions, `DocumentLink`, `WhiteboardNode`, and
`/media/<name>` references inside the body. What did not exist was any one
place that answered "what is this note joined to", links were chips on the
card, documents were a separate list, and boards were surfaced nowhere at
all, so a note could sit on three boards and show none of them.

Two properties carry the section's intent and are what these tests are
really for:

* **Direction is kept, not merged.** `links_for_entry` has always returned
  both directions in one list, so "this note points at that one" and "that
  one points at this" were indistinguishable. A Connections block that
  cannot state which way round a link goes is not a Connections block.
* **A private note contributes the fact of the connection, never its text.**
  Same rule the Library's file-usage chips follow.
"""

from __future__ import annotations

import io

import pytest

from memorymap.core import vault


def test_direction_is_not_merged(client):
    a = client.post("/entries", json={"content": "Sourdough starter"}).json()
    b = client.post("/entries", json={"content": "Oven temperatures"}).json()
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})

    out = client.get(f"/entries/{a['id']}/connections").json()
    assert [row["id"] for row in out["outgoing"]] == [b["id"]]
    assert out["incoming"] == []

    back = client.get(f"/entries/{b['id']}/connections").json()
    assert back["outgoing"] == []
    assert [row["id"] for row in back["incoming"]] == [a["id"]]


def test_a_deleted_note_stops_being_a_connection(client):
    a = client.post("/entries", json={"content": "Kept"}).json()
    b = client.post("/entries", json={"content": "Binned"}).json()
    client.post(f"/entries/{a['id']}/links", json={"target_id": b["id"]})
    client.delete(f"/entries/{b['id']}")

    out = client.get(f"/entries/{a['id']}/connections").json()
    assert out["outgoing"] == []
    assert out["total"] == 0


def test_documents_and_boards_are_connections_too(client):
    entry = client.post("/entries", json={"content": "Trip idea"}).json()
    doc = client.post("/documents", json={"title": "Trip plan", "content": "# Trip"}).json()
    client.post(f"/documents/{doc['id']}/notes", json={"entry_id": entry["id"]})
    board = client.post("/whiteboard/boards", json={"name": "Route map"}).json()
    client.post(
        "/whiteboard/nodes",
        json={"board_id": board["id"], "entry_id": entry["id"], "x": 10.0, "y": 20.0},
    )

    out = client.get(f"/entries/{entry['id']}/connections").json()
    assert [d["title"] for d in out["documents"]] == ["Trip plan"]
    assert [b["title"] for b in out["boards"]] == ["Route map"]
    assert out["total"] == 2


def test_the_unnamed_scratch_board_is_a_real_board(client):
    """`board_id IS NULL` is the board every notebook starts with, not a
    missing one: a card placed there must still show up as a connection."""
    entry = client.post("/entries", json={"content": "Loose thought"}).json()
    client.post("/whiteboard/nodes", json={"entry_id": entry["id"], "x": 0.0, "y": 0.0})

    out = client.get(f"/entries/{entry['id']}/connections").json()
    assert len(out["boards"]) == 1
    assert out["boards"][0]["id"] is None
    assert out["boards"][0]["title"] == "Whiteboard"


def test_one_board_is_listed_once_however_many_cards_it_holds(client):
    entry = client.post("/entries", json={"content": "Recurring idea"}).json()
    board = client.post("/whiteboard/boards", json={"name": "Big map"}).json()
    for x in (10.0, 200.0):
        client.post(
            "/whiteboard/nodes",
            json={"board_id": board["id"], "entry_id": entry["id"], "x": x, "y": 0.0},
        )

    out = client.get(f"/entries/{entry['id']}/connections").json()
    assert len(out["boards"]) == 1


def _upload(client, name="shot.png"):
    payload = {"file": (name, io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")}
    return client.post("/media/upload", files=payload).json()


def test_embedded_files_are_connections(client):
    media = _upload(client)
    stored = media["url"].rsplit("/", 1)[-1]
    entry = client.post("/entries", json={"content": f"See ![shot]({media['url']})"}).json()

    out = client.get(f"/entries/{entry['id']}/connections").json()
    assert [f["name"] for f in out["files"]] == [stored]
    assert out["files"][0]["original_name"] == "shot.png"


def test_a_document_lists_its_notes_bookmarks_and_files(client):
    media = _upload(client, "diagram.png")
    stored = media["url"].rsplit("/", 1)[-1]
    doc = client.post(
        "/documents", json={"title": "Design", "content": f"![d]({media['url']})"}
    ).json()
    entry = client.post("/entries", json={"content": "Design note"}).json()
    client.post(f"/documents/{doc['id']}/notes", json={"entry_id": entry["id"]})
    bookmark = client.post(
        "/bookmarks", json={"url": "https://example.com", "title": "Ref"}
    ).json()
    client.post(f"/documents/{doc['id']}/bookmarks", json={"bookmark_id": bookmark["id"]})

    out = client.get(f"/documents/{doc['id']}/connections").json()
    assert [n["id"] for n in out["notes"]] == [entry["id"]]
    assert [b["title"] for b in out["bookmarks"]] == ["Ref"]
    assert [f["name"] for f in out["files"]] == [stored]
    assert out["total"] == 3


@pytest.fixture
def open_vault(session):
    """A note can only be made private once a vault exists, `POST
    /entries/{id}/privacy` answers 409 otherwise. Opened by hand because
    these tests do not go through setup/unlock, and closed again so the
    state cannot leak into the next test."""
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    yield
    vault.close()


def test_a_private_note_is_a_connection_without_its_words(ai_client, open_vault):
    """The connection is not the secret; the text is. A Connections block
    that named a private note's first line would leak it onto the *other*
    note's card, where the vault's own rules do not apply."""
    public = ai_client.post("/entries", json={"content": "Weekly plan"}).json()
    secret = ai_client.post("/entries", json={"content": "SECRET diary line"}).json()
    ai_client.post(f"/entries/{public['id']}/links", json={"target_id": secret["id"]})
    marked = ai_client.post(f"/entries/{secret['id']}/privacy", json={"private": True})
    assert marked.status_code == 200, marked.text

    out = ai_client.get(f"/entries/{public['id']}/connections").json()
    assert len(out["outgoing"]) == 1
    assert out["outgoing"][0]["preview"] == "Private note"
    assert out["outgoing"][0]["is_private"] is True
    assert "SECRET" not in str(out)
