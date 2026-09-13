"""The whiteboard's API: cards, sketches, and which board they belong to.

Written during the §40 audit, because the whiteboard shipped with no tests at
all and four of the five things asserted here were broken. Each test names the
failure it caught rather than the method it calls, a test called
`test_create_node` tells the next session nothing about why it exists.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memorymap.core import deps
from memorymap.core.database import Entry


@pytest.fixture()
def board_client(app_state):
    from memorymap.api.app import create_app
    from tests.fakes import FakeEmbeddingService, FakeOllama

    deps.override_ai(
        ollama=FakeOllama(running=False),
        embeddings=FakeEmbeddingService(available=False),
    )
    return TestClient(create_app())


def _note(session, content="a note"):
    entry = Entry(content=content)
    session.add(entry)
    session.commit()
    return entry


def test_the_default_board_hands_back_what_was_put_on_it(board_client, session):
    """`board_id IS NULL` is a board, not an absence.

    The query filtered with `board_id == None`, which SQL renders as
    `= NULL`, never true for any row. So the unnamed scratch board, which is
    the one every notebook starts on, always came back empty however many
    cards you had dropped onto it, and they reappeared only if you happened to
    create a named board.
    """
    entry = _note(session)
    created = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "x": 10, "y": 20}
    )
    assert created.status_code == 200, created.text

    state = board_client.get("/whiteboard/").json()
    assert [n["entry_id"] for n in state["nodes"]] == [entry.id]
    assert (state["nodes"][0]["x"], state["nodes"][0]["y"]) == (10, 20)


def test_a_card_cannot_point_at_a_note_that_does_not_exist(board_client):
    """An unvalidated `entry_id` is a board that can never render again.

    Nothing checked the id, so a card for note 9999 was accepted, stored, and
    then failed to draw, with no way to select or delete it from the UI,
    because the thing you would click is the card that isn't there.
    """
    refused = board_client.post("/whiteboard/nodes", json={"entry_id": 9999})
    assert refused.status_code == 404
    assert board_client.get("/whiteboard/").json()["nodes"] == []


def test_dropping_the_same_note_twice_moves_its_card(board_client, session):
    """Two cards for one note stack exactly, and read as one that won't drag."""
    entry = _note(session)
    first = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "x": 1, "y": 1}
    ).json()
    second = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "x": 50, "y": 60}
    ).json()

    assert second["id"] == first["id"]
    nodes = board_client.get("/whiteboard/").json()["nodes"]
    assert len(nodes) == 1
    assert (nodes[0]["x"], nodes[0]["y"]) == (50, 60)


def test_the_same_note_can_be_referenced_from_two_boards_at_once(board_client, session):
    """§88.2 item 1 ("boards hold references, never copies") checked
    directly rather than assumed missing: `WhiteboardNode.entry_id` is
    already a pure foreign key, and `create_node`'s own dedup is scoped to
    `(entry_id, board_id)`, not `entry_id` alone, so the same note on two
    different boards is two independent rows, not a duplicate-detection
    false positive. Distinct from `test_a_card_can_be_moved_to_another_board`
    above: that one *moves* a card between boards (one reference at a time);
    this one confirms both references can exist *simultaneously*."""
    entry, board_a, board_b = _note(session), _note(session, "board A"), _note(session, "board B")

    node_a = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "board_id": board_a.id}
    ).json()
    node_b = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "board_id": board_b.id}
    ).json()
    assert node_a["id"] != node_b["id"]

    # Removing the reference from one board must not touch the other's, or
    # the underlying note.
    #
    # The delete call is on its own line, not inlined into the assert: an
    # assert's own expression is dropped entirely under Python's -O flag
    # (CodeQL: "an assert statement has a side-effect"), which would have
    # skipped the delete outright rather than just skipping the check.
    delete_response = board_client.delete(f"/whiteboard/nodes/{node_a['id']}")
    assert delete_response.status_code == 200
    assert board_client.get(f"/whiteboard/?board_id={board_a.id}").json()["nodes"] == []
    still_on_b = board_client.get(f"/whiteboard/?board_id={board_b.id}").json()["nodes"]
    assert [n["id"] for n in still_on_b] == [node_b["id"]]
    assert board_client.get(f"/entries/{entry.id}").status_code == 200


