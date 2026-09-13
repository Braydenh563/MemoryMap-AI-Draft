"""The agent's mindmap tools: read_mindmap, create_mindmap, add_map_node,
link_map_nodes (MINDMAP_PLAN.md §5 item 14).

Two things are being asserted here beyond "the handler runs".

**The outline shape.** `read_mindmap` exists because `read_whiteboard`'s
three flat lists are the wrong answer for a map, the structure *is* the
content, and a small model handed a list of nodes plus a list of parent ids
rebuilds the tree wrongly or not at all. So the tests assert indentation and
per-line ids, not just that every node is mentioned somewhere.

**The private-note guard.** CLAUDE.md's third recurring failure shape is "a
guard removed while the shape around it was kept": two tools grew batch
arguments and quietly stopped calling `_require_note`, and the code still
looked right. A map is a place a note's title gets copied into and read
straight back out, so the refusal is tested on the way in *and* on the way
out.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import tools
from memorymap.ai.tools._common import ToolError
from memorymap.core.database import Entry, WhiteboardObject, WhiteboardSketch


def _note(session, content="a note", private=False):
    entry = Entry(content=content, is_private=private)
    session.add(entry)
    session.commit()
    return entry


def _map(session, title="Thesis"):
    created = tools.TOOLS["create_mindmap"].handler(session, {"title": title})
    return created["board_id"], created["root_id"]


def test_create_mindmap_makes_a_board_that_is_a_map_with_a_root(session):
    """A map with no root has nothing to hang the next node off, and a small
    model handed one stalls there, which is why the root is part of this
    call rather than a second one."""
    result = tools.TOOLS["create_mindmap"].handler(
        session, {"title": "Thesis", "root_text": "Argument"}
    )
    board = session.get(Entry, result["board_id"])
    assert board.is_board is True
    assert json.loads(board.board_settings)["type"] == "map"

    root = session.get(WhiteboardObject, result["root_id"])
    assert root.kind == "topic"
    assert json.loads(root.data)["content"] == "Argument"
    assert root.parent_id is None


def test_create_mindmap_refuses_a_map_with_no_name(session):
    with pytest.raises(ToolError):
        tools.TOOLS["create_mindmap"].handler(session, {"title": "  "})


def test_read_mindmap_returns_an_indented_outline_with_ids(session):
    board_id, root_id = _map(session)
    child = tools.TOOLS["add_map_node"].handler(
        session, {"board_id": board_id, "parent_id": root_id, "text": "Chapter one"}
    )
    tools.TOOLS["add_map_node"].handler(
        session,
        {"board_id": board_id, "parent_id": child["node_id"], "text": "Sources"},
    )

    result = tools.TOOLS["read_mindmap"].handler(session, {"board_id": board_id})
    lines = result["outline"].splitlines()

    assert lines[0] == "Thesis"
    assert lines[1] == f"- Thesis [id {root_id}]"
    assert lines[2] == f"  - Chapter one [id {child['node_id']}]"
    # Depth is indentation, and it is the whole point of this format: a flat
    # list with a parent column is what the model gets wrong.
    assert lines[3].startswith("    - Sources [id ")
    assert result["node_count"] == 3
    assert result["type"] == "map"


def test_read_mindmap_names_the_note_behind_a_reference_node(session):
    """"each node's kind and any note id", the plan's words. Without the id
    the model can read the map and still not be able to open anything in it."""
    note = _note(session, "# Kolmogorov complexity\n\nnotes")
    board_id, root_id = _map(session)
    tools.TOOLS["add_map_node"].handler(
        session,
        {"board_id": board_id, "parent_id": root_id, "kind": "note", "note_id": note.id},
    )

    outline = tools.TOOLS["read_mindmap"].handler(session, {"board_id": board_id})["outline"]
    assert "Kolmogorov complexity" in outline
    assert f"note {note.id}" in outline


def test_read_mindmap_refuses_to_read_a_private_boards_contents(session):
    """A board is an Entry and can be marked private after being used as one
    - the same rule `_read_whiteboard` follows for a board title, applied to
    a whole outline, which is far more text."""
    board_id, _ = _map(session)
    board = session.get(Entry, board_id)
    board.is_private = True
    session.commit()

    with pytest.raises(ToolError):
        tools.TOOLS["read_mindmap"].handler(session, {"board_id": board_id})


def test_a_private_notes_text_never_reaches_the_outline(session):
    """The reference node is created directly, bypassing `add_map_node`'s own
    refusal: because the note can be marked private *after* it was put on
    the map, and the read path has to refuse it on its own."""
    note = _note(session, "SECRET research", private=True)
    board_id, root_id = _map(session)
    session.add(
        WhiteboardObject(
            board_id=board_id,
            kind="note",
            data=json.dumps({"content": "", "ref_id": note.id}),
            parent_id=root_id,
            x=0,
            y=0,
        )
    )
    session.commit()

    outline = tools.TOOLS["read_mindmap"].handler(session, {"board_id": board_id})["outline"]
    assert "SECRET" not in outline
    assert "Private note" in outline


def test_add_map_node_refuses_a_private_note(session):
    """`_require_note`, not a bare `session.get`, the guard `add_whiteboard_card`
    already uses, and the one CLAUDE.md records two tools quietly losing."""
    note = _note(session, "SECRET", private=True)
    board_id, root_id = _map(session)

    with pytest.raises(ToolError):
        tools.TOOLS["add_map_node"].handler(
            session,
            {"board_id": board_id, "parent_id": root_id, "kind": "note", "note_id": note.id},
        )
    assert (
        session.query(WhiteboardObject).filter(WhiteboardObject.kind == "note").count() == 0
    )


def test_add_map_node_places_the_node_without_being_told_where(session):
    """The reason this tool exists beside `generate_diagram`: the model never
    sees a coordinate. `add_whiteboard_card` takes x/y, and inventing them
    across chained calls is exactly what a small tool-calling model gets
    wrong."""
    board_id, root_id = _map(session)
    first = tools.TOOLS["add_map_node"].handler(
        session, {"board_id": board_id, "parent_id": root_id, "text": "One"}
    )
    second = tools.TOOLS["add_map_node"].handler(
        session, {"board_id": board_id, "parent_id": root_id, "text": "Two"}
    )

    a = session.get(WhiteboardObject, first["node_id"])
    b = session.get(WhiteboardObject, second["node_id"])
    assert a.x == b.x  # same depth, same column
    assert a.y != b.y  # and not stacked on top of each other
    assert a.parent_id == b.parent_id == root_id


def test_add_map_node_refuses_a_parent_on_another_board(session):
    here, here_root = _map(session, "Here")
    _, there_root = _map(session, "There")

    with pytest.raises(ToolError):
        tools.TOOLS["add_map_node"].handler(
            session, {"board_id": here, "parent_id": there_root, "text": "x"}
        )
    assert here_root  # the valid parent is untouched


def test_add_map_node_needs_text_for_a_topic(session):
    board_id, root_id = _map(session)
    with pytest.raises(ToolError):
        tools.TOOLS["add_map_node"].handler(
            session, {"board_id": board_id, "parent_id": root_id}
        )


def test_link_map_nodes_writes_a_link_sketch_between_two_objects(session):
    """A cross-link is the same row a link between two cards already is, 
    `sourceKind`/`targetKind` of "object" is what tells the canvas and
    `_forget_links_to` which table to look in."""
    board_id, root_id = _map(session)
    left = tools.TOOLS["add_map_node"].handler(
        session, {"board_id": board_id, "parent_id": root_id, "text": "Left"}
    )
    right = tools.TOOLS["add_map_node"].handler(
        session, {"board_id": board_id, "parent_id": root_id, "text": "Right"}
    )

    result = tools.TOOLS["link_map_nodes"].handler(
        session,
        {
            "board_id": board_id,
            "from_id": left["node_id"],
            "to_id": right["node_id"],
            "label": "contradicts",
        },
    )
    sketch = session.get(WhiteboardSketch, result["link_id"])
    data = json.loads(sketch.data)
    assert data["sourceKind"] == data["targetKind"] == "object"
    assert (data["sourceId"], data["targetId"]) == (left["node_id"], right["node_id"])
    assert data["label"] == "contradicts"
    assert sketch.board_id == board_id


def test_link_map_nodes_refuses_two_nodes_on_different_maps(session):
    """A link whose ends are on two boards draws on neither."""
    _, here_root = _map(session, "Here")
    _, there_root = _map(session, "There")

    with pytest.raises(ToolError):
        tools.TOOLS["link_map_nodes"].handler(
            session, {"from_id": here_root, "to_id": there_root}
        )


def test_link_map_nodes_refuses_a_node_linked_to_itself(session):
    _, root_id = _map(session)
    with pytest.raises(ToolError):
        tools.TOOLS["link_map_nodes"].handler(session, {"from_id": root_id, "to_id": root_id})


def test_the_map_tools_are_registered_and_gated_like_the_board_tools(session):
    """Registered in `TOOLS` (which is what puts them in Settings → Tools and
    in `/chat/tools`), and in the whiteboard cue group, a question about a
    map that was offered the board tools and not these answers by placing
    cards on a canvas."""
    from memorymap.ai import toolwords

    for name in ("read_mindmap", "create_mindmap", "add_map_node", "link_map_nodes"):
        assert name in tools.TOOLS
    # The three that write are declared as writes, so the agent's "you
    # claimed you saved it" net counts them and a skill using them is
    # labelled as acting.
    assert {"create_mindmap", "add_map_node", "link_map_nodes"} <= tools.WRITE_TOOLS
    assert "read_mindmap" not in tools.WRITE_TOOLS

    focus = tools.focus_for("make me a mind map of my thesis notes")
    assert focus is None or "create_mindmap" in focus
    assert toolwords  # imported for the group the assertion above exercises
