"""The agent's whiteboard tools (ROADMAP item 11's AI+whiteboard piece):
read_whiteboard, search_whiteboard, add_whiteboard_card, add_whiteboard_link.

Nothing under `ai/` mentioned the whiteboard at all before these existed, 
this file is the first coverage for that gap.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import tools
from memorymap.core.database import Entry, WhiteboardNode, WhiteboardObject, WhiteboardSketch


def _note(session, content="a note"):
    entry = Entry(content=content)
    session.add(entry)
    session.commit()
    return entry


def test_read_whiteboard_lists_cards_links_and_text_boxes(session):
    a = _note(session, "Kickoff plan")
    b = _note(session, "Budget draft")
    node_a = WhiteboardNode(entry_id=a.id, x=0, y=0)
    node_b = WhiteboardNode(entry_id=b.id, x=100, y=100)
    session.add_all([node_a, node_b])
    session.commit()
    link = WhiteboardSketch(
        data=json.dumps({"type": "link-straight", "sourceId": node_a.id, "targetId": node_b.id, "color": "#fff"}),
    )
    text_obj = WhiteboardObject(kind="text", data=json.dumps({"content": "milestone", "color": "#000", "font_size": 14}))
    session.add_all([link, text_obj])
    session.commit()

    result = tools.TOOLS["read_whiteboard"].handler(session, {})
    assert result["board_id"] is None
    assert {c["note_id"] for c in result["cards"]} == {a.id, b.id}
    assert result["links"] == [{"from_card_id": node_a.id, "to_card_id": node_b.id}]
    assert result["text_boxes"] == [{"object_id": text_obj.id, "text": "milestone"}]


def test_read_whiteboard_default_board_is_not_confused_with_an_absent_one(session):
    """`board_id IS NULL` is a board, not "no board", the same trap this
    project's own `_board_filter` in routes_whiteboard.py already guards
    against; the AI tool has its own copy of the filter and had to get it
    right independently."""
    a = _note(session)
    session.add(WhiteboardNode(entry_id=a.id, board_id=None, x=0, y=0))
    session.commit()

    result = tools.TOOLS["read_whiteboard"].handler(session, {"board_id": None})
    assert len(result["cards"]) == 1


def test_search_whiteboard_finds_a_card_by_note_content_and_says_which_board(session):
    board_note = _note(session, "Project board")
    a = _note(session, "The quarterly roadmap draft")
    session.add(WhiteboardNode(entry_id=a.id, board_id=board_note.id, x=0, y=0))
    session.commit()

    result = tools.TOOLS["search_whiteboard"].handler(session, {"query": "roadmap"})
    assert result["total_matching"] == 1
    assert result["matches"][0]["board_id"] == board_note.id
    assert result["matches"][0]["note_id"] == a.id


def test_search_whiteboard_requires_a_query(session):
    with pytest.raises(tools.ToolError):
        tools.TOOLS["search_whiteboard"].handler(session, {"query": "  "})


def test_read_whiteboard_does_not_expose_a_card_whose_note_turned_private(session):
    """`add_whiteboard_card` refuses a private note going in (the test below)
    - but a note can be marked private *after* it is already a card, and
    `WhiteboardNode` carries no privacy flag of its own to catch that later.
    `entry.content` is ciphertext at rest for a private note; `read_whiteboard`
    used to hand that straight back as the card's "preview", which becomes
    part of the agent's own context: the same leak `_require_note` exists to
    close on every other read."""
    a = _note(session, "Kickoff plan")
    node = WhiteboardNode(entry_id=a.id, x=0, y=0)
    session.add(node)
    session.commit()
    a.is_private = True
    a.content = "mmenc1:not-real-ciphertext"
    session.commit()

    result = tools.TOOLS["read_whiteboard"].handler(session, {})
    assert len(result["cards"]) == 1
    assert "not-real-ciphertext" not in result["cards"][0]["preview"]


def test_search_whiteboard_does_not_match_a_card_whose_note_turned_private(session):
    a = _note(session, "The quarterly roadmap draft")
    session.add(WhiteboardNode(entry_id=a.id, x=0, y=0))
    session.commit()
    a.is_private = True
    a.content = "mmenc1:roadmap-ciphertext"
    session.commit()

    result = tools.TOOLS["search_whiteboard"].handler(session, {"query": "roadmap"})
    assert result["total_matching"] == 0


def test_add_whiteboard_card_refuses_a_private_note(session):
    """The exact regression class CLAUDE.md's own review checklist names: a
    write tool that skips `_require_note` silently loses the one guard that
    refuses a private note. This tool must not be that fourth instance."""
    private = _note(session, "secret")
    private.is_private = True
    session.commit()

    with pytest.raises(tools.ToolError):
        tools.TOOLS["add_whiteboard_card"].handler(session, {"note_id": private.id})


def test_add_whiteboard_card_is_idempotent_on_the_same_board(session):
    """Calling it twice for the same note/board must not create two cards, 
    the agent retrying (or a user asking twice) shouldn't duplicate a card
    the way it would duplicate a note."""
    a = _note(session)
    first = tools.TOOLS["add_whiteboard_card"].handler(session, {"note_id": a.id, "x": 5, "y": 5})
    second = tools.TOOLS["add_whiteboard_card"].handler(session, {"note_id": a.id, "x": 999, "y": 999})
    assert first["card_id"] == second["card_id"]
    assert second["already_there"] is True
    assert session.query(WhiteboardNode).count() == 1


def test_add_whiteboard_link_connects_two_real_cards(session):
    a, b = _note(session, "A"), _note(session, "B")
    node_a = WhiteboardNode(entry_id=a.id, x=0, y=0)
    node_b = WhiteboardNode(entry_id=b.id, x=0, y=0)
    session.add_all([node_a, node_b])
    session.commit()

    result = tools.TOOLS["add_whiteboard_link"].handler(
        session, {"from_card_id": node_a.id, "to_card_id": node_b.id}
    )
    sketch = session.get(WhiteboardSketch, result["link_id"])
    data = json.loads(sketch.data)
    assert data["type"] == "link-straight"
    assert data["sourceId"] == node_a.id
    assert data["targetId"] == node_b.id


def test_add_whiteboard_link_rejects_an_unknown_card(session):
    with pytest.raises(tools.ToolError):
        tools.TOOLS["add_whiteboard_link"].handler(session, {"from_card_id": 999, "to_card_id": 998})


def test_add_whiteboard_link_rejects_a_self_link(session):
    a = _note(session, "A")
    node_a = WhiteboardNode(entry_id=a.id, x=0, y=0)
    session.add(node_a)
    session.commit()

    with pytest.raises(tools.ToolError):
        tools.TOOLS["add_whiteboard_link"].handler(
            session, {"from_card_id": node_a.id, "to_card_id": node_a.id}
        )


def test_add_whiteboard_link_rejects_cards_on_different_boards(session):
    """Without this, a link between cards on two different boards saved as a
    sketch on the source's board only: the target node is never in the
    target board's own fetched state, so the link renders with a dangling
    endpoint on both boards it could conceivably show up on."""
    a, b = _note(session, "A"), _note(session, "B")
    board = _note(session, "# A board")
    node_a = WhiteboardNode(entry_id=a.id, x=0, y=0, board_id=None)
    node_b = WhiteboardNode(entry_id=b.id, x=0, y=0, board_id=board.id)
    session.add_all([node_a, node_b])
    session.commit()

    with pytest.raises(tools.ToolError):
        tools.TOOLS["add_whiteboard_link"].handler(
            session, {"from_card_id": node_a.id, "to_card_id": node_b.id}
        )


def test_whiteboard_write_tools_are_in_the_write_tools_set(session):
    """The agent's "you claimed you saved it but never called a write tool"
    safety net keys off this set, missing from it means a real card/link
    creation would read as a hallucinated claim."""
    assert "add_whiteboard_card" in tools.WRITE_TOOLS
    assert "add_whiteboard_link" in tools.WRITE_TOOLS
    assert "generate_diagram" in tools.WRITE_TOOLS


# --- generate_diagram (BACKLOG.md §29d) -------------------------------------
#
# add_whiteboard_card/add_whiteboard_link already let the model build a
# diagram one call at a time, but x/y are numbers it has to invent itself, 
# exactly the bookkeeping a small tool-calling model gets wrong across many
# chained calls. This tool takes only structure (a title or an existing
# note, and which other node is its parent) and does every placement
# server-side in one round trip.


def test_generate_diagram_creates_notes_cards_and_links_for_a_small_tree(session):
    result = tools.TOOLS["generate_diagram"].handler(
        session,
        {
            "nodes": [
                {"ref": "root", "title": "Project X"},
                {"ref": "a", "title": "Design", "parent_ref": "root"},
                {"ref": "b", "title": "Build", "parent_ref": "root"},
                {"ref": "c", "title": "Test", "parent_ref": "b"},
            ]
        },
    )
    assert result["links_created"] == 3
    assert len(result["cards"]) == 4
    assert session.query(WhiteboardNode).count() == 4
    assert session.query(WhiteboardSketch).count() == 3
    titles = {c["ref"]: session.get(Entry, c["note_id"]).content for c in result["cards"]}
    assert titles == {"root": "Project X", "a": "Design", "b": "Build", "c": "Test"}
    # Positions actually differ: every node landing at (0, 0) would mean
    # the layout math silently did nothing.
    positions = {c["ref"]: (c["x"], c["y"]) for c in result["cards"]}
    assert len(set(positions.values())) == 4


def test_generate_diagram_can_reuse_an_existing_note_as_a_node(session):
    existing = _note(session, "already a note")
    result = tools.TOOLS["generate_diagram"].handler(
        session,
        {
            "nodes": [
                {"ref": "root", "note_id": existing.id},
                {"ref": "child", "title": "New idea", "parent_ref": "root"},
            ]
        },
    )
    root_card = next(c for c in result["cards"] if c["ref"] == "root")
    assert root_card["note_id"] == existing.id
    # Only one new note was actually created (the child): the root reused
    # the existing entry rather than duplicating it.
    assert session.query(Entry).count() == 2


def test_generate_diagram_refuses_a_private_existing_note(session):
    private = _note(session, "secret")
    private.is_private = True
    session.commit()
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(
            session, {"nodes": [{"ref": "root", "note_id": private.id}]}
        )


def test_generate_diagram_requires_exactly_one_root(session):
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(
            session,
            {"nodes": [{"ref": "a", "title": "A"}, {"ref": "b", "title": "B"}]},
        )
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(
            session,
            {"nodes": [{"ref": "a", "title": "A", "parent_ref": "b"}, {"ref": "b", "title": "B", "parent_ref": "a"}]},
        )


def test_generate_diagram_rejects_an_unknown_parent_ref(session):
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(
            session,
            {"nodes": [{"ref": "root", "title": "Root"}, {"ref": "a", "title": "A", "parent_ref": "nope"}]},
        )


def test_generate_diagram_rejects_a_node_with_both_title_and_note_id(session):
    existing = _note(session)
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(
            session,
            {"nodes": [{"ref": "root", "title": "Root", "note_id": existing.id}]},
        )


def test_generate_diagram_rejects_more_nodes_than_the_cap(session):
    nodes = [{"ref": "root", "title": "Root"}] + [
        {"ref": f"n{i}", "title": f"Node {i}", "parent_ref": "root"}
        for i in range(tools.MAX_DIAGRAM_NODES)
    ]
    with pytest.raises(tools.ToolError):
        tools.TOOLS["generate_diagram"].handler(session, {"nodes": nodes})


def test_generate_diagram_radial_layout_also_places_every_node(session):
    result = tools.TOOLS["generate_diagram"].handler(
        session,
        {
            "layout": "radial",
            "nodes": [
                {"ref": "root", "title": "Root"},
                {"ref": "a", "title": "A", "parent_ref": "root"},
                {"ref": "b", "title": "B", "parent_ref": "root"},
            ],
        },
    )
    assert len(result["cards"]) == 3
    # The root stays at the origin; the two children ring around it.
    root = next(c for c in result["cards"] if c["ref"] == "root")
    assert (root["x"], root["y"]) == (0.0, 0.0)


def test_generate_diagram_is_idempotent_with_add_whiteboard_card_on_a_shared_board(session):
    """A card generate_diagram places for an existing note must be found and
    reused by the same one-card-per-note-per-board rule add_whiteboard_card
    already enforces: not a second, competing card."""
    existing = _note(session, "shared")
    first = tools.TOOLS["add_whiteboard_card"].handler(session, {"note_id": existing.id, "x": 1, "y": 1})
    result = tools.TOOLS["generate_diagram"].handler(
        session, {"nodes": [{"ref": "root", "note_id": existing.id}]}
    )
    assert result["cards"][0]["card_id"] == first["card_id"]
    assert session.query(WhiteboardNode).count() == 1
