"""Tool results as typed cards (PLAN.md §4, item A1).

The acceptance PLAN.md writes down is *"grep finds no tool returning a bare
string"*, and that was already true when this was built, every one of the
registry's executors returns a dict. What was not true is the sentence after
it: *"the chat renders a card per kind (note, document, file, board,
reminder)"*. Two of those five had cards (`agent._touched_items`); the other
three had nothing at all, so a `search_files` result reached the reader as
JSON behind a disclosure and a reminder the agent set reached them as a
sentence.

`ai/cards.py` is that projection, and these tests pin the three properties
that make it trustworthy rather than decorative:

- **Coverage is enforced, not hoped for.** Every registered tool has an entry,
  empty included, so a tool added later cannot silently render as a blob.
- **A card names the thing the tool actually touched**, read from the result
  and never from the arguments, the same rule `_touched_items` follows.
- **Ids are not interchangeable.** A document is not a note, and an upload is
  not an attachment: id 1 is a different object in each, and a card that lost
  the distinction would open the wrong one.
"""

from __future__ import annotations

import json

from memorymap.ai import cards, tools


# --- coverage ----------------------------------------------------------------


def test_every_registered_tool_has_a_decision():
    """The enforceable version of "every tool returns {kind, items}".

    A tool whose result names nothing openable maps to `()`, which is a
    decision; a tool missing from the table is an oversight, and this is what
    turns the second into a failing test rather than a JSON blob in the chat.
    """
    missing = sorted(set(tools.TOOLS) - set(cards.PROJECTIONS))
    assert not missing, (
        f"{missing} have no entry in cards.PROJECTIONS, add one, or map them "
        "to () with a comment saying what they return instead."
    )


def test_the_table_has_no_tools_that_no_longer_exist():
    """The other direction: a renamed tool leaves a dead row behind, and a
    dead row is a card that can never render."""
    stale = sorted(set(cards.PROJECTIONS) - set(tools.TOOLS))
    assert not stale, f"{stale} are in cards.PROJECTIONS but not in the registry"


def test_every_projection_names_a_kind_the_front_end_draws():
    for name, wheres in cards.PROJECTIONS.items():
        for where in wheres:
            assert where.kind in cards.KINDS, f"{name} projects unknown kind {where.kind}"


# --- notes and documents ------------------------------------------------------


def test_a_search_result_becomes_one_note_card_per_hit():
    out = cards.result_cards(
        "search_notes",
        {
            "found": 2,
            "notes": [
                {"id": 3, "content": "Bought milk and eggs on the way home"},
                {"id": 9, "content": "Race day is on the 14th"},
            ],
        },
    )
    assert [group["kind"] for group in out] == ["note"]
    items = out[0]["items"]
    assert [item["id"] for item in items] == [3, 9]
    assert items[0]["label"].startswith("Bought milk")
    assert items[0]["snippet"].startswith("Bought milk")


def test_one_note_read_in_full_is_still_a_card():
    """`get_note` returns the note itself rather than a list of them, the
    shape `_touched_items` calls the single-item case."""
    out = cards.result_cards("get_note", {"id": 4, "content": "The whole note"})
    assert out == [{"kind": "note", "items": [{"id": 4, "label": "The whole note", "snippet": "The whole note"}]}]


def test_a_document_is_never_filed_as_a_note():
    """The trap `agent._touched_kind`'s own docstring records: a document
    result carries `id`, `title` *and* `content`, so anything reading
    `content` first would open the *note* with that id, a different object
    entirely. Here the tool name settles it before any field is read."""
    out = cards.result_cards(
        "get_document", {"id": 12, "title": "Thesis outline", "content": "Chapter one…"}
    )
    assert [group["kind"] for group in out] == ["document"]
    assert out[0]["items"][0]["label"] == "Thesis outline"


def test_a_note_with_no_text_still_gets_a_name():
    out = cards.result_cards("get_note", {"id": 7, "content": ""})
    assert out[0]["items"][0]["label"] == "Note #7"


# --- files --------------------------------------------------------------------


def test_a_file_card_keeps_which_table_it_came_from():
    """A `MediaUpload` and an `Attachment` have separate id spaces, so id 1 is
    two different files. A card that dropped `file_kind` would open one of
    them at random."""
    out = cards.result_cards(
        "search_files",
        {
            "files": [
                {"kind": "upload", "id": 1, "name": "board.png", "url": "/media/board.png",
                 "caption": "A photo of a whiteboard"},
                {"kind": "attachment", "id": 1, "name": "lecture.pdf", "url": "/files/1",
                 "text": "Week 3: gradients", "attached_to_note": 5},
            ]
        },
    )
    items = out[0]["items"]
    assert [item["file_kind"] for item in items] == ["upload", "attachment"]
    assert [item["id"] for item in items] == [1, 1], "two rows, not one deduplicated away"
    assert items[0]["url"] == "/media/board.png"
    assert items[1]["note_id"] == 5


def test_a_file_row_without_a_usable_kind_is_dropped():
    """Rather than guessing: a card that opens the wrong table is worse than
    no card."""
    out = cards.result_cards("search_files", {"files": [{"id": 1, "name": "x.pdf"}]})
    assert out == []


