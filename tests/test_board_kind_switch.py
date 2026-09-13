"""A board can say which kind it is, and change its mind.

Reported: *"when I press the boards dropdown to change boards, I cant tell
which one is a whiteboard and which one is a mindmap"*.

The picker has grouped the two kinds under `<optgroup>` since MINDMAP_PLAN §5
item 12, and it groups only when both kinds are present, because a lone
"Whiteboards" heading above every row answers a question nobody asked. So the
grouping disappears exactly when every board claims to be the same kind, which
is what the report looks like from the inside.

`_board_settings` defaults a board with no stored settings to "board". That is
the right default (it is what every board was before maps existed) and the
wrong answer for a board somebody has been using as a map ever since, and
until now nothing in the app could say otherwise: `rename_board` has taken a
`type` from the beginning, its own docstring says "also where a board becomes
a map and back", and no control ever sent one.

Driven in Chromium on a real map board: the View menu's switch read "Turn into
a whiteboard", clicking it made `wbIsMap()` false and flipped the label to
"Turn into a mind map", and the picker collapsed from
`[Mind maps] ... [Whiteboards] ...` to two ungrouped rows, which is the
reported symptom reproduced on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHITEBOARD_JS = (ROOT / "frontend" / "whiteboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def _make_board(client, name):
    return client.post("/whiteboard/boards", json={"name": name}).json()


def test_a_board_starts_as_a_whiteboard_and_can_become_a_map(client):
    board = _make_board(client, "A board that grew up")
    assert board["type"] == "board"

    changed = client.put(f"/whiteboard/boards/{board['id']}", json={"type": "map"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["type"] == "map"

    listed = {row["id"]: row for row in client.get("/whiteboard/boards").json()}
    assert listed[board["id"]]["type"] == "map", "the change did not survive the list read"


def test_it_goes_back(client):
    """Both directions, because the control is one button whose label flips."""
    board = _make_board(client, "Undecided")
    client.put(f"/whiteboard/boards/{board['id']}", json={"type": "map"})
    client.put(f"/whiteboard/boards/{board['id']}", json={"type": "board"})
    listed = {row["id"]: row for row in client.get("/whiteboard/boards").json()}
    assert listed[board["id"]]["type"] == "board"


def test_a_nonsense_kind_leaves_the_board_alone(client):
    """The column is JSON in a text field and this route is reachable by
    anything holding a token: an unknown value degrades to the default rather
    than storing itself."""
    board = _make_board(client, "Not a spreadsheet")
    client.put(f"/whiteboard/boards/{board['id']}", json={"type": "map"})
    client.put(f"/whiteboard/boards/{board['id']}", json={"type": "spreadsheet"})
    listed = {row["id"]: row for row in client.get("/whiteboard/boards").json()}
    assert listed[board["id"]]["type"] in {"board", "map"}


def test_the_control_exists_and_says_what_it_will_do():
    """A button whose label is the current state reads as a toggle that is
    already on. This one changes the board, so it names the change."""
    assert 'id="wb-board-kind"' in INDEX_HTML, "the kind switch is gone from the View menu"
    assert 'id="wb-board-kind-label"' in INDEX_HTML
    assert "Turn into a whiteboard" in WHITEBOARD_JS
    assert "Turn into a mind map" in WHITEBOARD_JS
    handler = re.search(
        r'getElementById\("wb-board-kind"\)\?\.addEventListener\("click".*?\n  \}\);',
        WHITEBOARD_JS,
        re.S,
    )
    assert handler, "the kind switch has no click handler"
    assert '"PUT"' in handler.group(0), "the switch no longer sends the change to the server"
    assert "openWhiteboardBoard" in handler.group(0), (
        "the board is not reopened after the switch: the two kinds draw "
        "different chrome, tools and renderer, and a half-switched board is "
        "the shape of bug this file has had before"
    )


def test_the_picker_still_groups_only_when_both_kinds_are_there():
    """The other half of the decision, so a later change cannot quietly make
    every board list carry a heading that says nothing."""
    assert "mapsPresent && boardsPresent" in WHITEBOARD_JS, (
        "the board picker no longer gates its optgroups on both kinds being "
        "present, or the check has been renamed"
    )
