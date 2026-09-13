"""PLAN.md §0 P6: `GET /media` (`routes_files.list_media`) used to
`Path.stat()` every upload on every single call, purely to answer
`size_bytes`, found by AUDIT.md A11: "fine at 100 files, wrong at 5,000."

Two things this covers: a fresh upload's `size_bytes` is written once, at
upload time, from the byte count the handler already has (never stat'd at
all); and a *pre-existing* row, one written before this column existed,
which is the real-world case the additive auto-migrator's own NULL-backfill
convention leaves on every upgraded database, costs exactly one `stat()`
the first time it's listed, and none after that.
"""

from __future__ import annotations

from pathlib import Path

from memorymap.core import deps
from memorymap.core.database import MediaUpload


def _stat_counter(monkeypatch, media_dir: Path) -> list[Path]:
    """Count real `Path.stat()` calls made against files *inside `media_dir`*,
    without changing their result, a monkeypatched no-op would make every
    row look like a 0-byte/missing file, which is exactly the case this test
    needs to tell apart from "read the real size from disk".

    Scoped to `media_dir` on purpose: `SecurityHeadersMiddleware`'s own CSP
    (`app.py`'s `CspForPage`) stats `frontend/index.html` on every request to
    pick up a live frontend edit without a restart, real, unrelated to
    `list_media`, and would otherwise inflate this count on every call.
    """
    calls: list[Path] = []
    real_stat = Path.stat

    def _counting_stat(self, *args, **kwargs):
        if media_dir in self.parents:
            calls.append(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _counting_stat)
    return calls


def test_upload_writes_size_bytes_without_ever_stating_the_file(client, monkeypatch):
    """A fresh upload already has its byte count in hand (the handler counts
    it while streaming to disk, to enforce the 50 MB cap), storing that is
    free. Confirmed here by not letting a single `stat()` happen at all."""
    calls = _stat_counter(monkeypatch, deps.get_config().data_dir / "media")
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 500
    response = client.post(
        "/media/upload", files={"file": ("shot.png", payload, "image/png")}
    )
    assert response.status_code == 200
    upload_id = response.json()["id"]

    with deps.get_db().session() as session:
        row = session.get(MediaUpload, upload_id)
        assert row.size_bytes == len(payload)
    assert calls == []  # the whole point: no disk stat on upload either


def test_a_preexisting_row_is_backfilled_once_and_never_stat_again(client, monkeypatch):
    """Simulates a database from before `size_bytes` existed: a row with the
    column NULL (the auto-migrator's own backfill for a column with no
    scalar default) and a real file already on disk."""
    config = deps.get_config()
    media_dir = config.data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    payload = b"already on disk before this column did"
    (media_dir / "old-upload.png").write_bytes(payload)

    with deps.get_db().session() as session:
        row = MediaUpload(filename="old-upload.png", original_name="old-upload.png")
        session.add(row)
        session.commit()
        upload_id = row.id
        assert row.size_bytes is None  # the pre-existing-row state this backfills

    calls = _stat_counter(monkeypatch, media_dir)

    first = client.get("/media").json()
    first_row = next(r for r in first if r["id"] == upload_id)
    assert first_row["size_bytes"] == len(payload)
    assert len(calls) == 1  # exactly one stat, the backfill, not a scan

    # The backfill must have been written back, not just returned once.
    with deps.get_db().session() as session:
        assert session.get(MediaUpload, upload_id).size_bytes == len(payload)

    second = client.get("/media").json()
    second_row = next(r for r in second if r["id"] == upload_id)
    assert second_row["size_bytes"] == len(payload)
    assert len(calls) == 1  # unchanged: the second call stat'd nothing at all


def test_a_row_whose_file_is_gone_backfills_to_zero_not_none(client, monkeypatch):
    """`MediaUploadOut.size_bytes` promises 0, never null, for a row that has
    outlived its file (the gallery already draws a placeholder for that
    state): this pins the backfill path to the same contract, not just the
    happy path above."""
    with deps.get_db().session() as session:
        row = MediaUpload(filename="never-existed.png", original_name="gone.png")
        session.add(row)
        session.commit()
        upload_id = row.id

    listed = client.get("/media").json()
    row_out = next(r for r in listed if r["id"] == upload_id)
    assert row_out["size_bytes"] == 0

    with deps.get_db().session() as session:
        # Backfilled to 0 (a known answer), not left NULL (which would retry
        # the same failing stat() on every future call, see the column's
        # own docstring in core/database.py).
        assert session.get(MediaUpload, upload_id).size_bytes == 0
