"""Vision-model text transcription for uploaded images (ai/vision_ocr.py).

Same shape as test_captioning.py, deliberately: vision_ocr_text/
vision_ocr_and_store mirror caption_text/caption_and_store, with one added
wrinkle covered here specifically, a genuine "no text in this image"
result must not be recorded as a failed background task the way a real
call failure is.
"""

from __future__ import annotations

from pathlib import Path

from memorymap.ai import vision_ocr
from memorymap.core import deps, taskhistory
from memorymap.core.database import MediaUpload


def _upload(session, filename="a.png") -> int:
    row = MediaUpload(filename=filename, original_name=filename)
    session.add(row)
    session.commit()
    session.refresh(row)
    upload_id = row.id
    session.close()
    return upload_id


def test_vision_ocr_text_returns_the_models_reply(tmp_path, fake_ollama):
    fake_ollama.librarian_reply = "Milk, eggs, bread"
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    text = vision_ocr.vision_ocr_text(image_path, "llava", fake_ollama)
    assert text == "Milk, eggs, bread"


def test_vision_ocr_text_sends_a_data_uri_not_bare_base64(tmp_path, fake_ollama):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    vision_ocr.vision_ocr_text(image_path, "llava", fake_ollama)
    sent = fake_ollama.chat_calls[-1][-1]
    assert sent["images"][0].startswith("data:image/png;base64,")


def test_vision_ocr_text_returns_empty_string_for_the_no_text_sentinel(tmp_path, fake_ollama):
    fake_ollama.librarian_reply = "NO_TEXT_FOUND"
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert vision_ocr.vision_ocr_text(image_path, "llava", fake_ollama) == ""


def test_vision_ocr_text_returns_none_on_a_missing_file(fake_ollama):
    assert vision_ocr.vision_ocr_text(Path("/does/not/exist.png"), "llava", fake_ollama) is None


def test_vision_ocr_text_returns_none_when_the_backend_errors(tmp_path):
    class _BrokenOllama:
        def chat(self, model, messages):
            raise RuntimeError("boom")

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert vision_ocr.vision_ocr_text(image_path, "llava", _BrokenOllama()) is None


def test_vision_ocr_and_store_writes_the_text_onto_the_row(app_state, session, fake_ollama, tmp_path):
    fake_ollama.librarian_reply = "Table 4, 7pm"
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    result = vision_ocr.vision_ocr_and_store(upload_id, image_path)
    assert result == "Table 4, 7pm"
    with deps.get_db().session() as check:
        row = check.get(MediaUpload, upload_id)
        assert row.vision_ocr_text == "Table 4, 7pm"
        assert row.vision_ocr_model


def test_vision_ocr_and_store_does_nothing_without_a_vision_model(
    app_state, session, fake_ollama, tmp_path
):
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = []
    deps.override_ai(ollama=fake_ollama)

    assert vision_ocr.vision_ocr_and_store(upload_id, image_path) is None
    with deps.get_db().session() as check:
        assert check.get(MediaUpload, upload_id).vision_ocr_text is None


def test_vision_ocr_and_store_is_write_once_by_default(app_state, session, fake_ollama, tmp_path):
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    with deps.get_db().session() as write:
        write.get(MediaUpload, upload_id).vision_ocr_text = "already read"
        write.commit()

    result = vision_ocr.vision_ocr_and_store(upload_id, image_path)
    assert result == "already read"
    assert len(fake_ollama.chat_calls) == 0


def test_vision_ocr_and_store_force_overwrites_existing_text(
    app_state, session, fake_ollama, tmp_path
):
    fake_ollama.librarian_reply = "fresh read"
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    with deps.get_db().session() as write:
        write.get(MediaUpload, upload_id).vision_ocr_text = "stale"
        write.commit()

    result = vision_ocr.vision_ocr_and_store(upload_id, image_path, force=True)
    assert result == "fresh read"


def test_vision_ocr_and_store_does_not_blow_up_if_the_upload_was_deleted_first(
    app_state, fake_ollama, tmp_path
):
    deps.override_ai(ollama=fake_ollama)
    assert vision_ocr.vision_ocr_and_store(999999, tmp_path / "gone.png") is None


def test_vision_ocr_and_store_records_a_completed_task(app_state, session, fake_ollama, tmp_path):
    taskhistory.clear()
    fake_ollama.librarian_reply = "some text"
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    vision_ocr.vision_ocr_and_store(upload_id, image_path)
    history = taskhistory.recent()
    assert history[0]["kind"] == "vision_ocr"
    assert history[0]["outcome"] == "completed"


