"""Mindmaps: the map object, its tree, and the rule that a map contains its
own contents (MINDMAP_PLAN.md Phase 1).

The containment tests come first in this file because they were written
first, before any of the code they cover, the plan says so by name ("Write
the test first; this is the rule most likely to be got wrong"), and the rule
itself is the one place where getting it wrong destroys somebody's notes
rather than drawing a wrong picture:

> any and all text boxes and things that are in the map stay bundled within
> the map

A `topic` exists only in the map, so it goes with the map. A `note` /
`document` / `file` node is a *pointer at something in the library*, so the
pointer goes and the thing it pointed at must still be there afterwards.
Those are opposite outcomes for two rows in the same table, which is exactly
why a test says which is which.
"""

from __future__ import annotations

import json

from memorymap.api.routes_whiteboard import MAP_BRANCH_PALETTE
from memorymap.core.database import Entry, WhiteboardObject


def _map(client, name="Thesis map", layout="tree-right"):
    board = client.post(
        "/whiteboard/boards", json={"name": name, "type": "map", "layout": layout}
    )
    assert board.status_code == 201, board.text
    return board.json()


def _node(client, board_id, *, parent_id=None, text="", kind="topic", ref_id=None):
    body = {"kind": kind, "parent_id": parent_id, "text": text}
    if ref_id is not None:
        body["ref_id"] = ref_id
    created = client.post(f"/whiteboard/boards/{board_id}/nodes", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _purge(client, entry_id):
    """The bin, then the bin emptied, the only path to a permanent delete,
    and the one the Library's own Delete action starts down."""
    binned = client.delete(f"/entries/{entry_id}")
    assert binned.status_code == 200, binned.text
    purged = client.delete(f"/entries/{entry_id}/purge")
    assert purged.status_code == 200, purged.text


# --- containment ------------------------------------------------------------


def test_deleting_a_map_takes_its_topics_and_leaves_the_notes_it_referenced(
    client, session
):
    """The rule, both halves of it, in one test.

    Without this the default behaviour is actively wrong in two different
    directions at once: purging a board detaches everything on it to the
    default scratch board (`manager._hard_delete`), so a deleted map's topics
    would reappear as loose text on the one board nobody deletes, and any
    attempt to fix that by simply deleting everything on the board would take
    the referenced *notes* with it, which is data loss.
    """
    note = client.post("/entries", json={"content": "Chapter three"}).json()
    board = _map(client)
    topic = _node(client, board["id"], text="Root")
    child = _node(client, board["id"], parent_id=topic["id"], text="Branch")
    reference = _node(
        client, board["id"], parent_id=topic["id"], kind="note", ref_id=note["id"]
    )

    _purge(client, board["id"])

    for object_id in (topic["id"], child["id"], reference["id"]):
        assert session.get(WhiteboardObject, object_id) is None, (
            f"object {object_id} outlived the map it lived in"
        )
    survivor = session.get(Entry, note["id"])
    assert survivor is not None and not survivor.is_deleted, (
        "deleting a map deleted a note that only happened to be referenced by it"
    )


def test_deleting_an_ordinary_board_still_detaches_its_objects(client, session):
    """The behaviour containment must not break.

    A plain whiteboard's text boxes and images are *not* bundled: purging the
    board note detaches them to the default board rather than destroying
    them, deliberately (see `_hard_delete`'s own comment: "delete this one
    note" must not silently wipe a whiteboard). Containment is a rule about
    maps, and this asserts it stayed one.
    """
    board = client.post("/whiteboard/boards", json={"name": "Scratch"}).json()
    text = client.post(
        "/whiteboard/objects",
        json={"kind": "text", "board_id": board["id"], "data": {"content": "hello"}},
    ).json()

    _purge(client, board["id"])

    survivor = session.get(WhiteboardObject, text["id"])
    assert survivor is not None, "an ordinary board's text box was destroyed with it"
    assert survivor.board_id is None


def test_deleting_a_topic_deletes_its_subtree_and_hands_it_back(client):
    """Coggle's choice, made deliberately: a deleted branch takes its
    children with it rather than re-homing them on the grandparent.

    Re-parenting reads as tidier and is worse: a branch you meant to remove
    reappears as loose children under a node that never had them, and there
    is no single action that undoes it. Deleting the subtree is one action, 
    so the response carries the whole subtree back, which is what lets the
    frontend offer a real undo instead of a warning dialog.
    """
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    branch = _node(client, board["id"], parent_id=root["id"], text="Branch")
    leaf = _node(client, board["id"], parent_id=branch["id"], text="Leaf")
    keep = _node(client, board["id"], parent_id=root["id"], text="Sibling")

    gone = client.delete(f"/whiteboard/objects/{branch['id']}")
    assert gone.status_code == 200, gone.text
    deleted = gone.json()["deleted"]
    assert {row["id"] for row in deleted} == {branch["id"], leaf["id"]}
    # Enough to rebuild the branch, not just to count it.
    assert {row["parent_id"] for row in deleted} == {root["id"], branch["id"]}
    assert {row["data"]["content"] for row in deleted} == {"Branch", "Leaf"}

    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert [n["id"] for n in tree["roots"]] == [root["id"]]
    assert [n["id"] for n in tree["roots"][0]["children"]] == [keep["id"]]


def test_deleting_a_reference_node_leaves_the_note_alone(client, session):
    """The single-node case of the same rule, a map node is a pointer, and
    removing a pointer is not removing the thing."""
    note = client.post("/entries", json={"content": "Keep me"}).json()
    board = _map(client)
    reference = _node(client, board["id"], kind="note", ref_id=note["id"])

    removed = client.delete(f"/whiteboard/objects/{reference['id']}")
    assert removed.status_code == 200, removed.text

    survivor = session.get(Entry, note["id"])
    assert survivor is not None and not survivor.is_deleted


# --- the map object ---------------------------------------------------------


def test_a_board_is_a_free_whiteboard_unless_it_says_otherwise(client):
    """Every board that existed before this feature has NULL settings, and
    NULL has to read as "an ordinary free-layout whiteboard" rather than as
    anything needing a backfill."""
    board = client.post("/whiteboard/boards", json={"name": "Plain"}).json()
    assert (board["type"], board["layout"]) == ("board", "free")

    listed = {b["id"]: b for b in client.get("/whiteboard/boards").json()}
    assert listed[board["id"]]["type"] == "board"
    # The default scratch board has no note behind it to store settings on.
    assert listed[None]["type"] == "board"


def test_type_and_layout_survive_a_round_trip_through_the_list(client):
    board = _map(client, name="Radial", layout="radial")
    assert (board["type"], board["layout"]) == ("map", "radial")

    listed = {b["id"]: b for b in client.get("/whiteboard/boards").json()}
    assert listed[board["id"]]["layout"] == "radial"


def test_the_layout_can_be_changed_without_renaming_the_board(client):
    """`PUT /whiteboard/boards/{id}` was rename-only, and a title was
    required. Switching a map's layout must not force the caller to resend
    the title it isn't changing: that is how a rename race loses an edit."""
    board = _map(client, name="Keep this name")
    updated = client.put(
        f"/whiteboard/boards/{board['id']}", json={"layout": "tree-down"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Keep this name"
    assert updated.json()["layout"] == "tree-down"


def test_an_unknown_type_or_layout_is_refused_rather_than_stored(client):
    assert (
        client.post("/whiteboard/boards", json={"name": "x", "type": "graph"}).status_code
        == 422
    )
    assert (
        client.post(
            "/whiteboard/boards", json={"name": "x", "layout": "spiral"}
        ).status_code
        == 422
    )


def test_the_maps_filter_returns_maps_and_nothing_else(client):
    """The Library's Maps chip. A filter that silently returns everything is
    worse than no filter, it reads as "you have no boards" only once the
    user has looked at every row."""
    plain = client.post("/whiteboard/boards", json={"name": "Whiteboard"}).json()
    mapped = _map(client, name="Mindmap")

    maps = client.get("/whiteboard/boards?type=map").json()
    assert [b["id"] for b in maps] == [mapped["id"]]

    boards = client.get("/whiteboard/boards?type=board").json()
    ids = [b["id"] for b in boards]
    assert plain["id"] in ids and mapped["id"] not in ids
    # The default scratch board is a board, so it belongs in one list and not
    # the other: it dropped out of both in the first draft of this filter.
    assert None in ids


# --- the tree ---------------------------------------------------------------


def test_the_tree_nests_children_under_their_parents_with_cross_links(client):
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    left = _node(client, board["id"], parent_id=root["id"], text="Left")
    right = _node(client, board["id"], parent_id=root["id"], text="Right")

    # A cross-link is a link sketch, exactly as it already is between two
    # cards: there is no second kind of edge and no second endpoint for one.
    linked = client.post(
        "/whiteboard/sketches",
        json={
            "board_id": board["id"],
            "data": json.dumps(
                {
                    "type": "link-straight",
                    "sourceId": left["id"],
                    "sourceKind": "object",
                    "targetId": right["id"],
                    "targetKind": "object",
                    "label": "compare",
                }
            ),
        },
    )
    assert linked.status_code == 200, linked.text

    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert tree["type"] == "map"
    assert [n["id"] for n in tree["roots"]] == [root["id"]]
    kids = tree["roots"][0]["children"]
    assert [n["text"] for n in kids] == ["Left", "Right"]
    assert kids[0]["kind"] == "topic"
    assert tree["cross_links"] == [
        {"from_id": left["id"], "to_id": right["id"], "label": "compare"}
    ]


def test_a_node_whose_parent_is_gone_reads_as_a_root(client, session):
    """A dangling `parent_id` must not make a branch invisible.

    `parent_id` is a plain integer, not a foreign key (see the column's own
    comment), so nothing at the database level stops one going stale. A tree
    builder that only walks down from `parent_id IS NULL` silently loses
    every node under a broken pointer, the board still holds them, the map
    just stops showing them, which is the worst way to lose something.
    """
    board = _map(client)
    orphan = _node(client, board["id"], text="Orphan")
    row = session.get(WhiteboardObject, orphan["id"])
    row.parent_id = 999_999
    session.commit()

    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert [n["id"] for n in tree["roots"]] == [orphan["id"]]


def test_a_node_cannot_be_moved_under_its_own_descendant(client):
    """The cycle check. Without it the tree walk never terminates, and the
    board is unreadable from then on with no way back through the UI that
    made it."""
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    child = _node(client, board["id"], parent_id=root["id"], text="Child")
    grandchild = _node(client, board["id"], parent_id=child["id"], text="Grandchild")

    refused = client.put(
        f"/whiteboard/boards/{board['id']}/nodes/{root['id']}/move",
        json={"parent_id": grandchild["id"]},
    )
    assert refused.status_code == 422, refused.text
    assert "descendant" in refused.json()["detail"].lower()

    # And the obvious degenerate case of the same thing.
    itself = client.put(
        f"/whiteboard/boards/{board['id']}/nodes/{root['id']}/move",
        json={"parent_id": root["id"]},
    )
    assert itself.status_code == 422


def test_moving_a_node_to_a_root_and_back_under_a_parent(client):
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    child = _node(client, board["id"], parent_id=root["id"], text="Child")

    promoted = client.put(
        f"/whiteboard/boards/{board['id']}/nodes/{child['id']}/move",
        json={"parent_id": None},
    )
    assert promoted.status_code == 200, promoted.text
    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert {n["id"] for n in tree["roots"]} == {root["id"], child["id"]}

    client.put(
        f"/whiteboard/boards/{board['id']}/nodes/{child['id']}/move",
        json={"parent_id": root["id"]},
    )
    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert [n["id"] for n in tree["roots"]] == [root["id"]]


def test_a_node_cannot_be_parented_onto_another_boards_node(client):
    """`board_id` scoping, the same rule the rest of this file already
    learned: a write has to be scoped to the board it claims."""
    here = _map(client, name="Here")
    there = _map(client, name="There")
    mine = _node(client, here["id"], text="Mine")
    theirs = _node(client, there["id"], text="Theirs")

    refused = client.put(
        f"/whiteboard/boards/{here['id']}/nodes/{mine['id']}/move",
        json={"parent_id": theirs["id"]},
    )
    assert refused.status_code == 404, refused.text


def test_a_reference_node_needs_something_real_to_point_at(client):
    board = _map(client)
    refused = client.post(
        f"/whiteboard/boards/{board['id']}/nodes",
        json={"kind": "note", "ref_id": 9999},
    )
    assert refused.status_code == 404
    assert (
        client.post(
            f"/whiteboard/boards/{board['id']}/nodes", json={"kind": "note"}
        ).status_code
        == 422
    )


def test_collapsed_and_pinned_are_stored_and_read_back(client):
    """Coggle's two: tidy on demand, and a branch you dragged stays where you
    put it. Both are per-node state on a node that already has a JSON blob,
    so neither is a column."""
    board = _map(client)
    node = _node(client, board["id"], text="Root")
    updated = client.put(
        f"/whiteboard/objects/{node['id']}",
        json={
            "kind": "topic",
            "board_id": board["id"],
            "data": {"content": "Root", "collapsed": True, "pinned": True},
        },
    )
    assert updated.status_code == 200, updated.text

    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert tree["roots"][0]["collapsed"] is True
    assert tree["roots"][0]["pinned"] is True


# --- preview ----------------------------------------------------------------


def test_a_maps_thumbnail_carries_its_edges(client):
    """The Library card. A map previewed as scattered dots reads as a board
    with no structure at all, which is precisely the thing a map has and a
    board does not."""
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], text="Child")

    row = next(b for b in client.get("/whiteboard/boards").json() if b["id"] == board["id"])
    assert len(row["preview_items"]) == 2
    assert len(row["preview_edges"]) == 1
    edge = row["preview_edges"][0]
    assert {"x1", "y1", "x2", "y2"} <= set(edge)
    assert all(0.0 <= edge[axis] <= 1.0 for axis in ("x1", "y1", "x2", "y2"))
    # The edge carries the branch it belongs to, so the thumbnail is the same
    # picture as the canvas rather than a grey diagram of one.
    assert edge["color"] in MAP_BRANCH_PALETTE


def test_an_ordinary_board_has_no_edges_to_draw(client):
    board = client.post("/whiteboard/boards", json={"name": "Plain"}).json()
    client.post(
        "/whiteboard/objects",
        json={"kind": "text", "board_id": board["id"], "data": {"content": "hi"}},
    )
    row = next(b for b in client.get("/whiteboard/boards").json() if b["id"] == board["id"])
    assert row["preview_edges"] == []


# --- duplicate --------------------------------------------------------------


def test_duplicating_a_map_keeps_its_shape(client):
    """`duplicate_board` copied objects row by row, which for a map would
    copy every node's `parent_id` verbatim: pointing the copy's whole tree
    back at the original's rows. The copy has to be re-wired to itself."""
    board = _map(client)
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], text="Child")

    copy = client.post(f"/whiteboard/boards/{board['id']}/duplicate").json()
    assert copy["type"] == "map"

    tree = client.get(f"/whiteboard/boards/{copy['id']}/tree").json()
    assert [n["text"] for n in tree["roots"]] == ["Root"]
    assert [n["text"] for n in tree["roots"][0]["children"]] == ["Child"]
    copied_ids = {n["id"] for n in tree["roots"]} | {
        n["id"] for n in tree["roots"][0]["children"]
    }
    assert not copied_ids & {root["id"]}