def test_a_card_can_be_moved_to_another_board(board_client, session):
    """`PUT` read `board_id` from the body and never assigned it, so "move
    this card to that board" returned 200 and changed nothing."""
    entry, board = _note(session), _note(session, "a board")
    node = board_client.post("/whiteboard/nodes", json={"entry_id": entry.id}).json()

    moved = board_client.put(
        f"/whiteboard/nodes/{node['id']}",
        json={"entry_id": entry.id, "board_id": board.id, "x": 5, "y": 5},
    )
    assert moved.status_code == 200
    assert moved.json()["board_id"] == board.id

    assert board_client.get("/whiteboard/").json()["nodes"] == []
    on_board = board_client.get(f"/whiteboard/?board_id={board.id}").json()
    assert [n["id"] for n in on_board["nodes"]] == [node["id"]]


def test_deleting_a_card_that_is_already_gone_says_so(board_client):
    """A cheerful `{"status": "ok"}` for a node that isn't there is how a
    stale board keeps its ghost cards until someone reloads the page."""
    missing_node = board_client.delete("/whiteboard/nodes/4321")
    assert missing_node.status_code == 404
    missing_sketch = board_client.delete("/whiteboard/sketches/4321")
    assert missing_sketch.status_code == 404


def test_a_sketch_round_trips_on_its_own_board(board_client, session):
    board = _note(session, "a board")
    made = board_client.post(
        "/whiteboard/sketches",
        json={"data": "M0 0 L10 10", "board_id": board.id, "x": 3, "y": 4},
    )
    assert made.status_code == 200, made.text

    # ...and does not leak onto the default board.
    assert board_client.get("/whiteboard/").json()["sketches"] == []
    scoped = board_client.get(f"/whiteboard/?board_id={board.id}").json()
    assert [s["data"] for s in scoped["sketches"]] == ["M0 0 L10 10"]


def test_an_enormous_sketch_is_refused_rather_than_stored(board_client):
    """The stroke list arrives as text and nothing bounded it, so a runaway
    client could fill the notebook's disk one PUT at a time."""
    from memorymap.api.routes_whiteboard import MAX_SKETCH_CHARS

    too_big = board_client.post(
        "/whiteboard/sketches", json={"data": "x" * (MAX_SKETCH_CHARS + 1)}
    )
    assert too_big.status_code == 422


def test_a_stale_board_id_is_refused_not_a_crash(board_client, session):
    """`board_id` is a real `ForeignKey("entries.id")`
    (`PRAGMA foreign_keys=ON`), writing one that doesn't exist wasn't
    validated the way `entry_id` already was, so it reached `db.commit()`
    and came back as a raw, unhandled `IntegrityError`, a 500, not a 404,
    and the frontend's own "the board is stale, reload" recovery only
    catches 4xx/error responses gracefully either way, but a 500 is a bug in
    its own right, not just a stale read.
    """
    entry = _note(session)
    refused = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "board_id": 9999}
    )
    assert refused.status_code == 404
    assert board_client.get("/whiteboard/").json()["nodes"] == []

    node = board_client.post("/whiteboard/nodes", json={"entry_id": entry.id}).json()
    moved = board_client.put(
        f"/whiteboard/nodes/{node['id']}",
        json={"entry_id": entry.id, "board_id": 9999, "x": 0, "y": 0},
    )
    assert moved.status_code == 404

    bad_sketch = board_client.post(
        "/whiteboard/sketches", json={"data": "M0 0 L1 1", "board_id": 9999}
    )
    assert bad_sketch.status_code == 404