# --- boards -------------------------------------------------------------------


def test_the_default_board_is_a_card_even_though_its_id_is_none():
    """`None` is a real board id in this app, it is the default board, which
    is why `_whiteboard_board_filter` exists. A "no id means no card" rule
    would have made the most-used board the one you cannot open."""
    out = cards.result_cards(
        "read_whiteboard",
        {"board_id": None, "board_title": "Default board", "cards": [], "links": []},
    )
    assert out == [{"kind": "board", "items": [{"id": None, "label": "Default board", "snippet": ""}]}]


def test_a_board_read_also_cards_the_notes_on_it():
    """A whiteboard card names its note under `note_id`; `id` there is the
    card's own row id and opens nothing."""
    out = cards.result_cards(
        "read_whiteboard",
        {
            "board_id": 8,
            "board_title": "Project planning",
            "cards": [{"card_id": 41, "note_id": 3, "preview": "Ship the thing"}],
            "links": [],
        },
    )
    kinds = {group["kind"]: group["items"] for group in out}
    assert kinds["board"][0]["id"] == 8
    assert kinds["note"][0]["id"] == 3, "the note, not the card row"
    assert kinds["note"][0]["label"] == "Ship the thing"


# --- reminders ----------------------------------------------------------------


def test_a_reminder_card_carries_what_the_actions_need():
    out = cards.result_cards(
        "list_reminders",
        {
            "reminders": [
                {"id": 2, "text": "Call the bank", "due_at": "2026-09-09T09:00:00", "done": False, "note_id": 5},
                {"id": 3, "text": "Pay rent", "due_at": "2026-09-01T09:00:00", "done": True, "note_id": None},
            ]
        },
    )
    items = out[0]["items"]
    assert [item["done"] for item in items] == [False, True]
    assert items[0]["due_at"] == "2026-09-09T09:00:00"
    assert items[0]["note_id"] == 5
    assert "note_id" not in items[1], "a reminder attached to nothing does not claim a note"


# --- the rules that keep it honest --------------------------------------------


def test_a_failed_call_names_nothing():
    """The transcript must not invent a note the call never reached. Same rule
    `_tool_sources` follows for the Sources panel."""
    assert cards.result_cards("search_notes", {"error": "no such note", "notes": [{"id": 1, "content": "x"}]}) == []


def test_a_tool_with_no_openable_result_contributes_nothing():
    assert cards.result_cards("count_notes", {"count": 12, "total": 40}) == []


def test_an_unregistered_name_is_ignored_rather_than_guessed():
    assert cards.result_cards("not_a_tool", {"notes": [{"id": 1, "content": "x"}]}) == []


def test_cards_are_capped_so_one_call_cannot_bury_the_answer():
    out = cards.result_cards(
        "list_notes",
        {"notes": [{"id": i, "content": f"note {i}"} for i in range(1, 40)]},
    )
    assert len(out[0]["items"]) == cards.CARD_ITEM_LIMIT


def test_the_same_thing_named_twice_is_one_card():
    """`related_notes` can name a note in `related` and again in
    `might_connect`; two chips for one note is a list that lies about how much
    was read."""
    out = cards.result_cards(
        "related_notes",
        {
            "related": [{"id": 3, "preview": "one"}],
            "might_connect": [{"id": 3, "preview": "one"}, {"id": 4, "preview": "two"}],
        },
    )
    assert [item["id"] for item in out[0]["items"]] == [3, 4]


def test_a_result_that_is_not_a_dict_is_survivable():
    assert cards.result_cards("search_notes", None) == []
    assert cards.result_cards("search_notes", "boom") == []


# --- end to end, through the agent loop ---------------------------------------


def _events(client, question, **body):
    with client.stream("POST", "/chat/stream", json={"question": question, **body}) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def test_the_tool_event_carries_its_cards(ai_client, fake_ollama, app_state):
    """The whole point, measured where it matters: the chat's tool event: the
    thing `toolChip` renders: now has typed cards on it."""
    ai_client.post("/entries", json={"content": "Bought milk and eggs"})
    fake_ollama.tool_script = [
        [{"name": "search_notes", "arguments": {"query": "milk"}}],
    ]
    events = _events(ai_client, "what did I buy?", use_tools=True)
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["tool"] == "search_notes"
    note_cards = [group for group in tool["cards"] if group["kind"] == "note"]
    assert note_cards and note_cards[0]["items"], "the note it found should be openable"
    assert note_cards[0]["items"][0]["label"].startswith("Bought milk")


def test_touched_is_still_sent_beside_the_cards(ai_client, fake_ollama, app_state):
    """`skill_runner._absorb` reads `touched` to carry ids across a run's
    steps, and every transcript saved before cards existed has only that. It
    stays."""
    ai_client.post("/entries", json={"content": "Bought milk and eggs"})
    fake_ollama.tool_script = [[{"name": "search_notes", "arguments": {"query": "milk"}}]]
    events = _events(ai_client, "what did I buy?", use_tools=True)
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["touched"], "the older field is still populated"
