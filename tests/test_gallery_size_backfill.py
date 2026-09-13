"""`GET /files/gallery` reads `Attachment.size`, not the filesystem.

`_attachment_size()` used to `stat()` the upload folder for every row on
every open: the same mistake `list_media` still has open under PLAN.md P6,
just on the attachment gallery instead. `Attachment.size` is written at
upload time and kept current from there, so a `stat()` at read time was
pure waste on every row that already had it. This asserts the fix by
counting real syscalls against the uploads folder, not by reasoning about
the code: a second gallery call must not touch an attachment's file at all,
and a row whose `size` was never backfilled (simulated by zeroing the
column directly, the state a pre-fix database is genuinely in) gets exactly
one `stat()`, the one-time backfill, and none after that.

Counting is scoped to paths inside the uploads directory rather than every
`Path.stat` call process-wide: patching the builtin globally also catches
unrelated stats FastAPI/Starlette make while serving the request (static
file checks, the CSP page read), which have nothing to do with the bug this
guards and would make the count fragile against changes in code this test
doesn't own.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from memorymap.core import deps
from memorymap.entry import manager


def _note_with_file(client, session, name="photo.png"):
    entry = manager.create_entry(session, "a note with a picture attached")
    session.commit()
    response = client.post(
        f"/entries/{entry.id}/files",
        files={"file": (name, io.BytesIO(b"not really a png but bytes"), "image/png")},
    )
    assert response.status_code in (200, 201), response.text
    return entry


def _uploads_stat_counter():
    """A patch of `Path.stat` that only counts calls under this notebook's
    uploads directory, real `stat()` still runs underneath so the response
    stays correct."""
    uploads_dir = deps.get_config().uploads_dir
    real_stat = Path.stat
    counter = {"n": 0}

    def fake(self, *args, **kwargs):
        if uploads_dir in self.parents:
            counter["n"] += 1
        return real_stat(self, *args, **kwargs)

    return patch.object(Path, "stat", autospec=True, side_effect=fake), counter


def test_attachment_size_is_stored_at_upload(ai_client, session):
    """The column the fix reads is actually populated on upload, otherwise
    every gallery load would hit the one-time backfill path forever."""
    entry = _note_with_file(ai_client, session)
    gallery = ai_client.get("/files/gallery").json()
    row = next(r for r in gallery if r["used_by"][0]["id"] == entry.id)
    assert row["size_bytes"] > 0


def test_a_second_gallery_call_makes_zero_uploads_stat_calls(ai_client, session):
    """The behaviour the report was about: with `size` already populated,
    reading the gallery must never touch the filesystem for it."""
    _note_with_file(ai_client, session)
    _note_with_file(ai_client, session, name="second.png")
    assert ai_client.get("/files/gallery").status_code == 200  # warm any caches

    patcher, counter = _uploads_stat_counter()
    with patcher:
        response = ai_client.get("/files/gallery")
    assert response.status_code == 200
    assert len(response.json()) >= 2
    assert counter["n"] == 0


def test_a_row_with_no_stored_size_is_backfilled_exactly_once(ai_client, session):
    """A pre-existing attachment from before `size` was maintained: NULL/0
    in the column, a real file on disk. The first read has to stat it (there
    is nowhere else to get the number); every read after must not."""
    from memorymap.core.database import Attachment

    entry = _note_with_file(ai_client, session)
    attachment_id = ai_client.get(f"/entries/{entry.id}").json()["attachments"][0]["id"]

    row = session.get(Attachment, attachment_id)
    row.size = 0
    session.commit()
    session.close()

    patcher, counter = _uploads_stat_counter()
    with patcher:
        first = ai_client.get("/files/gallery")
    assert first.status_code == 200
    assert counter["n"] == 1  # the one-time backfill

    row_after = next(r for r in first.json() if r["id"] == attachment_id)
    assert row_after["size_bytes"] > 0

    patcher, counter = _uploads_stat_counter()
    with patcher:
        second = ai_client.get("/files/gallery")
    assert second.status_code == 200
    assert counter["n"] == 0  # backfilled: the column answers now