# --- what the notebook knows about a node (section 5 item 19) ---------------


def test_a_note_node_carries_its_category_and_age(client):
    """The perspectives colour a map by the notebook's own metadata, which is
    the thing a general mindmapper cannot do. It has to be resolved here: a
    copy on the client goes stale the moment a note is refiled, and the client
    has no way to know it did."""
    note = client.post("/entries", json={"content": "# Filed thing\n\nbody"}).json()
    board = _map(client)
    _node(client, board["id"], kind="note", ref_id=note["id"])

    node = client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"][0]
    assert node["ref_category"]
    assert node["ref_updated_at"]


def test_a_topic_carries_no_facets_at_all(client):
    """A topic stands for nothing, so it has nothing to be coloured by, and
    the payload says so by leaving the keys out rather than by sending nulls
    for every node on the board."""
    board = _map(client)
    _node(client, board["id"], text="Just a topic")

    node = client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"][0]
    assert "ref_category" not in node
    assert "ref_updated_at" not in node


def test_a_private_notes_filing_stays_behind_the_boundary(client, session):
    """Its title already does (`_reference_label` renders "Private note"), and
    its category and its edit time are facts about it too."""
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    note = client.post("/entries", json={"content": "# Secret\n\nbody"}).json()
    board = _map(client)
    _node(client, board["id"], kind="note", ref_id=note["id"])
    assert client.post(f"/entries/{note['id']}/privacy", json={"private": True}).status_code == 200

    node = client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"][0]
    assert node["text"] == "Private note"
    assert "ref_category" not in node
    vault.close()


