"""A board's thumbnail: its shape, its branch colours, and the cache.

The picture on a Library card used to be a scatter of one-grey dots in a box
the shape of the card rather than the shape of the board, recomputed from
scratch on every visit. This file gates the three things that changed:

- **aspect**, so the miniature is letterboxed at the board's own ratio
  instead of stretched (`preview_aspect`, drawn by `mapPreview` in app.js);
- **colour**, so a map's thumbnail is the same picture as its canvas, branch
  by branch (`MAP_BRANCH_PALETTE`, Coggle's rule, which `wbMapColors`
  implements client-side);
- **the cache**, which is invisible in the response by construction: an
  identical answer is exactly what a cache is for, so the only way to assert
  it is the counter it keeps (`PREVIEW_CACHE_STATS`).

The staleness cases have their own tests here, because a preview cache that
serves the old picture is worse than no cache at all: the board a person is
looking at is the one they just changed.
"""

from __future__ import annotations

from memorymap.api.routes_whiteboard import (
    MAP_BRANCH_PALETTE,
    PREVIEW_ASPECT_RANGE,
    PREVIEW_CACHE_STATS,
    _preview_fields,
)


def _map(client, name="Shape map"):
    board = client.post(
        "/whiteboard/boards", json={"name": name, "type": "map", "layout": "tree-right"}
    )
    assert board.status_code == 201, board.text
    return board.json()


def _node(client, board_id, *, parent_id=None, text="", x=None, y=None, color=None):
    body = {"kind": "topic", "parent_id": parent_id, "text": text}
    if x is not None:
        body["x"], body["y"] = x, y
    if color is not None:
        body["color"] = color
    created = client.post(f"/whiteboard/boards/{board_id}/nodes", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _row(client, board_id):
    boards = client.get("/whiteboard/boards").json()
    return next(b for b in boards if b["id"] == board_id)


# --- aspect -----------------------------------------------------------------


def test_a_wide_board_reports_a_wide_thumbnail(client):
    """The number the client letterboxes with. Two nodes 400 apart across and
    100 apart down is a board twice as wide as it is tall, and that is the
    one fact normalising into 0..1 destroys."""
    board = _map(client)
    _node(client, board["id"], text="left", x=0, y=0)
    _node(client, board["id"], text="right", x=400, y=200)
    assert _row(client, board["id"])["preview_aspect"] == 2.0


def test_a_tall_board_reports_a_tall_thumbnail(client):
    board = _map(client)
    _node(client, board["id"], text="top", x=0, y=0)
    _node(client, board["id"], text="bottom", x=100, y=150)
    assert _row(client, board["id"])["preview_aspect"] == round(100 / 150, 3)


def test_an_extreme_board_is_clamped_rather_than_drawn_as_a_sliver(client):
    """A board 40 times wider than it is tall, drawn honestly, is a two-pixel
    band inside an otherwise empty card: past the clamp the ratio has stopped
    being information about the board."""
    board = _map(client)
    _node(client, board["id"], text="left", x=0, y=0)
    _node(client, board["id"], text="far", x=4000, y=100)
    assert _row(client, board["id"])["preview_aspect"] == PREVIEW_ASPECT_RANGE[1]


def test_a_single_node_keeps_the_square(client):
    """One node has no extent on either axis. The alternative to the square is
    a divide by zero or a shape invented out of a rounding error."""
    board = _map(client)
    _node(client, board["id"], text="only", x=10, y=10)
    assert _row(client, board["id"])["preview_aspect"] == 1.0


# --- colour -----------------------------------------------------------------


def test_each_first_level_branch_takes_the_next_palette_colour(client):
    """Coggle's rule, which the canvas already follows: the colour starts at
    the branch, not at the root, or the whole map is one colour."""
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], text="One")
    _node(client, board["id"], parent_id=root["id"], text="Two")

    items = {i["label"]: i for i in _row(client, board["id"])["preview_items"]}
    assert "color" not in items["Root"]
    assert items["One"]["color"] == MAP_BRANCH_PALETTE[0]
    assert items["Two"]["color"] == MAP_BRANCH_PALETTE[1]