def test_purging_a_note_removes_its_own_whiteboard_card(board_client, session):
    """`_hard_delete` deletes rows in half a dozen tables that carry a real
    `ForeignKey("entries.id")` before it deletes the entry itself, because
    `PRAGMA foreign_keys=ON` fails the whole `DELETE FROM entries` the
    instant one is left behind, reproduced live: emptying the recycle bin
    for a note that had a whiteboard card on it 500'd, and the note (and
    everything else in the same purge batch) stayed stuck in the bin.
    `WhiteboardNode`/`WhiteboardSketch` were added to the schema after
    `_hard_delete` was written and were never added to its cleanup list.
    """
    entry = _note(session)
    board_client.post("/whiteboard/nodes", json={"entry_id": entry.id})

    # The request is made on its own line, not inside the assert: `python -O`
    # strips assert statements, which would silently skip the bin step and
    # leave the purge below testing nothing. (CodeQL: py/side-effect-in-assert.)
    binned = board_client.delete(f"/entries/{entry.id}")
    assert binned.status_code == 200
    purged = board_client.delete(f"/entries/{entry.id}/purge")
    assert purged.status_code == 200, purged.text

    assert board_client.get("/whiteboard/").json()["nodes"] == []


def test_the_board_list_only_shows_boards_actually_in_use(board_client, session):
    """Reported directly: "the different board options confuse me." The
    picker used to be built client-side from *every note in the notebook*, 
    this is the fix, and the test pins the shape it has to have: the default
    board always present, and a note only listed once something is actually
    on it.
    """
    plain_note = _note(session, "just an ordinary note, never a board")
    board_note = _note(session, "a real board")
    board_client.post("/whiteboard/nodes", json={"entry_id": plain_note.id, "board_id": board_note.id})

    boards = board_client.get("/whiteboard/boards").json()
    ids = [b["id"] for b in boards]
    assert None in ids  # the default board is always offered
    assert board_note.id in ids
    assert plain_note.id not in ids  # never used as a board, not listed

    entry = next(b for b in boards if b["id"] == board_note.id)
    assert entry["node_count"] == 1
    assert entry["sketch_count"] == 0


def test_creating_a_board_makes_a_named_note_and_lists_it(board_client):
    """The other half of the same report: there was no way to make a new
    board except creating an ordinary note elsewhere and finding it again in
    the all-notes dropdown."""
    created = board_client.post("/whiteboard/boards", json={"name": "Project Atlas"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Project Atlas"
    assert body["node_count"] == 0

    # Reported live: a board made this way vanished from the list the moment
    # it was created (empty) or later cleared back to empty, indistinguishable
    # from the board having deleted itself, since the underlying note was
    # never actually touched. Explicitly creating a board is enough to keep
    # it listed even with nothing on it yet, unlike a *plain* note, which
    # still only becomes a board once something is drawn on it (the other
    # half of this file's own test above).
    boards = board_client.get("/whiteboard/boards").json()
    assert body["id"] in [b["id"] for b in boards]

    board_client.post("/whiteboard/sketches", json={"data": "M0 0 L1 1", "board_id": body["id"]})
    boards = board_client.get("/whiteboard/boards").json()
    entry = next(b for b in boards if b["id"] == body["id"])
    assert entry["title"] == "Project Atlas"
    assert entry["sketch_count"] == 1


def test_a_board_survives_being_emptied_back_out(board_client, session):
    """The other half of the live report: not just a fresh board, but one
    that *had* content and was cleared back to zero (every card/sketch/object
    on it removed) used to drop out of the list exactly the same way, the
    note itself was never deleted, but the only UI that could find it again
    had lost track of it. A board an ordinary note "graduates" into by
    having something drawn on it (never created via `+ New board`) has to
    survive this too, not just an explicitly-created one.
    """
    card_note = _note(session, "a note dropped onto someone else's board")
    board_note = _note(session, "an ordinary note someone started drawing on")
    created = board_client.post(
        "/whiteboard/nodes", json={"entry_id": card_note.id, "board_id": board_note.id}
    )
    node_id = created.json()["id"]

    boards = board_client.get("/whiteboard/boards").json()
    assert board_note.id in [b["id"] for b in boards]

    board_client.delete(f"/whiteboard/nodes/{node_id}")
    boards = board_client.get("/whiteboard/boards").json()
    ids = [b["id"] for b in boards]
    assert board_note.id in ids, "emptying a board must not make it vanish from the list"
    entry = next(b for b in boards if b["id"] == board_note.id)
    assert entry["node_count"] == 0


def test_renaming_a_board_rewrites_its_notes_heading_line(board_client, session):
    """A board's title is its underlying note's own first `#` heading: 
    `list_boards` reads it via `extract_title`, so renaming a board has to
    rewrite that line, not add a second stored field."""
    created = board_client.post("/whiteboard/boards", json={"name": "Old Name"}).json()
    board_client.post("/whiteboard/sketches", json={"data": "M0 0 L1 1", "board_id": created["id"]})

    renamed = board_client.put(f"/whiteboard/boards/{created['id']}", json={"title": "New Name"})
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["title"] == "New Name"
    assert body["sketch_count"] == 1

    entry = session.get(Entry, created["id"])
    session.refresh(entry)
    assert entry.content.splitlines()[0] == "# New Name"

    boards = board_client.get("/whiteboard/boards").json()
    listed = next(b for b in boards if b["id"] == created["id"])
    assert listed["title"] == "New Name"


def test_renaming_the_default_board_is_refused_not_a_crash(board_client):
    """`board_id=None` is the always-present scratch board, there is no
    underlying note to rewrite a heading line into."""
    resp = board_client.put("/whiteboard/boards/0", json={"title": "Nope"})
    assert resp.status_code == 404


def test_renaming_a_stale_board_id_404s(board_client):
    resp = board_client.put("/whiteboard/boards/999999", json={"title": "Ghost"})
    assert resp.status_code == 404


def test_an_image_object_needs_a_real_media_url(board_client):
    """A card wraps a note, a sketch is a path, neither is a placeable
    image. `data.url` has to be a same-origin `/media/...` path, the shape
    `POST /media/upload` always returns, not an arbitrary string a client
    could otherwise stash here."""
    refused = board_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "data": {"url": "https://evil.example/x.png"}},
    )
    assert refused.status_code == 422

    made = board_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "data": {"url": "/media/abc123.png"}, "x": 5, "y": 5},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["data"]["url"] == "/media/abc123.png"
    assert body["width"] == 200  # the default, not zero