# --- export and import ------------------------------------------------------


OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Reading list</title></head>
  <body>
    <outline text="Fiction">
      <outline text="Le Guin"/>
      <outline text="Borges"/>
    </outline>
    <outline text="History"/>
  </body>
</opml>"""


def _structure(tree_nodes):
    return [
        {"text": node["text"], "children": _structure(node["children"])}
        for node in tree_nodes
    ]


def test_opml_imports_and_exports_to_the_same_structure(client):
    """The round trip the plan asks for by name, and the reason the export
    formats are worth having at all: a map that cannot leave is a lock-in,
    and OPML is what every other mindmapper reads."""
    imported = client.post(
        "/whiteboard/boards/import", json={"format": "opml", "content": OPML}
    )
    assert imported.status_code == 201, imported.text
    board = imported.json()
    assert board["type"] == "map"
    assert board["title"] == "Reading list"

    first = _structure(client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"])
    assert [n["text"] for n in first] == ["Fiction", "History"]
    assert [n["text"] for n in first[0]["children"]] == ["Le Guin", "Borges"]

    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=opml")
    assert exported.status_code == 200, exported.text

    again = client.post(
        "/whiteboard/boards/import",
        json={"format": "opml", "content": exported.text},
    ).json()
    second = _structure(client.get(f"/whiteboard/boards/{again['id']}/tree").json()["roots"])
    assert second == first


FREEMIND = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.0.1">
  <node TEXT="Thesis">
    <node TEXT="Method">
      <node TEXT="Interviews"/>
    </node>
    <node TEXT="Results"/>
  </node>
</map>"""


