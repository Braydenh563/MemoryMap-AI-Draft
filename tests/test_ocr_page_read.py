"""Reading one page of a document with the vision model.

The OCR workspace's own reader (`POST /{files,media}/{id}/ocr-page-read`). Page
-scoped deliberately: the whole-document vision path exists already and reads up
to `pdfpages.MAX_PAGES`, which is the wrong shape for a workspace where the
question is always "what does *this* page say" and a reader who wants page six
should not wait through five they have already checked.

Nothing is stored: a wrong transcription written onto the row is worse than one
to repeat: so these tests are about the refusals and the routing, which is
where a page reader can actually mislead.
"""

from __future__ import annotations

import io

import pytest

from memorymap.core import pdfpages

ONE_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 24 Tf 20 40 Td (Hello OCR) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


def _attach(client, name: str, data: bytes) -> int:
    created = client.post("/entries", json={"content": "host note"}).json()
    upload = client.post(
        f"/entries/{created['id']}/files",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )
    assert upload.status_code == 201, upload.text
    return upload.json()["attachments"][-1]["id"]


def test_only_a_pdf_is_read_a_page_at_a_time(client):
    """An image *is* one page, it goes through the ordinary vision read, and
    offering a page-scoped route for it would imply a page rail that does not
    exist."""
    attachment_id = _attach(client, "photo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    response = client.post(f"/files/{attachment_id}/ocr-page-read?page=0")
    assert response.status_code == 415


def test_a_missing_model_is_a_409_not_a_500(client):
    """The commonest state on this machine: no Ollama running. The workspace
    shows the message; a 500 would show a stack trace to somebody whose only
    problem is that they have not started their model server."""
    if not pdfpages.available():
        pytest.skip("the pdfpages extra is not installed")
    attachment_id = _attach(client, "scan.pdf", ONE_PAGE_PDF)
    response = client.post(f"/files/{attachment_id}/ocr-page-read?page=0")
    assert response.status_code == 409
    assert "model" in response.json()["detail"].lower()


def test_without_the_rasteriser_it_answers_rather_than_failing(client, monkeypatch):
    """No pypdfium2 means no pixels to read, which is a *state* rather than an
    error: the reader is told what to install, in the response body, at 200."""
    monkeypatch.setattr(pdfpages, "available", lambda: False)
    attachment_id = _attach(client, "scan.pdf", ONE_PAGE_PDF)
    response = client.post(f"/files/{attachment_id}/ocr-page-read?page=0")
    assert response.status_code == 200
    assert "rasteriser" in response.json()["message"]
    assert response.json()["text"] == ""


def test_an_unknown_attachment_is_a_404(client):
    assert client.post("/files/9999/ocr-page-read?page=0").status_code == 404
