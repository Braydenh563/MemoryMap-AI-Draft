"""core/media_process.py: where OCR/captioning/vision-OCR actually fire
now that they no longer run automatically on `/media/upload` itself.

Asked for directly, correcting this session's own earlier choice: "the OCR
shouldn't happen to staged files, only when they are actually saved as a
note, actually sent in a chat message, or uploaded directly to the
library." These tests cover the module's own three entry points directly;
test_media_api.py covers the upload route's `direct` flag, and the
per-route tests below cover each of the three "committed" moments actually
triggering it end to end.
"""

from __future__ import annotations

from memorymap.ai import captioning, vision_ocr
from memorymap.core import deps, media_process, ocr
from memorymap.core.database import MediaUpload


def _upload(session, filename="a.png") -> MediaUpload:
    row = MediaUpload(filename=filename, original_name=filename)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_process_committed_upload_triggers_all_three_readers_for_an_image(
    session, tmp_path, monkeypatch
):
    # `process_committed_upload` imports these three lazily (the CodeQL
    # cyclic-import fix), so the names it calls are the real modules'
    # attributes, not attributes of `media_process` itself: patch those.
    calls = []
    monkeypatch.setattr(ocr, "extract_in_background", lambda *a: calls.append("ocr"))
    monkeypatch.setattr(
        captioning, "caption_in_background", lambda *a: calls.append("caption")
    )
    monkeypatch.setattr(
        vision_ocr, "vision_ocr_in_background", lambda *a: calls.append("vision_ocr")
    )
    upload = _upload(session)
    media_process.process_committed_upload(upload, tmp_path)
    assert set(calls) == {"ocr", "caption", "vision_ocr"}


def test_process_committed_upload_does_nothing_for_an_unsupported_suffix(
    session, tmp_path, monkeypatch
):
    calls: list[str] = []
    _patch_readers(monkeypatch, calls)
    upload = _upload(session, filename="notes.zip")
    media_process.process_committed_upload(upload, tmp_path)
    assert calls == []


def test_a_pdf_gets_the_vision_reader_and_nothing_else(session, tmp_path, monkeypatch):
    """The gap this closed: `OCR_SUFFIXES` and `VISION_OCR_SUFFIXES` are both
    raster-only, so a filed PDF started no reader at all and a scan stayed
    unsearchable until someone opened it and pressed a button."""
    calls: list[str] = []
    _patch_readers(monkeypatch, calls)
    upload = _upload(session, filename="scan.pdf")
    media_process.process_committed_upload(upload, tmp_path)
    assert calls == ["pdf_vision"]


def test_process_referenced_uploads_finds_media_by_filename_in_text(
    session, tmp_path, monkeypatch
):
    from memorymap.core import media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_committed_upload", lambda upload, media_dir: calls.append(upload.id)
    )
    upload = _upload(session, filename="hash123.png")
    other = _upload(session, filename="unrelated.png")

    media_process.process_referenced_uploads(
        session, tmp_path, f"a note with ![img](/media/{upload.filename})"
    )
    assert calls == [upload.id]
    assert other.id not in calls


def test_process_referenced_uploads_does_nothing_for_unreferenced_text(
    session, tmp_path, monkeypatch
):
    from memorymap.core import media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_committed_upload", lambda upload, media_dir: calls.append(upload.id)
    )
    _upload(session, filename="never-mentioned.png")
    media_process.process_referenced_uploads(session, tmp_path, "just plain text, no images")
    assert calls == []


def test_process_committed_upload_ids_finds_media_by_id(session, tmp_path, monkeypatch):
    from memorymap.core import media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_committed_upload", lambda upload, media_dir: calls.append(upload.id)
    )
    upload = _upload(session)
    media_process.process_committed_upload_ids(session, tmp_path, [upload.id])
    assert calls == [upload.id]


def test_process_committed_upload_ids_does_nothing_for_an_empty_list(
    session, tmp_path, monkeypatch
):
    from memorymap.core import media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_committed_upload", lambda upload, media_dir: calls.append(upload.id)
    )
    media_process.process_committed_upload_ids(session, tmp_path, [])
    assert calls == []


# --- end-to-end: each of the three "committed" moments ----------------------


