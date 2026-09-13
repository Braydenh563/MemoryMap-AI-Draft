"""The caption and vision readings of an uploaded PDF.

Reported with a traceback: "generate a caption" on a PDF answered 500 with
"'function' object has no attribute 'read'". `pdf_vision_reader` returns the
reader callable itself (docview's `vision_reader` contract), and the route
called `.read(path)` on it. Both PDF branches of the route go through the
fake reader here, so the shape cannot come back.
"""

from __future__ import annotations

import pytest

from memorymap.api import routes_files
from memorymap.core import deps


class _Ollama:
    def is_running(self):
        return True


class _Models:
    def resolve_vision_model(self, ollama):
        return "fake-vision"


@pytest.fixture
def pdf_attachment(client, monkeypatch):
    # The classes themselves, not lambdas around them: calling a class is
    # already a factory (CodeQL's "unnecessary lambda").
    monkeypatch.setattr(deps, "get_ollama", _Ollama)
    monkeypatch.setattr(deps, "get_model_manager", _Models)
    monkeypatch.setattr(
        routes_files.vision_ocr,
        "pdf_vision_reader",
        lambda model, ollama: (lambda path: "Page one says hello."),
    )
    created = client.post("/entries", json={"content": "host note"}).json()
    files = {"file": ("scan.pdf", b"%PDF-1.4\n" + b"0" * 64, "application/pdf")}
    upload = client.post(f"/entries/{created['id']}/files", files=files)
    assert upload.status_code in (200, 201), upload.text
    body = upload.json()
    return body["id"] if "id" in body else body["files"][0]["id"]


def test_a_pdf_caption_reads_the_pages_instead_of_crashing(client, pdf_attachment):
    response = client.post(f"/files/{pdf_attachment}/analyse", json={"kind": "caption", "force": True})
    assert response.status_code == 200, response.text
    assert response.json()["caption"] == "Page one says hello."


def test_a_pdf_vision_reading_reads_the_pages_instead_of_crashing(client, pdf_attachment):
    response = client.post(f"/files/{pdf_attachment}/analyse", json={"kind": "vision", "force": True})
    assert response.status_code == 200, response.text
    assert response.json()["vision_ocr_text"] == "Page one says hello."