def test_vision_ocr_and_store_records_completed_not_failed_when_no_text_is_found(
    app_state, session, fake_ollama, tmp_path
):
    """A genuine "nothing to transcribe" result is not a failure, it must
    not be recorded the same way a real backend error is, or the
    background-tasks list would fill with "failed" for every ordinary
    photo with no text in it."""
    taskhistory.clear()
    fake_ollama.librarian_reply = "NO_TEXT_FOUND"
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    result = vision_ocr.vision_ocr_and_store(upload_id, image_path)
    assert result == ""
    history = taskhistory.recent()
    assert history[0]["kind"] == "vision_ocr"
    assert history[0]["outcome"] == "completed"
    with deps.get_db().session() as check:
        row = check.get(MediaUpload, upload_id)
        assert row.vision_ocr_text == ""
        assert row.vision_ocr_model


def test_vision_ocr_and_store_records_a_failed_task_when_the_call_errors(
    app_state, session, fake_ollama, tmp_path
):
    def _broken_chat(model, messages):
        raise RuntimeError("500 Server Error")

    taskhistory.clear()
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    fake_ollama.chat = _broken_chat
    deps.override_ai(ollama=fake_ollama)

    result = vision_ocr.vision_ocr_and_store(upload_id, image_path)
    assert result is None
    history = taskhistory.recent()
    assert history[0]["kind"] == "vision_ocr"
    assert history[0]["outcome"] == "failed"


def test_vision_ocr_and_store_does_not_record_a_task_with_no_vision_model(
    app_state, session, fake_ollama, tmp_path
):
    taskhistory.clear()
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = []
    deps.override_ai(ollama=fake_ollama)

    vision_ocr.vision_ocr_and_store(upload_id, image_path)
    assert taskhistory.recent() == []


# --- Scanned PDFs, read automatically on upload ---------------------------
#
# The gap these cover: `VISION_OCR_SUFFIXES` is raster-only, so a filed PDF
# started no reader at all, `pdf_vision_reader` existed but was only ever
# reached from a button. Asked for directly: "make sure all the file and
# document ocr works with ai ocr models, I dont use tesseract."


def _pdf_upload(session) -> int:
    return _upload(session, filename="scan.pdf")


def test_pdf_vision_ocr_and_store_writes_what_the_reader_returns(
    app_state, session, monkeypatch, tmp_path
):
    upload_id = _pdf_upload(session)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(vision_ocr, "pdf_reader_or_none", lambda: (lambda p: "Page one text"))
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "llava"
    )

    assert vision_ocr.pdf_vision_ocr_and_store(upload_id, pdf) == "Page one text"
    with deps.get_db().session() as check:
        row = check.get(MediaUpload, upload_id)
        assert row.vision_ocr_text == "Page one text"
        assert row.vision_ocr_model == "llava"


def test_pdf_vision_ocr_and_store_leaves_a_text_layer_pdf_alone(
    app_state, session, monkeypatch, tmp_path
):
    """A model asked to transcribe a page whose text is already exact can only
    make it worse: so the expensive path is for scans only."""
    from memorymap.core import docview

    upload_id = _pdf_upload(session)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        docview, "extract", lambda path, vision_reader=None: docview.ViewedFile(
            text="Already selectable text", kind="plain", source="converted"
        )
    )
    called = []
    monkeypatch.setattr(
        vision_ocr, "pdf_reader_or_none", lambda: called.append("model") or (lambda p: "x")
    )

    assert vision_ocr.pdf_vision_ocr_and_store(upload_id, pdf) is None
    assert called == []
    with deps.get_db().session() as check:
        assert check.get(MediaUpload, upload_id).vision_ocr_text is None


def test_pdf_vision_ocr_and_store_is_quiet_with_no_reader(
    app_state, session, monkeypatch, tmp_path
):
    upload_id = _pdf_upload(session)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(vision_ocr, "pdf_reader_or_none", lambda: None)
    assert vision_ocr.pdf_vision_ocr_and_store(upload_id, pdf) is None


def test_pdf_vision_ocr_and_store_is_write_once_by_default(
    app_state, session, monkeypatch, tmp_path
):
    upload_id = _pdf_upload(session)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with deps.get_db().session() as write:
        row = write.get(MediaUpload, upload_id)
        row.vision_ocr_text = "read earlier"
        write.commit()
    called = []
    monkeypatch.setattr(
        vision_ocr, "pdf_reader_or_none", lambda: called.append("model") or (lambda p: "x")
    )
    assert vision_ocr.pdf_vision_ocr_and_store(upload_id, pdf) == "read earlier"
    assert called == []


def test_pdf_vision_ocr_and_store_records_the_completed_task(
    app_state, session, monkeypatch, tmp_path
):
    upload_id = _pdf_upload(session)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(vision_ocr, "pdf_reader_or_none", lambda: (lambda p: "Some text"))
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "llava"
    )
    taskhistory.clear()
    vision_ocr.pdf_vision_ocr_and_store(upload_id, pdf)
    history = taskhistory.recent()
    assert history[0]["kind"] == "vision_ocr"
    assert history[0]["outcome"] == "completed"