def test_freemind_imports_with_its_root_as_the_maps_name(client):
    """A `.mm` file's single root node *is* its title, which is the shape
    FreeMind, Freeplane and Coggle all write: taking it as a node instead
    would leave every imported map one level deeper than it was drawn."""
    imported = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": FREEMIND}
    )
    assert imported.status_code == 201, imported.text
    board = imported.json()
    assert board["type"] == "map"
    assert board["title"] == "Thesis"

    roots = _structure(client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"])
    assert roots == [
        {"text": "Method", "children": [{"text": "Interviews", "children": []}]},
        {"text": "Results", "children": []},
    ]


def test_freemind_round_trips_through_the_export(client):
    """The point of the format: a map made here opens in FreeMind, and a map
    made there opens here, without either end losing the tree."""
    first_id = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": FREEMIND}
    ).json()["id"]
    first = _structure(client.get(f"/whiteboard/boards/{first_id}/tree").json()["roots"])

    exported = client.get(f"/whiteboard/boards/{first_id}/export?format=freemind")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-disposition"].endswith('.mm"')
    assert exported.text.lstrip().startswith("<?xml")
    assert "<map version=" in exported.text

    again = client.post(
        "/whiteboard/boards/import",
        json={"format": "freemind", "content": exported.text},
    ).json()
    assert _structure(client.get(f"/whiteboard/boards/{again['id']}/tree").json()["roots"]) == first


def test_a_multi_root_map_exports_under_one_freemind_root(client):
    """`.mm` has room for exactly one root, and a map here can have several.
    The alternative to naming a trunk after the map is a file FreeMind
    refuses to open, or one that quietly drops every root but the first."""
    board = _map(client, name="Two trunks")
    _node(client, board["id"], text="Alpha")
    _node(client, board["id"], text="Beta")

    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=freemind").text
    assert exported.count("<node") == 3
    back = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": exported}
    ).json()
    assert back["title"] == "Two trunks"
    roots = _structure(client.get(f"/whiteboard/boards/{back['id']}/tree").json()["roots"])
    assert [node["text"] for node in roots] == ["Alpha", "Beta"]


def test_a_freemind_import_with_a_doctype_is_refused(client):
    """The second XML door. It shares `_parse_xml_document` with OPML for
    exactly this reason: a security check copied per format is a check that
    is one day only in one of them."""
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        '<map version="1.0.1"><node TEXT="&lol;"/></map>'
    )
    refused = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": bomb}
    )
    assert refused.status_code == 422
    assert "FreeMind" in refused.json()["detail"]


def test_an_opml_file_sent_as_freemind_imports_as_nothing_rather_than_wrongly(client):
    """OPML's nodes are `<outline>` and FreeMind's are `<node>`: the parser
    finds nothing rather than inventing a tree. Written down because the
    client picks the format from the file's extension, and `.mm` had to be
    tested before `.xml` for that reason."""
    empty = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": OPML}
    ).json()
    assert empty["object_count"] == 0


#: Everything the node edit strip and the two radials can write on a node
#: (MINDMAP_PLAN.md §12.1 items 2 to 4), one value each, so a round-trip test
#: fails if any single one of them is dropped on the way out or on the way
#: back. Written once and used by both format tests: the two exports lost the
#: same seven fields in the same way, which is what a shared fixture says.
MAP_STYLE = {
    "bold": True,
    "italic": True,
    "font_size": 22,
    "align": "center",
    "shape": "pill",
    "icon": "lightbulb",
    "link": "https://example.org/paper",
    "edge_label": "because",
    "edge_style": "elbow",
    "edge_dashed": True,
    "color": "#4f46e5",
}


def _styled_map(client, name):
    """A two-node map whose child wears every style field there is."""
    board = _map(client, name=name)
    root = _node(client, board["id"], text="Trunk")
    child = _node(client, board["id"], parent_id=root["id"], text="Branch")
    saved = client.put(
        f"/whiteboard/objects/{child['id']}",
        json={
            "kind": child["kind"],
            "board_id": board["id"],
            "data": {**child["data"], **MAP_STYLE},
            "x": child["x"],
            "y": child["y"],
            "z": child["z"],
        },
    )
    assert saved.status_code == 200, saved.text
    return board


