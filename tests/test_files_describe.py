"""Describe with AI, on a file that is not a picture.

Reported on 2026-09-09: "the describe with ai button in the files tab doesnt
work. it should be a button for generating a description/summary of the file
from the readable and/or extractable content of the file."

It did not work because both caption routes were written for images: the
media one answered 415 "Only images can be captioned", and the attachment one
415 "Only images and PDFs can be described, there is nothing to look at". A
.md, a .docx, a .csv or a text-layer PDF has its whole content in reach of
`docview`, so describing one needs no vision model at all, only the utility
model that already writes tag suggestions and meeting summaries.

The tests below are the contract: a text file is described from its text, a
scan with no text layer still falls back to the vision reader, and neither
path invents a description when the model has nothing to say.
"""

from __future__ import annotations

import pytest

from memorymap.ai import captioning
from memorymap.api import routes_files
from memorymap.core import deps


class _Ollama:
    def is_running(self):
        return True

    def chat(self, model, messages):
        # The prompt carries the document's own text, which is the whole
        # point: a describer that never sees the content would be a filename
        # paraphraser.
        assert "Some readable content" in messages[-1]["content"]
        return {"content": "A short note about readable content."}


class _Models:
    def utility_model(self):
        return "fake-utility"

    def resolve_vision_model(self, ollama):
        return "fake-vision"


class _SilentOllama(_Ollama):
    def chat(self, model, messages):
        return {"content": "   "}


@pytest.fixture
def entry_id(client):
    return client.post("/entries", json={"content": "host note"}).json()["id"]


def _attach(client, entry_id, name, blob, mime):
    made = client.post(f"/entries/{entry_id}/files", files={"file": (name, blob, mime)})
    assert made.status_code in (200, 201), made.text
    body = made.json()
    return body["id"] if "id" in body else body["files"][0]["id"]


def test_a_text_file_is_described_from_its_own_text(client, entry_id, monkeypatch):
    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    file_id = _attach(client, entry_id, "handout.md", b"# Agents\n\nSome readable content.", "text/markdown")
    got = client.post(f"/files/{file_id}/analyse", json={"kind": "caption"})
    assert got.status_code == 200, got.text
    assert got.json()["caption"] == "A short note about readable content."
    assert got.json()["caption_model"] == "fake-utility"


def test_a_model_with_nothing_to_say_writes_no_description(client, entry_id, monkeypatch):
    monkeypatch.setattr(deps, "get_ollama", _SilentOllama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    file_id = _attach(client, entry_id, "handout.md", b"Some readable content.", "text/markdown")
    got = client.post(f"/files/{file_id}/analyse", json={"kind": "caption"})
    assert got.status_code == 200, got.text
    assert got.json()["caption"] == ""


def test_a_scan_with_no_text_layer_still_falls_back_to_the_vision_reader(
    client, entry_id, monkeypatch
):
    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    monkeypatch.setattr(
        routes_files.vision_ocr,
        "pdf_vision_reader",
        lambda model, ollama: (lambda path: "Page one is a photograph of a whiteboard."),
    )
    # docview finds nothing in this stub PDF, which is exactly a scan.
    file_id = _attach(client, entry_id, "scan.pdf", b"%PDF-1.4\n" + b"0" * 64, "application/pdf")
    got = client.post(f"/files/{file_id}/analyse", json={"kind": "caption"})
    assert got.status_code == 200, got.text
    assert "whiteboard" in got.json()["caption"]


def test_an_already_read_scan_is_described_from_that_reading_not_recaptioned(
    client, entry_id, monkeypatch
):
    """Reported directly: "it used my lfm2.5-vl vision model to do it" on a
    scan the AI document reader had already read fourteen pages of. The
    `readable` fallback checked `ocr_text` (Tesseract) and a fresh
    `docview.extract` and skipped straight to a vision caption of one raw
    page when both were empty, never looking at `vision_ocr_text`, the field
    that exact reading is stored in. If the vision reader below runs at all
    here, this test fails: `describe_document`'s own model call is the only
    one that should fire when a reading already exists.
    """
    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)

    def _must_not_be_called(model, ollama):
        raise AssertionError("the vision reader ran despite an existing vision_ocr_text reading")

    monkeypatch.setattr(routes_files.vision_ocr, "pdf_vision_reader", _must_not_be_called)
    file_id = _attach(client, entry_id, "scan.pdf", b"%PDF-1.4\n" + b"0" * 64, "application/pdf")
    with deps.get_db().session() as session:
        row = session.get(routes_files.Attachment, file_id)
        row.vision_ocr_text = "Page 1: Some readable content.\nPage 2: more of it."
        session.commit()
    got = client.post(f"/files/{file_id}/analyse", json={"kind": "caption", "force": True})
    assert got.status_code == 200, got.text
    assert got.json()["caption"] == "A short note about readable content."
    assert got.json()["caption_model"] == "fake-utility"


def test_a_media_row_that_is_not_an_image_is_described_too(client, monkeypatch):
    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    made = client.post(
        "/media/upload",
        files={"file": ("handout.pdf", b"%PDF-1.4\n" + b"0" * 64, "application/pdf")},
    )
    if made.status_code not in (200, 201):
        pytest.skip("this build's /media/upload does not accept a PDF")
    upload_id = made.json()["id"]
    monkeypatch.setattr(routes_files.docview, "extract", lambda *a, **k: _Extracted())
    got = client.post(f"/media/{upload_id}/caption", json={})
    assert got.status_code == 200, got.text
    assert got.json()["caption"] == "A short note about readable content."


class _Extracted:
    text = "Some readable content."


def test_the_prompt_names_the_file_and_asks_for_two_sentences():
    assert "sentence" in captioning.DOCUMENT_PROMPT.lower()
    assert "no preamble" in captioning.DOCUMENT_PROMPT.lower()


def test_the_prompt_rules_out_a_transcription():
    """Reported: the description "needs to be an actual description or summary
    of what the file is about and includes, not a transcription".

    A small local model handed two thousand characters of a document and told
    to describe it will very often hand back the opening of that document,
    lightly reworded. `PAGE_CAPTION_PROMPT` already answers this for rendered
    pages with an explicit clause; this asserts the document prompt carries the
    same one, and that it asks for what the file contains rather than only what
    it is about, which is the other half of the report.
    """
    prompt = captioning.DOCUMENT_PROMPT.lower()
    assert "do not transcribe" in prompt
    assert "contains" in prompt
    assert "no bullet list" in prompt
