"""`GET /media` reports each upload's size on disk.

Asked for directly, in the Files sub-tab redesign: "there should be details
on the name... file details such as the type, size, topic/category". The
schema comment on `created_at` had explicitly declined to carry a byte count
("a number nobody asked for"); this is the request that reverses it, so the
test pins the number rather than leaving it to the comment.

**Size is recorded once, at upload time, not re-read from disk on every
list** (PLAN.md §0 P6: see `test_media_size_backfill.py` for the migration
path and the stat-count proof). That is a deliberate trade this file's own
second test used to test the opposite side of: it used to delete an
upload's file *out from under the app*, bypassing `DELETE /media/{id}`
entirely: and expect the very next list to notice and self-heal to 0. That
required a `stat()` per row on every single call, which is the exact cost
this item exists to remove; the two are not simultaneously satisfiable,
and the PLAN item is explicit ("read it from the row thereafter"). Deleting
a file through the app it actually removes the row too (see `delete_media`),
so a stale size is only ever visible for a file interfered with by
something other than this app, which is what the test below now covers
instead: a row that starts with no reading at all, the real upgrade case,
never a fabricated one, still finds and reports the truth once.
"""
from __future__ import annotations

import io


def _upload(client, name: str, blob: bytes) -> dict:
    response = client.post("/media/upload", files={"file": (name, io.BytesIO(blob), "image/png")})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_gallery_reports_the_real_byte_count(client):
    blob = b"x" * 4321
    _upload(client, "sized.png", blob)
    row = next(r for r in client.get("/media").json() if r["original_name"] == "sized.png")
    assert row["size_bytes"] == len(blob)


def test_a_row_predating_the_column_is_backfilled_from_the_real_file(client):
    """The upgrade case `size_bytes` actually exists for: a row written by a
    version of this app from before the column did, carrying NULL (the
    additive auto-migrator's own convention for a column with no scalar
    default: see its docstring in `core/database.py`), with its file still
    genuinely on disk. `list_media` has to find that real size the first
    time the row is listed, same as it always did, the change is that it
    only ever does this once per row (`test_media_size_backfill.py`)."""
    from memorymap.core import deps
    from memorymap.core.database import MediaUpload

    stored = deps.get_config().data_dir / "media"
    stored.mkdir(parents=True, exist_ok=True)
    blob = b"y" * 777
    (stored / "predates-the-column.png").write_bytes(blob)
    with deps.get_db().session() as session:
        row = MediaUpload(filename="predates-the-column.png", original_name="old.png")
        session.add(row)
        session.commit()
        upload_id = row.id

    listed = next(r for r in client.get("/media").json() if r["id"] == upload_id)
    assert listed["size_bytes"] == len(blob)


def test_a_row_whose_file_was_never_written_reports_zero_rather_than_failing(client):
    """The gallery already renders a placeholder for a row with no working
    file, so listing has to survive it, a raise here would take out the
    whole Library, not one tile. Covers a row backfilled against a filename
    that never existed (a stat that fails), distinct from the happy path
    above (a stat that succeeds)."""
    from memorymap.core import deps
    from memorymap.core.database import MediaUpload

    with deps.get_db().session() as session:
        row = MediaUpload(filename="never-written.png", original_name="vanishing.png")
        session.add(row)
        session.commit()
        upload_id = row.id

    row_out = next(r for r in client.get("/media").json() if r["id"] == upload_id)
    assert row_out["size_bytes"] == 0