def _styled_child(client, board_id):
    """The styled node, wherever the tree puts it. A `.mm` file's one root is
    its title, so a map exported and imported again comes back with its trunk
    as the board's name and the styled node at the top level: the round trip
    being tested is the style's, not the depth's."""

    def find(nodes):
        for node in nodes:
            if node["text"] == "Branch":
                return node
            found = find(node["children"])
            if found is not None:
                return found
        return None

    found = find(client.get(f"/whiteboard/boards/{board_id}/tree").json()["roots"])
    assert found is not None
    return found


def test_the_tree_hands_back_what_the_strip_and_the_rings_wrote(client):
    """The style fields were readable only by fetching the raw objects, so
    every other reader of a map (the exports, the agent, a thumbnail) could
    not see them at all. They are on the node in the tree now."""
    board = _styled_map(client, "Styled")
    child = _styled_child(client, board["id"])
    assert child["color"] == "#4f46e5"
    assert child["style"] == {
        key: value for key, value in MAP_STYLE.items() if key != "color"
    }


def test_freemind_carries_a_styled_node_out_and_back(client):
    """§12.0: "a feature that cannot round-trip is not built". The strip and
    the two rings landed with none of their fields in either XML export,
    which made the one path built for taking a map somewhere else a silent
    loss of everything a person had styled."""
    board = _styled_map(client, "Styled")
    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=freemind").text

    # The four FreeMind has words of its own for, in its own words.
    assert 'LINK="https://example.org/paper"' in exported
    assert 'BOLD="true"' in exported and 'ITALIC="true"' in exported
    assert 'SIZE="22"' in exported
    assert 'STYLE="bubble"' in exported and '_shape="pill"' in exported
    assert 'STYLE="horizontal"' in exported and 'COLOR="#4f46e5"' in exported
    # And the four it does not, as private attributes rather than as invented
    # FreeMind that another reader would choke on.
    assert '_icon="lightbulb"' in exported
    assert '_edge_label="because"' in exported
    assert '_edge_dashed="true"' in exported
    assert '_align="center"' in exported

    back = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": exported}
    ).json()
    child = _styled_child(client, back["id"])
    assert child["color"] == "#4f46e5"
    assert child["style"] == {
        key: value for key, value in MAP_STYLE.items() if key != "color"
    }


def test_opml_carries_a_styled_node_out_and_back(client):
    """OPML 2.0 has one attribute that fits (`url`) and no word for the rest,
    so the rest ride as private attributes: the same device `_kind` and
    `_ref` have used here since the export was written."""
    board = _styled_map(client, "Styled")
    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=opml").text

    assert 'url="https://example.org/paper"' in exported
    # Not `type="link"`: that would say the outline *is* a link, and a reader
    # honouring it drops the children underneath.
    assert 'type="link"' not in exported
    assert '_bold="true"' in exported and '_edge_style="elbow"' in exported
    assert '_color="#4f46e5"' in exported

    back = client.post(
        "/whiteboard/boards/import", json={"format": "opml", "content": exported}
    ).json()
    child = _styled_child(client, back["id"])
    assert child["color"] == "#4f46e5"
    assert child["style"] == {
        key: value for key, value in MAP_STYLE.items() if key != "color"
    }


def test_a_topic_with_no_box_is_freeminds_own_fork_node(client):
    """The one shape FreeMind has a word for. `bubble` covers the other three
    between them, so the private `_shape` is what tells a pill from a box on
    the way back; `fork` is written as well because it is what makes the file
    look right in FreeMind, Freeplane and Coggle.

    The other direction matters more: a `.mm` written somewhere else carries
    no `_shape` at all, and `fork` is the only one of FreeMind's two styles
    that means anything here."""
    board = _map(client, name="Plain topics")
    node = _node(client, board["id"], text="On the line")
    client.put(
        f"/whiteboard/objects/{node['id']}",
        json={
            "kind": node["kind"], "board_id": board["id"],
            "data": {**node["data"], "shape": "none"},
            "x": node["x"], "y": node["y"], "z": node["z"],
        },
    )
    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=freemind").text
    assert 'STYLE="fork"' in exported

    foreign = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.0.1"><node TEXT="Root">
  <node TEXT="Bare" STYLE="fork"/><node TEXT="Boxed" STYLE="bubble"/>
</node></map>"""
    back = client.post(
        "/whiteboard/boards/import", json={"format": "freemind", "content": foreign}
    ).json()
    roots = client.get(f"/whiteboard/boards/{back['id']}/tree").json()["roots"]
    shapes = {node["text"]: node["style"].get("shape") for node in roots}
    # `bubble` is this map's own default, so it stays unset rather than
    # putting a field on every node of every imported file.
    assert shapes == {"Bare": "none", "Boxed": None}


def test_a_plain_map_exports_exactly_as_it_did_before_styles(client):
    """The other half of the round trip: an attribute per unset field would
    triple a plain map's file and say nothing, so nothing unset is written."""
    board = _map(client, name="Plain")
    _node(client, board["id"], text="Trunk")
    freemind = client.get(f"/whiteboard/boards/{board['id']}/export?format=freemind").text
    opml = client.get(f"/whiteboard/boards/{board['id']}/export?format=opml").text
    assert "<font" not in freemind and "<edge" not in freemind
    assert "_icon" not in freemind and "LINK" not in freemind and "STYLE" not in freemind
    assert "_bold" not in opml and "url=" not in opml


def test_an_imported_style_a_file_invented_is_dropped_field_by_field(client):
    """The import door validates each attribute against the same model the
    object PUT endpoint uses, and drops only what fails: a file with one bad
    attribute loses that attribute, not the nine beside it.

    The icon and the link are the two that matter. An icon name is written
    straight into a class attribute on the node, and a link is followed on
    click, so `javascript:` and a name full of punctuation are exactly what a
    file from somewhere else would carry if it were hostile."""
    hostile = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0"><head><title>Hostile</title></head><body>