def test_saving_a_note_processes_its_referenced_upload(ai_client, monkeypatch):
    import memorymap.core.media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_referenced_uploads", lambda session, media_dir, text: calls.append(text)
    )
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    ai_client.post("/entries", json={"content": f"look: ![img]({uploaded['url']})"})
    assert any(uploaded["url"] in text for text in calls)


def test_saving_a_document_processes_its_referenced_upload(ai_client, monkeypatch):
    import memorymap.core.media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_referenced_uploads", lambda session, media_dir, text: calls.append(text)
    )
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    ai_client.post(
        "/documents", json={"title": "Doc", "content": f"![img]({uploaded['url']})"}
    )
    assert any(uploaded["url"] in text for text in calls)


def test_updating_a_document_with_new_content_processes_its_upload(ai_client, monkeypatch):
    import memorymap.core.media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_referenced_uploads", lambda session, media_dir, text: calls.append(text)
    )
    created = ai_client.post("/documents", json={"title": "Doc", "content": "empty"}).json()
    calls.clear()
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    ai_client.put(
        f"/documents/{created['id']}",
        json={"content": f"![img]({uploaded['url']})"},
    )
    assert any(uploaded["url"] in text for text in calls)


def test_saving_a_chat_turn_processes_its_attached_image(ai_client, monkeypatch):
    import memorymap.core.media_process as mp

    calls = []
    monkeypatch.setattr(
        mp,
        "process_committed_upload_ids",
        lambda session, media_dir, media_ids: calls.append(media_ids),
    )
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    ai_client.post(
        "/conversations",
        json={"question": "what's this?", "answer": "a photo", "image_media_ids": [uploaded["id"]]},
    )
    assert calls == [[uploaded["id"]]]


def test_creating_a_whiteboard_image_object_processes_its_upload(ai_client, monkeypatch):
    import memorymap.core.media_process as mp

    calls = []
    monkeypatch.setattr(
        mp, "process_referenced_uploads", lambda session, media_dir, text: calls.append(text)
    )
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    ai_client.post(
        "/whiteboard/objects",
        json={"kind": "image", "data": {"url": uploaded["url"]}, "board_id": None},
    )
    assert any(uploaded["url"] in text for text in calls)


def _patch_readers(monkeypatch, calls):
    monkeypatch.setattr(ocr, "extract_in_background", lambda *a: calls.append("ocr"))
    monkeypatch.setattr(
        captioning, "caption_in_background", lambda *a: calls.append("caption")
    )
    monkeypatch.setattr(
        vision_ocr, "vision_ocr_in_background", lambda *a: calls.append("vision_ocr")
    )
    monkeypatch.setattr(
        vision_ocr, "pdf_vision_ocr_in_background", lambda *a: calls.append("pdf_vision")
    )


def test_turning_off_auto_captioning_leaves_the_text_readers_running(
    session, tmp_path, monkeypatch, app_state
):
    """Asked for directly: both automatic passes must be switchable off.

    Separately, not together - describing a picture is a vision-model round
    trip and is the expensive one, while Tesseract is local and cheap, so
    someone may well want the text without the description.
    """
    calls = []
    _patch_readers(monkeypatch, calls)
    deps.get_config().set_preference("auto_caption_images", False)

    media_process.process_committed_upload(_upload(session), tmp_path)

    assert "caption" not in calls
    assert set(calls) == {"ocr", "vision_ocr"}


def test_turning_off_auto_text_reading_stops_both_ocr_passes(
    session, tmp_path, monkeypatch, app_state
):
    """One switch covers Tesseract and the vision model together: both answer
    "what does this picture say", and a user turning that off does not mean
    "only the offline half of it"."""
    calls = []
    _patch_readers(monkeypatch, calls)
    deps.get_config().set_preference("auto_read_image_text", False)

    media_process.process_committed_upload(_upload(session), tmp_path)

    assert calls == ["caption"]


def test_both_automatic_passes_are_on_by_default(
    session, tmp_path, monkeypatch, app_state
):
    """The gate must not change behaviour for anyone who never touches it."""
    calls = []
    _patch_readers(monkeypatch, calls)

    media_process.process_committed_upload(_upload(session), tmp_path)

    assert set(calls) == {"ocr", "caption", "vision_ocr"}