def test_a_text_object_round_trips_with_its_own_style(board_client):
    made = board_client.post(
        "/whiteboard/objects",
        json={
            "kind": "text",
            "data": {"content": "Meeting notes", "color": "#ffcc00", "font_size": 18},
            "x": 10, "y": 20, "width": 240, "height": 80,
        },
    )
    assert made.status_code == 201, made.text
    obj_id = made.json()["id"]

    state = board_client.get("/whiteboard/").json()
    assert len(state["objects"]) == 1
    assert state["objects"][0]["data"] == {
        "content": "Meeting notes", "color": "#ffcc00", "font_size": 18, "url": None,
        "bg": None, "border_color": None,
        # Added with the text-box formatting controls; None until set.
        "align": None,
        "md": None,
        # Added with mindmaps (MINDMAP_PLAN.md Phase 1). A text box is not a
        # map node, so all three stay None, asserted rather than omitted
        # because this test's whole job is to catch a field that silently
        # stops round-tripping, and it can only do that by naming every one.
        "ref_id": None,
        "collapsed": None,
        "pinned": None,
        # Added with the map's node edit strip (MINDMAP_PLAN.md §12.1 item 2),
        # and named here for the same reason as the three above.
        "bold": None,
        "italic": None,
        # And with the four node shapes (§12.1 item 3, decided in §12.0).
        "shape": None,
        "icon": None,
        "link": None,
        "edge_label": None,
        "edge_style": None,
        "edge_dashed": None,
    }

    moved = board_client.put(
        f"/whiteboard/objects/{obj_id}",
        json={
            "kind": "text",
            "data": {"content": "Meeting notes: updated"},
            "x": 50, "y": 60, "width": 300, "height": 90,
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["x"] == 50
    assert moved.json()["width"] == 300
    assert moved.json()["data"]["content"] == "Meeting notes: updated"


def test_an_objects_kind_cannot_be_changed_on_update(board_client):
    made = board_client.post(
        "/whiteboard/objects", json={"kind": "text", "data": {"content": "hi"}}
    ).json()
    refused = board_client.put(
        f"/whiteboard/objects/{made['id']}",
        json={"kind": "image", "data": {"url": "/media/x.png"}},
    )
    assert refused.status_code == 422


def test_an_image_url_cannot_point_outside_the_media_folder(board_client, tmp_path):
    """`delete_object` unlinks the file behind an image object, so a
    `startswith("/media/")` check on the way in is a file-deletion hole:
    `/media/../../../x` passes it and resolves anywhere on disk. Caught by
    CodeQL as a path-injection alert on the commit that introduced it.
    """
    outsider = deps.get_config().data_dir / "DO_NOT_DELETE.txt"
    outsider.write_text("important")

    for bad in (
        "/media/../DO_NOT_DELETE.txt",
        "/media/../../etc/passwd",
        "/media/sub/dir.png",
        "/mediafoo.png",
        "https://evil.example/x.png",
    ):
        refused = board_client.post(
            "/whiteboard/objects", json={"kind": "image", "data": {"url": bad}}
        )
        assert refused.status_code == 422, f"{bad!r} should be refused, got {refused.status_code}"

    assert outsider.exists()
    assert board_client.get("/whiteboard/").json()["objects"] == []


def test_a_legacy_traversing_url_still_cannot_delete_an_outside_file(board_client, session):
    """Defence in depth: a row written before the pattern check existed (or
    by anything that skips it) must still not be able to unlink whatever it
    names. `_media_path` resolves and confirms containment rather than
    trusting the stored string."""
    from memorymap.core.database import WhiteboardObject

    outsider = deps.get_config().data_dir / "SURVIVOR.txt"
    outsider.write_text("important")

    smuggled = WhiteboardObject(
        kind="image", data='{"url": "/media/../SURVIVOR.txt"}', x=0, y=0, width=50, height=50
    )
    session.add(smuggled)
    session.commit()

    deleted = board_client.delete(f"/whiteboard/objects/{smuggled.id}")
    assert deleted.status_code == 200
    assert outsider.exists(), "the row went, but it must not take an outside file with it"


def test_deleting_an_image_object_removes_its_file_from_disk(board_client):
    """The only row that ever pointed at this file, unlike a note's inline
    `![]()` image, which nothing in the app tracks or cleans up yet."""
    media_dir = deps.get_config().data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "keepme.png").write_bytes(b"fake png bytes")

    made = board_client.post(
        "/whiteboard/objects", json={"kind": "image", "data": {"url": "/media/keepme.png"}}
    ).json()
    assert (media_dir / "keepme.png").exists()

    deleted = board_client.delete(f"/whiteboard/objects/{made['id']}")
    assert deleted.status_code == 200
    assert not (media_dir / "keepme.png").exists()
    assert board_client.get("/whiteboard/").json()["objects"] == []


def test_objects_count_toward_a_board_appearing_in_the_list(board_client, session):
    board = _note(session, "a board with only a text box on it")
    board_client.post(
        "/whiteboard/objects",
        json={"kind": "text", "data": {"content": "hi"}, "board_id": board.id},
    )
    boards = board_client.get("/whiteboard/boards").json()
    entry = next(b for b in boards if b["id"] == board.id)
    assert entry["object_count"] == 1


def test_purging_a_board_note_detaches_its_cards_instead_of_deleting_them(
    board_client, session
):
    """The board itself is just a note (`board_id` points at one), and
    purging *that* note must not take every card on the board down with
    it: the same 'orphan becomes a root' choice already made for
    `Entry.parent_id`, not a cascade delete.
    """
    entry, board = _note(session), _note(session, "a board")
    node = board_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "board_id": board.id}
    ).json()

    # Out of the assert for the same reason as above, under `python -O` the
    # board would never reach the bin and the purge would be a no-op.
    binned = board_client.delete(f"/entries/{board.id}")
    assert binned.status_code == 200
    purged = board_client.delete(f"/entries/{board.id}/purge")
    assert purged.status_code == 200, purged.text

    # The card survives, moved to the default board rather than deleted.
    default_board = board_client.get("/whiteboard/").json()["nodes"]
    assert [n["id"] for n in default_board] == [node["id"]]
    assert default_board[0]["board_id"] is None