<outline text="Topic" url="javascript:alert(1)" _icon="a&quot; onload=x" _bold="true"
         _font_size="9999" _edge_style="spiral" _color="red; background: url(x)"/>
</body></opml>"""
    board = client.post(
        "/whiteboard/boards/import", json={"format": "opml", "content": hostile}
    ).json()
    node = client.get(f"/whiteboard/boards/{board['id']}/tree").json()["roots"][0]
    assert node["style"] == {"bold": True}
    assert node["color"] is None


def test_markdown_exports_as_an_indented_outline_and_comes_back(client):
    board = _map(client, name="Trip")
    root = _node(client, board["id"], text="Packing")
    _node(client, board["id"], parent_id=root["id"], text="Boots")

    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=markdown")
    assert exported.status_code == 200
    assert exported.text.splitlines()[:3] == ["# Trip", "", "- Packing"]
    assert "  - Boots" in exported.text

    back = client.post(
        "/whiteboard/boards/import",
        json={"format": "markdown", "content": exported.text},
    ).json()
    assert back["title"] == "Trip"
    tree = client.get(f"/whiteboard/boards/{back['id']}/tree").json()
    assert _structure(tree["roots"]) == [
        {"text": "Packing", "children": [{"text": "Boots", "children": []}]}
    ]


def test_a_reference_node_exports_as_the_note_it_points_at(client):
    """An outline whose rows say "(note 12)" is what makes the export usable
    as a working document rather than a picture of one."""
    note = client.post("/entries", json={"content": "# Sources\n\nreading"}).json()
    board = _map(client, name="Essay")
    _node(client, board["id"], kind="note", ref_id=note["id"])

    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=markdown").text
    assert "Sources" in exported
    assert f"note {note['id']}" in exported


def test_an_import_with_a_doctype_is_refused(client):
    """The billion-laughs shape. Nothing in this app parses XML from anywhere
    else, and an import box is the one door that takes it, so the door
    refuses a document type declaration outright rather than trusting the
    parser's own defaults not to expand entities."""
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        "<opml><body><outline text=\"&lol;\"/></body></opml>"
    )
    refused = client.post(
        "/whiteboard/boards/import", json={"format": "opml", "content": bomb}
    )
    assert refused.status_code == 422


def test_an_import_that_is_not_xml_at_all_is_a_422_not_a_500(client):
    refused = client.post(
        "/whiteboard/boards/import", json={"format": "opml", "content": "not xml"}
    )
    assert refused.status_code == 422


def test_exporting_an_empty_map_is_still_a_document(client):
    board = _map(client, name="Empty")
    markdown = client.get(f"/whiteboard/boards/{board['id']}/export?format=markdown").text
    assert markdown.strip() == "# Empty"
    opml = client.get(f"/whiteboard/boards/{board['id']}/export?format=opml").text
    assert "<opml" in opml and "Empty" in opml


def test_private_note_text_never_reaches_an_export(client, session):
    """The same rule the board preview and the Connections block already
    follow: the *fact* of the connection is not secret, its content is."""
    note = client.post("/entries", json={"content": "SECRET plans"}).json()
    session.get(Entry, note["id"]).is_private = True
    session.commit()

    board = _map(client, name="Essay")
    _node(client, board["id"], kind="note", ref_id=note["id"])

    exported = client.get(f"/whiteboard/boards/{board['id']}/export?format=markdown").text
    assert "SECRET" not in exported
    assert f"note {note['id']}" in exported


def test_the_node_endpoint_stores_position_and_colour(client):
    board = _map(client)
    created = client.post(
        f"/whiteboard/boards/{board['id']}/nodes",
        json={"kind": "topic", "text": "Root", "x": 40, "y": 90, "color": "#ff0000"},
    ).json()
    assert (created["x"], created["y"]) == (40, 90)

    stored = client.get(f"/whiteboard/?board_id={board['id']}").json()["objects"]
    assert [json.loads(json.dumps(o["data"]))["color"] for o in stored] == ["#ff0000"]
    tree = client.get(f"/whiteboard/boards/{board['id']}/tree").json()
    assert tree["roots"][0]["color"] == "#ff0000"


# --- Phase 3: the map as a citizen of the app (MINDMAP_PLAN.md §5 items 12-13)


def test_a_map_a_tool_touched_becomes_a_chip_in_the_transcript():
    """MINDMAP_PLAN.md §5 item 12, the chat half.

    `_touched_items` reads `id` off a result row, and every map tool names its
    board with `board_id` instead: so before this the four map tools
    contributed nothing at all to the transcript's touched line. A turn that
    read a whole map showed a bare tool name and no way to open what it read,
    which is the failure that line exists to prevent.
    """
    from memorymap.ai import agent

    rows = agent._touched_items(
        {"board_id": 7, "board_title": "Thesis map", "node_count": 12, "outline": "…"}
    )
    assert rows == [{"kind": "map", "id": 7, "label": "Thesis map"}]


def test_a_created_map_is_named_from_title_when_there_is_no_board_title():
    """`create_mindmap` returns `title`, `read_mindmap` returns `board_title`.
    Both are the map's name, and a chip reading "map #12" for one of them
    would be the same bug wearing a different key."""
    from memorymap.ai import agent

    rows = agent._touched_items({"board_id": 12, "title": "New map", "root_id": 3})
    assert rows == [{"kind": "map", "id": 12, "label": "New map"}]


def test_a_result_with_no_board_id_still_contributes_nothing():
    from memorymap.ai import agent

    assert agent._touched_items({"ok": True}) == []