def test_a_descendant_inherits_its_branch(client):
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    branch = _node(client, board["id"], parent_id=root["id"], text="Branch")
    _node(client, board["id"], parent_id=branch["id"], text="Leaf")

    items = {i["label"]: i for i in _row(client, board["id"])["preview_items"]}
    assert items["Leaf"]["color"] == items["Branch"]["color"] == MAP_BRANCH_PALETTE[0]


def test_a_nodes_own_colour_wins_and_carries_down(client):
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    branch = _node(client, board["id"], parent_id=root["id"], text="Branch", color="#123456")
    _node(client, board["id"], parent_id=branch["id"], text="Leaf")

    items = {i["label"]: i for i in _row(client, board["id"])["preview_items"]}
    assert items["Branch"]["color"] == "#123456"
    assert items["Leaf"]["color"] == "#123456"


def test_an_ordinary_board_ships_no_colours(client):
    """Colour on a board would be a claim about structure it does not have,
    and `color` is omitted rather than sent as null: a twenty-board list ships
    eight hundred of these items."""
    board = client.post("/whiteboard/boards", json={"name": "Plain"}).json()
    client.post(
        "/whiteboard/objects",
        json={"kind": "text", "board_id": board["id"], "data": {"content": "hi"}},
    )
    items = _row(client, board["id"])["preview_items"]
    assert items and all("color" not in item for item in items)


# --- the cache --------------------------------------------------------------


def test_the_second_board_list_draws_from_the_cache(client):
    """The Library rebuilds every thumbnail on every visit, and a thumbnail is
    a full scan of the board. The second visit to an unchanged board must not
    pay for it again."""
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], text="Child")

    first = _row(client, board["id"])
    before = dict(PREVIEW_CACHE_STATS)
    second = _row(client, board["id"])

    assert PREVIEW_CACHE_STATS["hits"] > before["hits"]
    assert PREVIEW_CACHE_STATS["misses"] == before["misses"]
    assert second["preview_items"] == first["preview_items"]
    assert second["preview_edges"] == first["preview_edges"]
    assert second["preview_aspect"] == first["preview_aspect"]


def test_moving_a_node_redraws_the_thumbnail(client):
    """The staleness case that matters most: the board someone is looking at
    is the board they just changed."""
    board = _map(client)
    root = _node(client, board["id"], text="Root", x=0, y=0)
    _node(client, board["id"], parent_id=root["id"], text="Child", x=100, y=100)
    before = _row(client, board["id"])["preview_aspect"]

    moved = client.put(
        f"/whiteboard/objects/{root['id']}",
        json={
            "kind": "topic",
            "board_id": board["id"],
            "data": {"content": "Root"},
            "x": 0.0,
            "y": -300.0,
        },
    )
    assert moved.status_code == 200, moved.text
    assert _row(client, board["id"])["preview_aspect"] != before


def test_renaming_a_note_redraws_the_card_that_stands_for_it(client):
    """A card's label is the note's title, and renaming a note touches nothing
    on the board at all: the fingerprint has to reach through to the entry or
    the Library shows the old name until something else changes."""
    note = client.post("/entries", json={"content": "# First name\n\nBody"}).json()
    board = client.post("/whiteboard/boards", json={"name": "Cards"}).json()
    placed = client.post(
        "/whiteboard/nodes",
        json={"entry_id": note["id"], "board_id": board["id"], "x": 0, "y": 0},
    )
    assert placed.status_code == 200, placed.text
    assert _row(client, board["id"])["preview_items"][0]["label"] == "First name"

    client.put(f"/entries/{note['id']}", json={"content": "# Second name\n\nBody"})
    assert _row(client, board["id"])["preview_items"][0]["label"] == "Second name"


def test_the_cached_lists_are_copied_on_the_way_out(client, session):
    """A caller that mutates a preview in place would otherwise poison every
    board list drawn after it, and the fault would surface somewhere else
    entirely."""
    board = _map(client)
    _node(client, board["id"], text="Root")

    first = _preview_fields(session, board["id"])
    first["preview_items"][0]["label"] = "mutated"
    assert _preview_fields(session, board["id"])["preview_items"][0]["label"] == "Root"
    assert _row(client, board["id"])["preview_items"][0]["label"] == "Root"