def test_moving_a_card_keeps_it_on_its_board(ai_client, session):
    """`PUT /whiteboard/nodes/{id}` takes the whole node, and the browser was
    not sending `board_id`, so dragging a card on a named board read as "move
    this to the global board" and it vanished from the board you were looking
    at."""
    entry = _note(session, "a note")
    board = _note(session, "a board")
    node = ai_client.post(
        "/whiteboard/nodes", json={"entry_id": entry.id, "board_id": board.id}
    ).json()

    moved = ai_client.put(
        f"/whiteboard/nodes/{node['id']}",
        json={"entry_id": entry.id, "board_id": board.id, "x": 40, "y": 50},
    )
    assert moved.status_code == 200
    assert moved.json()["board_id"] == board.id
    on_board = ai_client.get(f"/whiteboard/?board_id={board.id}").json()
    assert [n["id"] for n in on_board["nodes"]] == [node["id"]]


def test_the_frontend_sends_the_board_when_it_moves_a_card():
    """The guard for the half of that bug that lives in the browser."""
    from memorymap.api.app import FRONTEND_DIR

    # The whiteboard subsystem moved out of app.js into its own file, loaded
    # by a second <script> tag, see index.html, so this comment now lives
    # in whiteboard.js, not app.js.
    whiteboard_js = (FRONTEND_DIR / "whiteboard.js").read_text(encoding="utf-8")
    save = whiteboard_js[whiteboard_js.index("// Sync back to API.") :][:900]
    assert "board_id" in save, "the coordinate save must carry the card's board"


