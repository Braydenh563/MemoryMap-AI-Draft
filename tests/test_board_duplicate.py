"""Duplicating a board: ROADMAP.md item 8, "managing concept maps".

Creating a map works, and so do listing and renaming. Duplicating did not
exist on either side, and it is the one that makes a map reusable: a map you
have laid out is a template for the next one, and without this the only way to
reuse a shape is to rebuild it card by card.

The property that matters most is independence. A card on a board **is a real
note** (this app's own premise), so a shallow copy that pointed both boards at
one set of notes would look identical the moment it was made and diverge into
data loss the first time anyone edited the copy.
"""

from __future__ import annotations


def _board_with_a_card(client, name="Study plan", text="root idea"):
    board = client.post("/whiteboard/boards", json={"name": name}).json()
    entry = client.post("/entries", json={"content": text}).json()
    client.post(
        "/whiteboard/nodes",
        json={"board_id": board["id"], "entry_id": entry["id"], "x": 40.0, "y": 90.0},
    )
    return board, entry


def test_a_duplicate_carries_the_cards_and_their_positions(client):
    board, _ = _board_with_a_card(client)

    copy = client.post(f"/whiteboard/boards/{board['id']}/duplicate")
    assert copy.status_code == 201, copy.text
    copy = copy.json()

    assert copy["id"] != board["id"]
    assert copy["title"] == "Study plan (copy)"
    assert copy["node_count"] == 1

    # State comes from `GET /whiteboard/`, not a `/nodes` collection: there
    # is no such endpoint, which the first draft of this test assumed.
    state = client.get(f"/whiteboard/?board_id={copy['id']}").json()
    assert len(state["nodes"]) == 1
    assert (state["nodes"][0]["x"], state["nodes"][0]["y"]) == (40.0, 90.0)


def test_editing_a_copied_card_does_not_change_the_original(client):
    """The whole reason this is a deep copy. A shared-note version passes the
    test above and loses the user's data the first time they edit the copy."""
    board, original_entry = _board_with_a_card(client, text="original wording")

    copy = client.post(f"/whiteboard/boards/{board['id']}/duplicate").json()
    copied_node = client.get(f"/whiteboard/?board_id={copy['id']}").json()["nodes"][0]
    assert copied_node["entry_id"] != original_entry["id"], "the copy must own its notes"

    client.put(
        f"/entries/{copied_node['entry_id']}", json={"content": "changed on the copy"}
    )

    still = client.get(f"/entries/{original_entry['id']}").json()
    assert still["content"] == "original wording"


def test_duplicating_an_empty_board_works(client):
    board = client.post("/whiteboard/boards", json={"name": "Blank"}).json()
    copy = client.post(f"/whiteboard/boards/{board['id']}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["node_count"] == 0


def test_duplicating_a_board_that_does_not_exist_is_a_404(client):
    assert client.post("/whiteboard/boards/999999/duplicate").status_code == 404


def test_the_copy_appears_in_the_board_list(client):
    board, _ = _board_with_a_card(client, name="Thesis map")
    client.post(f"/whiteboard/boards/{board['id']}/duplicate")

    titles = [b["title"] for b in client.get("/whiteboard/boards").json()]
    assert "Thesis map" in titles
    assert "Thesis map (copy)" in titles
