"""Renaming a file from the Library, for both kinds of row.

Reported: *"i cant rename or delete files via a kebab button in the files
subtab."* The kebab was there and Delete worked; Rename was withheld from
`Attachment` rows on the reasoning that an attachment's name is the note's own
file list's business. That was a judgement about where a name belongs, and the
report overrules it: a file shown in the Library is a file you expect to
manage in the Library.

The two tables take different routes and different field names, which is the
part a frontend can get silently wrong: `PUT /files/{id}` wants `filename` and
answers with the whole note; `PUT /media/{id}` wants `original_name` and
answers with the upload.
"""

from __future__ import annotations

import io

from memorymap.entry import manager


def _note_with_file(client, session, name="lecture.pdf"):
    entry = manager.create_entry(session, "a note that carries a file")
    session.commit()
    response = client.post(
        f"/entries/{entry.id}/files",
        files={"file": (name, io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert response.status_code in (200, 201), response.text
    return entry, response.json()


def test_an_attachment_can_be_renamed(ai_client, session):
    entry, _ = _note_with_file(ai_client, session)
    listing = ai_client.get(f"/entries/{entry.id}").json()
    attachment_id = listing["attachments"][0]["id"]

    response = ai_client.put(f"/files/{attachment_id}", json={"filename": "week 3 slides.pdf"})
    assert response.status_code == 200, response.text

    names = [a["filename"] for a in response.json()["attachments"]]
    assert "week 3 slides.pdf" in names


def test_the_rename_response_carries_the_note_not_the_attachment(ai_client, session):
    """The shape the frontend has to read back from, it has no
    `original_name`, which is what the media route returns instead."""
    entry, _ = _note_with_file(ai_client, session)
    attachment_id = ai_client.get(f"/entries/{entry.id}").json()["attachments"][0]["id"]

    body = ai_client.put(f"/files/{attachment_id}", json={"filename": "renamed.pdf"}).json()
    assert "attachments" in body
    assert "original_name" not in body


def test_an_empty_name_is_refused(ai_client, session):
    entry, _ = _note_with_file(ai_client, session)
    attachment_id = ai_client.get(f"/entries/{entry.id}").json()["attachments"][0]["id"]

    assert ai_client.put(f"/files/{attachment_id}", json={"filename": ""}).status_code == 422


def test_renaming_a_file_that_is_not_there_is_a_404(ai_client):
    assert ai_client.put("/files/999999", json={"filename": "x.pdf"}).status_code == 404