def test_deleting_an_item_takes_its_links_with_it(board_client, session):
    """A link is a sketch row that names its two ends. The frontend hides a
    link whose end is gone, but the row stayed, an orphan on every board a
    card was ever deleted from. Deleting a card, a text box or a shape now
    removes the links that touched it, and nothing else."""
    entry = _note(session)
    node = board_client.post("/whiteboard/nodes", json={"entry_id": entry.id, "x": 0, "y": 0}).json()
    obj = board_client.post(
        "/whiteboard/objects",
        json={"kind": "text", "data": {"content": "hi"}, "x": 300, "y": 0, "width": 100, "height": 60},
    ).json()
    shape = board_client.post(
        "/whiteboard/sketches", json={"data": '{"type": "rect", "d": "M0 0 h50 v50 h-50 z"}', "x": 0, "y": 0}
    ).json()
    link_node_obj = board_client.post(
        "/whiteboard/sketches",
        json={"data": f'{{"type": "link-straight", "sourceId": {node["id"]}, "targetId": {obj["id"]}, "targetKind": "object"}}', "x": 0, "y": 0},
    ).json()
    link_shape_obj = board_client.post(
        "/whiteboard/sketches",
        json={"data": f'{{"type": "link-curved", "sourceId": {shape["id"]}, "sourceKind": "sketch", "targetId": {obj["id"]}, "targetKind": "object"}}', "x": 0, "y": 0},
    ).json()

    # The request runs outside the assert: CodeQL flags a side-effecting
    # expression inside one, and `-O` would skip it entirely.
    gone_node = board_client.delete(f"/whiteboard/nodes/{node['id']}")
    assert gone_node.status_code == 200
    ids = {s["id"] for s in board_client.get("/whiteboard/").json()["sketches"]}
    assert link_node_obj["id"] not in ids
    assert link_shape_obj["id"] in ids and shape["id"] in ids

    gone_obj = board_client.delete(f"/whiteboard/objects/{obj['id']}")
    assert gone_obj.status_code == 200
    ids = {s["id"] for s in board_client.get("/whiteboard/").json()["sketches"]}
    assert link_shape_obj["id"] not in ids
    assert shape["id"] in ids


