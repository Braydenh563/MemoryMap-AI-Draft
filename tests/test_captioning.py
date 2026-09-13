"""Automatic image captions from a vision-capable model (ai/captioning.py).

Same shape as test_ocr.py, deliberately: caption_text/caption_and_store
mirror extract_text/extract_and_store, and this suite exercises the same
contract: never raises, write-once unless forced, does nothing gracefully
when the upload row is gone.
"""

from __future__ import annotations

from memorymap.ai import captioning
from memorymap.core import deps
from memorymap.core.database import MediaUpload


def _upload(session, filename="a.png") -> int:
    row = MediaUpload(filename=filename, original_name=filename)
    session.add(row)
    session.commit()
    session.refresh(row)
    upload_id = row.id
    session.close()
    return upload_id


def test_caption_text_returns_the_models_reply(tmp_path, fake_ollama):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    text = captioning.caption_text(image_path, "llava", fake_ollama)
    assert text == fake_ollama.librarian_reply


def test_caption_text_sends_a_data_uri_not_bare_base64(tmp_path, fake_ollama):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    captioning.caption_text(image_path, "llava", fake_ollama)
    sent = fake_ollama.chat_calls[-1][-1]
    assert sent["images"][0].startswith("data:image/png;base64,")


def test_caption_text_never_raises_on_a_missing_file(fake_ollama):
    from pathlib import Path

    assert captioning.caption_text(Path("/does/not/exist.png"), "llava", fake_ollama) == ""


def test_caption_text_never_raises_when_the_backend_errors(tmp_path):
    class _BrokenOllama:
        def chat(self, model, messages):
            raise RuntimeError("boom")

    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert captioning.caption_text(image_path, "llava", _BrokenOllama()) == ""


def test_caption_and_store_writes_the_caption_onto_the_row(app_state, session, fake_ollama, tmp_path):
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    result = captioning.caption_and_store(upload_id, image_path)
    assert result == fake_ollama.librarian_reply
    with deps.get_db().session() as check:
        assert check.get(MediaUpload, upload_id).caption == fake_ollama.librarian_reply


def test_caption_and_store_does_nothing_without_a_vision_model(app_state, session, fake_ollama, tmp_path):
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = []  # nothing declares vision
    deps.override_ai(ollama=fake_ollama)

    assert captioning.caption_and_store(upload_id, image_path) is None
    with deps.get_db().session() as check:
        assert check.get(MediaUpload, upload_id).caption is None


def test_caption_and_store_is_write_once_by_default(app_state, session, fake_ollama, tmp_path):
    """Reported requirement: "if one is already there, another doesn't need
    to be written unless the user presses the button to rewrite it."""
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    with deps.get_db().session() as write:
        write.get(MediaUpload, upload_id).caption = "an existing caption"
        write.commit()

    result = captioning.caption_and_store(upload_id, image_path)
    assert result == "an existing caption"
    assert len(fake_ollama.chat_calls) == 0  # never even asked the model


def test_caption_and_store_force_overwrites_an_existing_caption(app_state, session, fake_ollama, tmp_path):
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    with deps.get_db().session() as write:
        write.get(MediaUpload, upload_id).caption = "stale"
        write.commit()

    result = captioning.caption_and_store(upload_id, image_path, force=True)
    assert result == fake_ollama.librarian_reply
    with deps.get_db().session() as check:
        assert check.get(MediaUpload, upload_id).caption == fake_ollama.librarian_reply


def test_caption_and_store_does_not_blow_up_if_the_upload_was_deleted_first(app_state, fake_ollama, tmp_path):
    deps.override_ai(ollama=fake_ollama)
    assert captioning.caption_and_store(999999, tmp_path / "gone.png") is None


def test_caption_and_store_records_which_model_wrote_it(app_state, session, fake_ollama, tmp_path):
    """Asked for directly: a caption should say which model wrote it, so it
    reads as one model's guess rather than the app's own opinion."""
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    captioning.caption_and_store(upload_id, image_path)
    with deps.get_db().session() as check:
        row = check.get(MediaUpload, upload_id)
        assert row.caption_model
        assert row.caption_edited is False


def test_caption_and_store_records_a_completed_task(app_state, session, fake_ollama, tmp_path):
    """Reported directly: captioning never showed up in Settings →
    Background tasks, success or failure, as if it had never run."""
    from memorymap.core import taskhistory

    taskhistory.clear()
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    captioning.caption_and_store(upload_id, image_path)
    history = taskhistory.recent()
    assert history[0]["kind"] == "caption"
    assert history[0]["outcome"] == "completed"


def test_caption_and_store_records_a_failed_task_when_the_model_produces_nothing(
    app_state, session, fake_ollama, tmp_path
):
    """The reported bug: a captioning call failing outright (a 500 from the
    backend) left no trace anywhere but the log console."""
    from memorymap.core import taskhistory

    def _broken_chat(model, messages):
        raise RuntimeError("500 Server Error")

    taskhistory.clear()
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    fake_ollama.chat = _broken_chat
    deps.override_ai(ollama=fake_ollama)

    result = captioning.caption_and_store(upload_id, image_path)
    assert result is None
    history = taskhistory.recent()
    assert history[0]["kind"] == "caption"
    assert history[0]["outcome"] == "failed"


def test_caption_and_store_does_not_record_a_task_with_no_vision_model(
    app_state, session, fake_ollama, tmp_path
):
    """Not a failure worth a history entry, every upload on a notebook
    with no vision model installed would otherwise fill the ring with the
    same expected, non-actionable line."""
    from memorymap.core import taskhistory

    taskhistory.clear()
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = []  # nothing declares vision
    deps.override_ai(ollama=fake_ollama)

    captioning.caption_and_store(upload_id, image_path)
    assert taskhistory.recent() == []


def test_caption_and_store_force_clears_the_edited_flag(app_state, session, fake_ollama, tmp_path):
    """A fresh AI write always supersedes a manual edit, the badge should
    say the model wrote the current text, not that a person's old edit is
    still what's showing."""
    upload_id = _upload(session)
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    with deps.get_db().session() as write:
        row = write.get(MediaUpload, upload_id)
        row.caption = "a hand-typed caption"
        row.caption_edited = True
        write.commit()

    captioning.caption_and_store(upload_id, image_path, force=True)
    with deps.get_db().session() as check:
        row = check.get(MediaUpload, upload_id)
        assert row.caption_edited is False
        assert row.caption_model


def test_running_captions_is_empty_when_nothing_is_captioning():
    """ROADMAP §89.6: the Tasks panel's own empty case."""
    assert captioning.running_captions() == []


def test_running_captions_reports_the_upload_while_the_model_call_is_in_flight(
    app_state, session, fake_ollama, tmp_path, monkeypatch
):
    """The gap this item closed: a caption call is a real model round-trip
    (seconds, not instant) and until now nothing showed it happening. This
    checks the state a poll of /tasks would see mid-call, not just before
    and after."""
    upload_id = _upload(session, filename="vacation.png")
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_ollama.capabilities_declared = ["vision"]
    deps.override_ai(ollama=fake_ollama)

    seen_mid_call = []
    real_caption_text = captioning.caption_text

    def _spy(*args, **kwargs):
        seen_mid_call.append(captioning.running_captions())
        return real_caption_text(*args, **kwargs)

    monkeypatch.setattr(captioning, "caption_text", _spy)
    captioning.caption_and_store(upload_id, image_path)

    assert seen_mid_call == [[{"upload_id": upload_id, "name": "vacation.png"}]]
    # Cleared once the call returns, not left stuck "running" forever.
    assert captioning.running_captions() == []
