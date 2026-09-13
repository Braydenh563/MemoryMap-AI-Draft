"""The agent can see uploaded files at all.

Asked for twice: *"is there a way to improve the backend and function of the
notebook further?? better grouping, better linking, better ai understanding of
all features??"* Every other part of the app was reachable by the model, 
notes, categories, tags, documents, whiteboards, reminders, past chats, skills
- and files were not, so "what was in that PDF I uploaded?" could not be
answered even though the app had already read the file.
"""

from __future__ import annotations

import pytest

from memorymap.ai import tools
from memorymap.ai.tools._common import ToolError
from memorymap.core.database import Attachment, MediaUpload


def _upload(session, name="scan.png", text=None, caption=None):
    row = MediaUpload(filename=f"stored-{name}", original_name=name)
    if text is not None:
        row.ocr_text = text
    if caption is not None:
        row.caption = caption
    session.add(row)
    session.commit()
    return row


def test_the_tools_are_registered():
    """A handler nobody registered is a feature that never runs."""
    assert "search_files" in tools.TOOLS
    assert "read_file" in tools.TOOLS


def test_search_finds_a_file_by_the_text_read_out_of_it(session):
    _upload(session, "invoice.png", text="Total due 42.00 on 3 March")
    found = tools.TOOLS["search_files"].handler(session, {"query": "total due"})
    assert [f["name"] for f in found["files"]] == ["invoice.png"]
    assert found["files"][0]["kind"] == "upload"


def test_search_finds_a_file_by_its_caption(session):
    _upload(session, "IMG_3021.png", caption="A whiteboard covered in sticky notes")
    found = tools.TOOLS["search_files"].handler(session, {"query": "sticky notes"})
    assert [f["name"] for f in found["files"]] == ["IMG_3021.png"]


def test_search_finds_a_file_by_name_when_nothing_has_been_read(session):
    _upload(session, "lecture-notes.pdf")
    found = tools.TOOLS["search_files"].handler(session, {"query": "lecture"})
    assert found["found"] == 1


def test_an_empty_query_lists_what_there_is(session):
    _upload(session, "one.png")
    _upload(session, "two.png")
    assert tools.TOOLS["search_files"].handler(session, {})["found"] == 2


def test_a_private_notes_attachment_is_not_searchable(session):
    """The same refusal a private note gets everywhere else, its attachments
    are part of it."""
    from memorymap.entry import manager

    entry = manager.create_entry(session, "secret", category_name=manager.UNCATEGORISED)
    entry.is_private = True
    attachment = Attachment(
        entry_id=entry.id, filename="secret-plan.pdf", stored_name="s1", size=1
    )
    attachment.ocr_text = "the merger closes in June"
    session.add(attachment)
    session.commit()

    found = tools.TOOLS["search_files"].handler(session, {"query": "merger"})
    assert found["found"] == 0


def test_reading_a_private_notes_attachment_is_refused(session):
    from memorymap.entry import manager

    entry = manager.create_entry(session, "secret", category_name=manager.UNCATEGORISED)
    entry.is_private = True
    attachment = Attachment(entry_id=entry.id, filename="s.pdf", stored_name="s2", size=1)
    session.add(attachment)
    session.commit()

    with pytest.raises(ToolError):
        tools.TOOLS["read_file"].handler(session, {"kind": "attachment", "file_id": attachment.id})


def test_read_file_returns_more_text_than_search_does(session):
    """Search is a list, it shows a preview; reading one file is the step
    that pays for the whole page of text."""
    long_text = "word " * 400
    upload = _upload(session, "long.png", text=long_text)
    listed = tools.TOOLS["search_files"].handler(session, {"query": "word"})["files"][0]
    read = tools.TOOLS["read_file"].handler(session, {"kind": "upload", "file_id": upload.id})
    assert len(read["text"]) > len(listed["text"])