def test_a_text_box_keeps_its_alignment_and_markdown_flag(board_client):
    """`align` and `md` are real fields, not extras Pydantic drops. The first
    version of the text-box formatting controls stored them client-side only,
    so every toggle came back empty on the next render."""
    made = board_client.post(
        "/whiteboard/objects",
        json={
            "kind": "text",
            "data": {"content": "# Plan", "align": "center", "md": True},
            "x": 0, "y": 0, "width": 200, "height": 120,
        },
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["data"]["align"] == "center"
    assert body["data"]["md"] is True

    round_trip = board_client.get("/whiteboard/").json()["objects"]
    stored = next(o for o in round_trip if o["id"] == body["id"])
    assert stored["data"]["align"] == "center"
    assert stored["data"]["md"] is True

    refused = board_client.post(
        "/whiteboard/objects",
        json={"kind": "text", "data": {"content": "x", "align": "sideways"}, "x": 0, "y": 0},
    )
    assert refused.status_code == 422


def test_purging_a_map_unlinks_the_files_behind_its_image_nodes(board_client, session):
    """A map's objects are deleted with the map (an ordinary board's are
    detached and keep theirs), so the files behind a map's image objects
    would otherwise sit in `<data>/media` with no row pointing at them, 
    BACKLOG §116.1 item 1. The allowlist is the same as the delete route's:
    a url that does not resolve inside the media folder is left alone."""
    media_dir = deps.get_config().data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "onmap.png").write_bytes(b"fake png bytes")
    (media_dir / "onboard.png").write_bytes(b"fake png bytes")
    outsider = deps.get_config().data_dir / "NOT_MEDIA.txt"
    outsider.write_text("must survive")

    the_map = board_client.post(
        "/whiteboard/boards", json={"name": "Purge me", "type": "map", "layout": "tree-right"}
    ).json()
    plain = board_client.post("/whiteboard/boards", json={"name": "Keep my picture"}).json()
    board_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "board_id": the_map["id"], "data": {"url": "/media/onmap.png"}},
    )
    board_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "board_id": plain["id"], "data": {"url": "/media/onboard.png"}},
    )
    # A row that would escape the media folder if the path were trusted.
    escaped = board_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "board_id": the_map["id"], "data": {"url": "/media/../NOT_MEDIA.txt"}},
    )
    assert escaped.status_code == 422  # refused on the way in; the purge is the second guard

    for board in (the_map, plain):
        binned = board_client.delete(f"/entries/{board['id']}")
        assert binned.status_code == 200, binned.text
        purged = board_client.delete(f"/entries/{board['id']}/purge")
        assert purged.status_code == 200, purged.text

    assert not (media_dir / "onmap.png").exists()
    assert (media_dir / "onboard.png").exists()  # detached with its object, not deleted
    assert outsider.exists()


def test_a_created_map_does_not_appear_in_the_notes_list(board_client, session):
    """Reported: "I made a mindmap naming it test and I think it came up as a
    new note??" It did.

    A board, and a mind map, which is a board with `type: "map"`, is an
    `Entry` (`Entry.is_board`), and `GET /entries` had no filter for that at
    all, so every board in the notebook was in the notes list, in its count,
    and in everything else built on that response. Measured in a real browser
    on a notebook with nine maps: twelve rows in the Notes list, ten of them
    maps.

    The three modes are asserted together deliberately: the default excluding
    boards is only safe because `boards=only` still exists for the two callers
    that genuinely want them (the `[[wiki]]` resolver and the editor's `@`
    picker), and a regression in either direction breaks one of those.
    """
    note = _note(session, "# A real note")
    made = board_client.post(
        "/whiteboard/boards", json={"name": "test", "type": "map", "layout": "tree-right"}
    )
    assert made.status_code == 201, made.text
    map_id = made.json()["id"]
    plain = board_client.post("/whiteboard/boards", json={"name": "A plain board"}).json()

    listed = board_client.get("/entries")
    assert listed.status_code == 200, listed.text
    ids = [row["id"] for row in listed.json()]
    assert note.id in ids
    assert map_id not in ids, "a mind map is not a note"
    assert plain["id"] not in ids, "nor is an ordinary board"
    # The header has to agree with the list under it, or the Notes tab counts
    # rows nobody can see.
    assert int(listed.headers["X-Total-Count"]) == len(ids)

    only = board_client.get("/entries?boards=only").json()
    only_ids = [row["id"] for row in only]
    assert map_id in only_ids and plain["id"] in only_ids
    assert note.id not in only_ids

    both = board_client.get("/entries?boards=include").json()
    both_ids = [row["id"] for row in both]
    assert {note.id, map_id, plain["id"]} <= set(both_ids)

    assert board_client.get("/entries?boards=sideways").status_code == 422