def test_a_map_and_its_notes_are_a_node_and_edges_in_the_graph(client):
    """MINDMAP_PLAN.md §5 item 13, and the §3.3 rule it settles: a map's
    *membership* is a link, a node's *position* is not."""
    note = client.post("/entries", json={"content": "Gradient descent"}).json()
    other = client.post("/entries", json={"content": "Backprop"}).json()
    board = _map(client, name="ML map")
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], kind="note", ref_id=note["id"])
    _node(client, board["id"], parent_id=root["id"], kind="note", ref_id=other["id"])
    # A topic is not a note and must never become a graph edge.
    _node(client, board["id"], parent_id=root["id"], text="Just a thought")

    data = client.get("/graph?include_maps=true").json()
    map_edges = [e for e in data["edges"] if e["kind"] == "map"]
    assert sorted(e["target"] for e in map_edges) == sorted([note["id"], other["id"]])
    assert {e["source"] for e in map_edges} == {board["id"]}

    # The board is the node it already was, marked, not duplicated.
    ids = [n["id"] for n in data["nodes"]]
    assert ids.count(board["id"]) == 1
    node = next(n for n in data["nodes"] if n["id"] == board["id"])
    assert node["type"] == "map"


def test_map_edges_are_opt_in(client):
    """Same contract as `include_entities` and `include_documents`: an existing
    caller that assumes every edge joins two notes it retrieved keeps working
    unasked."""
    note = client.post("/entries", json={"content": "Gradient descent"}).json()
    board = _map(client, name="ML map")
    _node(client, board["id"], kind="note", ref_id=note["id"])

    data = client.get("/graph").json()
    assert [e for e in data["edges"] if e["kind"] == "map"] == []
    node = next(n for n in data["nodes"] if n["id"] == board["id"])
    assert "type" not in node


def test_an_ordinary_whiteboard_is_marked_as_a_board_not_a_map(client):
    """A board of either kind is not a note the way every other graph node is,
    and one drawn as a note with a `# heading` for a label says so to nobody."""
    board = client.post("/whiteboard/boards", json={"name": "Sketches"}).json()
    data = client.get("/graph?include_maps=true").json()
    node = next(n for n in data["nodes"] if n["id"] == board["id"])
    assert node["type"] == "board"


def test_a_map_node_pointing_at_a_deleted_note_makes_no_dangling_edge(client, session):
    """d3 silently drops an edge naming a node it never received, so a
    dangling edge is an invisible failure rather than a visible one."""
    note = client.post("/entries", json={"content": "Temporary"}).json()
    board = _map(client, name="ML map")
    _node(client, board["id"], kind="note", ref_id=note["id"])
    client.delete(f"/entries/{note['id']}")
    session.expire_all()

    data = client.get("/graph?include_maps=true").json()
    ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert edge["source"] in ids and edge["target"] in ids


def test_a_document_node_on_a_map_is_not_a_graph_edge(client):
    """Only a *note* reference is an edge here: a document node's id is a
    Document id, and emitting it into a space of Entry ids would join the map
    to whichever unrelated note happened to share the number."""
    board = _map(client, name="Reading")
    document = client.post("/documents", json={"title": "Paper", "content": "x"}).json()
    _node(client, board["id"], kind="document", ref_id=document["id"])

    data = client.get("/graph?include_maps=true").json()
    assert [e for e in data["edges"] if e["kind"] == "map"] == []


# --- Phase 3: attaching a map to a chat message (MINDMAP_PLAN.md §5 item 11)


def _prepared(**body):
    """What `_prepare` hands the model, for a question with attachments.

    Called directly rather than through `POST /chat` because that endpoint
    needs a running model to answer, and this is a test about what the model
    is *given*, not about what it says back.
    """
    from memorymap.api import routes_chat
    from memorymap.core import deps

    session = deps.get_db().session()
    try:
        return routes_chat._prepare(
            session, body.pop("question", "what is on it?"), **body
        )
    finally:
        session.close()


def test_an_attached_map_reaches_the_model_as_its_outline(client):
    """The whole reason `board_ids` is its own field: a board IS an Entry, so
    `note_ids` would have carried it, and a board's content is the single
    line `# My map`, so attaching one as a note sends the model a heading and
    calls it a map."""
    board = _map(client, name="Thesis")
    root = _node(client, board["id"], text="Argument")
    _node(client, board["id"], parent_id=root["id"], text="Evidence")
    _node(client, board["id"], parent_id=root["id"], text="Counterpoint")

    prepared = _prepared(board_ids=[board["id"]])
    rows = [n for n in prepared["notes"] if n.get("category") == "Mind map"]
    assert len(rows) == 1
    content = rows[0]["content"]
    assert "Mind map: Thesis" in content
    assert "3 nodes" in content
    # Indented, one node per line, the shape the plan chose for a small model.
    assert "- Argument" in content
    assert "  - Evidence" in content
    assert "  - Counterpoint" in content
    assert rows[0]["attached"] is True


def test_a_reference_node_says_what_kind_it_is_in_the_outline(client):
    """"Which of these is a real note?" has to be answerable from the outline
    without a second call, the same reason `read_mindmap` marks them."""
    note = client.post("/entries", json={"content": "Gradient descent"}).json()
    board = _map(client, name="ML")
    root = _node(client, board["id"], text="Root")
    _node(client, board["id"], parent_id=root["id"], kind="note", ref_id=note["id"])

    content = [
        n for n in _prepared(board_ids=[board["id"]])["notes"]
        if n.get("category") == "Mind map"
    ][0]["content"]
    assert "Gradient descent [note]" in content


def test_attaching_a_map_makes_the_turn_about_the_notebook(client):
    """Same override the other three attachment kinds already apply: "what do
    you think?" with a map clipped to it is a question about that map, however
    smalltalk-shaped it reads."""
    from memorymap.ai import intent

    board = _map(client, name="Thesis")
    _node(client, board["id"], text="Argument")
    assert _prepared(question="hey", board_ids=[board["id"]])["intent"] == intent.NOTES


