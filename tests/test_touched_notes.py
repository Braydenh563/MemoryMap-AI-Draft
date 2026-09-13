"""What a tool call touched, notes *and* documents, for the live action line.

Asked for: *"is it also possible to have live action lines show on the chat ui,
to show and visually show as the ai accesses specific notes, files and
stuff??"*

Read from the tool's own **result**, never from the arguments it was called
with: arguments are what the model asked for, which may be a search string
rather than an id, may be wrong, and may name a note the call then refused. The
result is what happened.
"""

from __future__ import annotations

import pathlib

from memorymap.ai.agent import TOUCHED_LIMIT, _touched_items


def test_a_single_note_result_is_itself_the_note():
    """`get_note`, `edit_note` and `pin_note` return the note at the top level."""
    touched = _touched_items({"id": 43, "content": "League of Legends champions", "tags": []})
    assert touched == [{"kind": "note", "id": 43, "label": "League of Legends champions"}]


def test_a_list_result_names_every_note():
    touched = _touched_items(
        {"notes": [{"id": 1, "content": "one"}, {"id": 2, "content": "two"}]}
    )
    assert [t["id"] for t in touched] == [1, 2]


def test_the_same_note_is_named_once():
    touched = _touched_items(
        {"id": 7, "content": "seven", "notes": [{"id": 7, "content": "seven"}]}
    )
    assert [t["id"] for t in touched] == [7]


def test_a_row_without_content_is_not_a_note():
    """Plenty of results carry an `id` that is not a note's: a link id, a
    reminder's, a category's. `content` is what every note-shaped result has."""
    assert _touched_items({"id": 5, "name": "Games", "total": 3}) == []


def test_a_tool_that_touched_nothing_contributes_nothing():
    """The UI omits the row entirely rather than drawing an empty one."""
    assert _touched_items({"total": 27, "by_category": {"Games": 3}}) == []


def test_the_label_is_one_line_and_bounded():
    long = "a very long note " * 20
    label = _touched_items({"id": 1, "content": f"first line\n\n{long}"})[0]["label"]
    assert "\n" not in label
    assert len(label) <= 60


def test_a_huge_result_is_capped():
    """A `list_notes` over a big notebook would otherwise bury the answer under
    its own evidence."""
    rows = [{"id": i, "content": f"note {i}"} for i in range(50)]
    assert len(_touched_items({"notes": rows})) == TOUCHED_LIMIT


def test_a_note_with_no_text_still_gets_a_label():
    assert _touched_items({"id": 9, "content": ""})[0]["label"] == "note #9"


def test_a_non_dict_result_is_survivable():
    assert _touched_items(None) == []
    assert _touched_items("boom") == []


def test_a_document_result_is_a_document_not_a_note():
    """The defect this function exists to prevent: `read_document` returns
    `id`, `title` *and* `content`, so a `content`-only test called it a note
    and the UI opened the note with that id, a different object entirely."""
    touched = _touched_items(
        {"id": 12, "title": "Lease agreement", "content": "body text", "words": 900}
    )
    assert touched == [{"kind": "document", "id": 12, "label": "Lease agreement"}]


def test_a_note_and_a_document_sharing_an_id_are_both_named():
    """Ids collide across the two tables, so dedup keys on (kind, id)."""
    touched = _touched_items(
        {
            "notes": [{"id": 3, "content": "note three"}],
            "documents": [{"id": 3, "title": "Doc three"}],
        }
    )
    assert [(t["kind"], t["id"]) for t in touched] == [("note", 3), ("document", 3)]


def test_a_titled_document_with_no_title_text_still_gets_a_label():
    assert _touched_items({"id": 4, "title": ""})[0]["label"] == "document #4"


# The frontend half, as a lint. The Python suite cannot execute app.js, but the
# two ways this feature breaks are both visible in its source, and both have
# already happened once.

APP_JS = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "app.js"


def test_the_chip_routes_on_kind_rather_than_assuming_a_note():
    """`flashEntry(id)` on a document id opens an unrelated note."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "const TOUCHED_KINDS = {" in source
    assert "openDocumentFromNote(id)" in source


def test_the_transcript_serialiser_matches_the_wrapped_row():
    """`classList.contains` is an exact token match, so a row wrapped as
    `.tool-chip-wrap` is invisible to a `.tool-chip` test: and the whole tool
    call then disappears from the conversation when it is reopened."""
    source = APP_JS.read_text(encoding="utf-8")
    assert 'node.classList.contains("tool-chip-wrap")' in source
    assert "node.toolStep ||" in source


def test_rows_that_are_not_notes_or_documents_are_left_alone():
    """The shapes that share a scanned key but are neither: a web search hit
    (title, no id), a whiteboard match (board_id/object_id, no id) and a
    category (id + name). Any of these leaking in would draw a chip that
    opens the wrong thing, or nothing at all."""
    assert _touched_items({"results": [{"title": "A page", "url": "https://x"}]}) == []
    assert _touched_items({"matches": [{"board_id": 2, "object_id": 9, "text": "hi"}]}) == []
    assert _touched_items({"id": 5, "name": "Games"}) == []
    # `link_notes` returns plain ids, not rows, nothing to name.
    assert _touched_items({"linked": [3, 4]}) == []