def test_loading_a_board_drops_an_edge_whose_end_is_gone(board_client, session):
    """Reported with a screenshot: a node with "a dangling curved edge to
    nowhere (an edge whose other end is a deleted node or a point)".

    Every *delete* route already calls `_forget_links_to`, so this is not
    about those. A link's two ends are ids inside a JSON blob rather than
    foreign keys, so nothing at the database level enforces them, and one live
    path removes a row without going through a delete route at all: purging a
    note deletes its `WhiteboardNode` rows in bulk (`entry/manager.py`). The
    link that pointed at the card survived it, with an id resolving to
    nothing, measured in the browser before this was written.

    The free-point link in here is the control, and it matters as much as the
    orphan: a link end with no item at all is a real feature ("even make it a
    dangling unattached point"), so an integrity pass that ate one would be a
    worse bug than the one it fixes.
    """
    import json

    board = board_client.post("/whiteboard/boards", json={"name": "Integrity"}).json()
    note = _note(session, "# A note that gets purged")
    card = board_client.post(
        "/whiteboard/nodes", json={"entry_id": note.id, "board_id": board["id"], "x": 0, "y": 0}
    ).json()
    keeper = board_client.post(
        "/whiteboard/objects",
        json={"kind": "topic", "board_id": board["id"], "data": {"content": "Bubble Tea"}},
    ).json()

    orphan = board_client.post(
        "/whiteboard/sketches",
        json={
            "board_id": board["id"],
            "data": json.dumps(
                {"type": "link-curve", "sourceKind": "object", "sourceId": keeper["id"],
                 "targetKind": "node", "targetId": card["id"]}
            ),
        },
    ).json()
    free_end = board_client.post(
        "/whiteboard/sketches",
        json={
            "board_id": board["id"],
            "data": json.dumps(
                {"type": "link-curve", "sourceKind": "object", "sourceId": keeper["id"],
                 "targetPoint": {"x": 300, "y": 520}}
            ),
        },
    ).json()

    # The purge path, which is the one that leaves the orphan behind.
    board_client.delete(f"/entries/{note.id}")
    purged = board_client.delete(f"/entries/{note.id}/purge")
    assert purged.status_code == 200, purged.text

    state = board_client.get(f"/whiteboard/?board_id={board['id']}").json()
    ids = [row["id"] for row in state["sketches"]]
    assert orphan["id"] not in ids, "an edge whose end is gone is dropped on load"
    assert free_end["id"] in ids, "an edge that deliberately ends at a point is kept"

    # And it is really deleted, not merely filtered out of one response.
    again = board_client.get(f"/whiteboard/?board_id={board['id']}").json()
    assert [row["id"] for row in again["sketches"]] == [free_end["id"]]



def test_deleting_a_card_survives_a_sketch_whose_data_is_a_list(client, session):
    """A sketch's `data` is free text as far as the API is concerned, and only
    a *link* sketch is an object with a `type`. A drawing stored as a bare
    JSON array used to make `_forget_links_to` call `.get` on a list, so
    deleting an unrelated card on that board answered 500.
    """
    note = client.post("/entries", json={"content": "a note", "tags": []}).json()
    node = client.post("/whiteboard/nodes", json={"entry_id": note["id"]}).json()
    client.post("/whiteboard/sketches", json={"data": "[[1,2],[3,4]]"})

    # The call is its own statement, not the assertion's expression: `python -O`
    # strips asserts, and a test whose only delete lives inside one silently
    # stops exercising anything (CodeQL alert 403, and the sixth of this shape
    # on this branch).
    removed = client.delete(f"/whiteboard/nodes/{node['id']}")
    assert removed.status_code == 200