def test_a_private_board_is_never_attached(client, session):
    """Attaching is a deliberate act, so this is not the guard that matters, 
    but `read_mindmap` refuses a private board on the AI's behalf, and one
    reaching the model through a different door would make that decorative."""
    board = _map(client, name="Secret")
    _node(client, board["id"], text="SECRET plan")
    session.get(Entry, board["id"]).is_private = True
    session.commit()

    prepared = _prepared(board_ids=[board["id"]])
    assert [n for n in prepared["notes"] if n.get("category") == "Mind map"] == []
    assert "SECRET" not in json.dumps(prepared["notes"])


def test_an_empty_map_says_it_is_empty_rather_than_nothing(client):
    """A chip in the transcript corresponding to nothing at all is the failure
    `document_ids` already shipped once (routes_chat.py says so by name)."""
    board = _map(client, name="Blank")
    content = [
        n for n in _prepared(board_ids=[board["id"]])["notes"]
        if n.get("category") == "Mind map"
    ][0]["content"]
    assert "(empty: no nodes yet)" in content


def test_a_long_outline_is_truncated_to_the_budget(client):
    """Every character here is resent on every round of the turn."""
    from memorymap.api import routes_chat

    board = _map(client, name="Huge")
    root = _node(client, board["id"], text="Root")
    for i in range(400):
        _node(client, board["id"], parent_id=root["id"], text=f"Node number {i} with words")

    content = [
        n for n in _prepared(board_ids=[board["id"]])["notes"]
        if n.get("category") == "Mind map"
    ][0]["content"]
    assert "[…truncated]" in content
    assert len(content) < routes_chat.ATTACHED_MAP_CHARS + 400


def test_the_chat_request_caps_attached_maps_at_four(client):
    """Matching `document_ids` and `file_ids`, and the composer's own ceiling."""
    refused = client.post(
        "/chat", json={"question": "hi", "board_ids": [1, 2, 3, 4, 5]}
    )
    assert refused.status_code == 422


def test_a_board_id_that_is_not_a_board_contributes_nothing(client):
    """A deleted map, or an id typed by hand. Skipped in silence rather than
    refused: the message is still worth answering."""
    prepared = _prepared(board_ids=[99999])
    assert [n for n in prepared["notes"] if n.get("category") == "Mind map"] == []


# --- exports that cannot be made to recurse ---------------------------------


def _deep_chain(session, board_id: int, depth: int) -> int:
    """One branch, `depth` nodes long, written straight to the database.

    Through the API this would be `depth` requests and about as many seconds;
    what the test is about is the export, not the insert. `parent_id` is a
    plain integer column (see its own comment), so this builds exactly the
    shape a person builds with the Tab key, only faster.
    """
    parent_id = None
    for level in range(depth):
        node = WhiteboardObject(
            kind="topic",
            data=json.dumps({"content": f"Level {level}"}),
            board_id=board_id,
            x=float(level * 40),
            y=0.0,
            width=200.0,
            height=56.0,
            parent_id=parent_id,
        )
        session.add(node)
        session.flush()
        parent_id = node.id
    session.commit()
    return depth


def test_a_map_deeper_than_pythons_recursion_headroom_still_exports(client, session):
    """**The two XML exports used to recurse.** Nothing caps how deep a map
    built by hand can go: `MAX_IMPORT_DEPTH` caps an import and the Tab key is
    not an import. A branch longer than Python's own recursion limit therefore
    left `_export_opml` and `_export_freemind` raising `RecursionError`, which
    reaches the person pressing Download as a 500 on a map that opens fine.

    1,200 rather than a round thousand: the default limit is 1,000 and each
    level of the old walk took more than one frame, so a number just over it
    would have passed by luck on some builds.
    """
    board = _map(client, name="Deep map")
    depth = _deep_chain(session, board["id"], 1200)

    for fmt in ("opml", "freemind", "markdown"):
        exported = client.get(f"/whiteboard/boards/{board['id']}/export?format={fmt}")
        assert exported.status_code == 200, f"{fmt}: {exported.text[:200]}"
        # Every level is in the file: the nesting is clamped past
        # MAX_MAP_DEPTH, the content is not.
        assert "Level 0" in exported.text
        assert f"Level {depth - 1}" in exported.text
        assert exported.text.count("Level ") == depth


def test_a_ring_in_the_tree_does_not_hang_an_export(client, session):
    """`_build_tree` re-roots the lowest id of an unreachable ring rather than
    dropping its rows, so a ring reaches the exporters as a root whose
    descendants lead back to it. The recursive versions never returned, and
    the Markdown walk, which was already iterative, had no seen set and
    appended rows until it ran out of memory.

    A ring is not hypothetical: `parent_id` is a plain integer, so any write
    that sets it without the move endpoint's `_is_descendant` check can make
    one, and a restored backup or a hand-edited database certainly can.
    """
    board = _map(client, name="Ring map")
    first = _node(client, board["id"], text="A")
    second = _node(client, board["id"], parent_id=first["id"], text="B")
    # Close the ring behind the API's back: the move endpoint refuses this,
    # which is the point. It is the shape that arrives from somewhere else.
    session.get(WhiteboardObject, first["id"]).parent_id = second["id"]
    session.commit()

    for fmt in ("opml", "freemind", "markdown"):
        exported = client.get(f"/whiteboard/boards/{board['id']}/export?format={fmt}")
        assert exported.status_code == 200, f"{fmt}: {exported.text[:200]}"
        # Each node once, not once per lap.
        laps_a = exported.text.count(">A<") + exported.text.count('"A"') + exported.text.count("- A")
        laps_b = exported.text.count(">B<") + exported.text.count('"B"') + exported.text.count("- B")
        assert laps_a == 1, f"{fmt}: node A written {laps_a} times"
        assert laps_b == 1, f"{fmt}: node B written {laps_b} times"
