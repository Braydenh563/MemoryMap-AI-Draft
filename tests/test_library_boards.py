"""A board and a mind map are not notes in the Library.

Reported on 2026-09-09 with two screenshots: "in the all library subtab, the
mindmap I made called bubble tea shows as a note", while Boards and maps drew
the same thing correctly as a map with 3 nodes.

It is not a classification slip in one view, it is the storage model showing
through: MINDMAP_PLAN §4 chose option B, so a board is an `Entry` carrying
`is_board`, and a mind map is a board whose `board_settings` say
`type: "map"`. The Library's own feed selected entries and called every one
of them a note, which is true of the row and false of the thing.
"""

from __future__ import annotations

import json

from memorymap.core.database import Entry


def _kinds(client):
    body = client.get("/library").json()
    return {item["title"]: item["kind"] for item in body["items"]}


def test_a_plain_note_is_still_a_note(client):
    client.post("/entries", json={"content": "A plain thought"})
    assert _kinds(client)["A plain thought"] == "note"


def test_a_board_is_a_board(client, session):
    made = client.post("/entries", json={"content": "Default board"}).json()
    entry = session.get(Entry, made["id"])
    entry.is_board = True
    session.commit()
    assert _kinds(client)["Default board"] == "board"


def test_a_mind_map_is_a_map(client, session):
    made = client.post("/entries", json={"content": "bubble tea"}).json()
    entry = session.get(Entry, made["id"])
    entry.is_board = True
    entry.board_settings = json.dumps({"type": "map"})
    session.commit()
    assert _kinds(client)["bubble tea"] == "map"


def test_the_counts_name_the_new_kinds(client, session):
    made = client.post("/entries", json={"content": "bubble tea"}).json()
    entry = session.get(Entry, made["id"])
    entry.is_board = True
    entry.board_settings = json.dumps({"type": "map"})
    session.commit()
    counts = client.get("/library").json()["counts"]
    assert counts.get("map") == 1
    assert counts.get("note", 0) == 0
