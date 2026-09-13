"""A document says what it is as soon as it is attached.

The owner, 2026-09-09, with a screenshot of a Files row showing a wall of
transcription and no description: "the files description needs to be an
actual description or summary of what the file is about and includes, not a
transcription", and earlier, of the same tab, "the describe with ai button in
the files tab doesnt work ... no notification, no bg process, nothing."

An `Attachment` had no analysis of any kind on upload: an image gets OCR and
a caption on a background thread the moment it lands, and a document got
neither, so every Files row was a filename until somebody clicked into it one
at a time. `read_document_and_store` is that missing pass. It is the
attachment side of `captioning.caption_and_store`, and it follows the same
three rules: runs off the request, never raises, and never rewrites what is
already there.
"""

from __future__ import annotations

from pathlib import Path

from memorymap.ai import docreader
from memorymap.core.database import Attachment


class _Ollama:
    def is_running(self):
        return True

    def chat(self, model, messages):
        return {"content": "A handout about agents and tools."}


class _Models:
    def utility_model(self):
        return "fake-utility"


class _NoOllama:
    def is_running(self):
        return False

    def chat(self, model, messages):  # pragma: no cover, must never be reached
        raise AssertionError("the describer ran with no model available")


def _attach(client, text=b"# Agents\n\nSome readable content about tools.", name="handout.md"):
    entry = client.post("/entries", json={"content": "host note"}).json()
    made = client.post(f"/entries/{entry['id']}/files", files={"file": (name, text, "text/markdown")})
    assert made.status_code in (200, 201), made.text
    body = made.json()
    return body["id"] if "id" in body else body["files"][0]["id"]


def test_the_text_is_extracted_and_the_document_described(client, session, monkeypatch):
    from memorymap.core import deps

    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    file_id = _attach(client)
    docreader.read_document_and_store(file_id)
    row = session.get(Attachment, file_id)
    session.refresh(row)
    assert "readable content" in (row.ocr_text or "")
    assert row.caption == "A handout about agents and tools."


def test_with_no_model_the_text_is_still_extracted(client, session, monkeypatch):
    from memorymap.core import deps

    monkeypatch.setattr(deps, "get_ollama", _NoOllama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    file_id = _attach(client)
    docreader.read_document_and_store(file_id)
    row = session.get(Attachment, file_id)
    session.refresh(row)
    assert "readable content" in (row.ocr_text or "")
    assert not row.caption


def test_an_existing_reading_is_never_overwritten(client, session, monkeypatch):
    from memorymap.core import deps

    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    file_id = _attach(client)
    row = session.get(Attachment, file_id)
    row.ocr_text = "a reading somebody corrected by hand"
    row.caption = "a description somebody typed"
    session.commit()
    docreader.read_document_and_store(file_id)
    session.refresh(row)
    assert row.ocr_text == "a reading somebody corrected by hand"
    assert row.caption == "a description somebody typed"


def test_a_missing_row_is_not_an_error(monkeypatch):
    assert docreader.read_document_and_store(9_999_999) is None


def test_an_image_attachment_is_left_to_the_image_path(client, session, monkeypatch):
    from memorymap.core import deps

    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    entry = client.post("/entries", json={"content": "host"}).json()
    made = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    file_id = made.json().get("id") or made.json()["files"][0]["id"]
    assert docreader.read_document_and_store(file_id) is None


def test_the_upload_route_starts_the_pass(client, monkeypatch):
    seen = []
    monkeypatch.setattr(docreader, "read_in_background", lambda fid: seen.append(fid))
    from memorymap.api import routes_files

    monkeypatch.setattr(routes_files.docreader, "read_in_background", lambda fid: seen.append(fid))
    file_id = _attach(client)
    assert seen == [file_id]


def test_the_module_never_leaks_a_path_outside_the_uploads_dir(client, session):
    file_id = _attach(client)
    row = session.get(Attachment, file_id)
    row.stored_name = "../../etc/passwd"
    session.commit()
    assert docreader.read_document_and_store(file_id) is None
    assert Path("/etc/passwd").exists()