def test_a_vision_reading_beats_tesseracts(session):
    """A vision model reads handwriting and low-contrast photographs that
    Tesseract cannot, so when both exist its transcription is the answer."""
    upload = _upload(session, "handwritten.png", text="scrambled ocr")
    upload.vision_ocr_text = "the actual handwriting"
    session.commit()
    read = tools.TOOLS["read_file"].handler(session, {"kind": "upload", "file_id": upload.id})
    assert read["text"] == "the actual handwriting"


def test_the_two_id_spaces_are_kept_apart(session):
    """`upload` 1 and `attachment` 1 are different objects; `kind` is what
    tells them apart, and a wrong kind must not silently read the other."""
    from memorymap.entry import manager

    entry = manager.create_entry(session, "host", category_name=manager.UNCATEGORISED)
    attachment = Attachment(entry_id=entry.id, filename="att.pdf", stored_name="a1", size=1)
    session.add(attachment)
    session.commit()
    upload = _upload(session, "up.png")

    by_upload = tools.TOOLS["read_file"].handler(
        session, {"kind": "upload", "file_id": upload.id}
    )
    by_attachment = tools.TOOLS["read_file"].handler(
        session, {"kind": "attachment", "file_id": attachment.id}
    )
    assert by_upload["name"] == "up.png"
    assert by_attachment["name"] == "att.pdf"
    assert by_attachment["attached_to_note"] == entry.id


def test_an_unknown_kind_is_refused_rather_than_guessed(session):
    with pytest.raises(ToolError):
        tools.TOOLS["read_file"].handler(session, {"kind": "picture", "file_id": 1})


# --- keyword context: the search preview and the full read actually contain
# the match, not just the start of the reading -------------------------------
#
# Reported directly: "if files are fully text extracted by ocr. if the ai is
# searching for something, might keywords be flagged in certain pages of a
# file document in the actual document and/or extracted text, then it can use
# a tool or smth simpler to get the full text from those areas??" Before this,
# `search_files` correctly found a file whose *reading* contained the word
# (it scans the whole text), but the `text` field it returned: and even
# `read_file`'s own full-text field, capped at 2000 characters, always
# started from the top of the reading, so a match past that point was never
# actually visible to the model, however precisely it had been located.


def test_the_search_preview_contains_the_word_that_matched(session):
    far_away = "padding " * 400  # comfortably past PREVIEW_CHARS (200)
    _upload(session, "long-scan.png", text=f"{far_away}the password is hunter2{far_away}")
    found = tools.TOOLS["search_files"].handler(session, {"query": "password"})
    assert found["found"] == 1
    assert "password is hunter2" in found["files"][0]["text"]


def test_read_file_with_a_query_returns_text_past_the_old_cap(session):
    """The concrete failure this fixes: a reading longer than FILE_TEXT_CHARS
    (2000) whose match sits past that point used to be unreachable through
    this tool no matter what, the read always started at character zero and
    stopped at 2000, so `search_files` could point at the file correctly and
    `read_file` would still come back with nothing useful."""
    from memorymap.ai.tools.files import FILE_TEXT_CHARS

    filler = "the quick brown fox jumps over the lazy dog. " * 100
    assert len(filler) > FILE_TEXT_CHARS
    upload = _upload(session, "manual.png", text=f"{filler}THE SECRET CODE IS 4471{filler}")
    read = tools.TOOLS["read_file"].handler(
        session, {"kind": "upload", "file_id": upload.id, "query": "secret code"}
    )
    assert "THE SECRET CODE IS 4471" in read["text"]
    # And the label says a query narrowed it, so the model can tell this
    # from an ordinary head-of-text read.
    assert "search term" in read["label"]


def test_read_file_with_no_query_keeps_the_old_head_of_text_behaviour(session):
    """No query, no change, this is additive, not a replacement for the
    plain "just read it" case."""
    upload = _upload(session, "short.png", text="Hello, this is a short reading.")
    read = tools.TOOLS["read_file"].handler(session, {"kind": "upload", "file_id": upload.id})
    assert read["text"] == "Hello, this is a short reading."
    assert "search term" not in read["label"]
