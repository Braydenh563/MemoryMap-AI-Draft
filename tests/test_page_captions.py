"""Captioning for documents, not photographs (UI_MODERNISATION_PLAN Phase 7.3).

Reported directly:

    "image captioning, how it is done and displayed needs to be refined for
     pdf documents and other similar documents. with graphs, images and
     diagrams in them."

`ai/captioning.py`'s one prompt asks "what does this image show", which is the
right question for a photograph and produces the same useless sentence for
every page of a slide deck, *"a white page with black text and a bar chart"*.
And there was one caption *per file*, so a twenty-page deck had one line about
"the document" and nothing about any of its figures.

Two things are checked here, and both are checkable without a model: what the
prompt actually asks for, and that a description is stored per page beside that
page's reading rather than over the file's own caption.

**Every model call in this file goes through the fake transport** (`fake_ollama`
- see tests/fakes.py). There is no vision model in this sandbox, so what a real
one would *answer* to this prompt is not covered by anything here; what is
covered is that the right prompt reaches it, carrying the right page number,
and that the answer lands in the right column.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from memorymap.ai import captioning
from memorymap.api import routes_files
from memorymap.core import deps, pdfpages
from memorymap.core.database import PageRead

#: The same hand-written one-page PDF `test_ocr_page_reads_persist.py` uses: 
#: pdfium repairs the missing xref table, so this is a real, openable document
#: without a binary fixture in the tree.
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


# --- the prompt ---------------------------------------------------------------


def test_the_page_prompt_says_which_page_of_how_many():
    """The one piece of context a rendered page cannot carry itself, and the
    thing that stops the answer describing the document instead of the page."""
    prompt = captioning.page_caption_prompt(3, 18)
    assert "page 4 of 18" in prompt.lower(), "one-based, like the page rail"


def test_the_page_prompt_asks_for_figures_and_not_for_a_photograph():
    prompt = captioning.page_caption_prompt(0, 1).lower()
    for subject in ("figures", "charts", "diagrams", "tables"):
        assert subject in prompt
    assert "not a photograph" in prompt
    assert "do not transcribe" in prompt, (
        "vision_ocr.py already asks for the words; asking one call for both "
        "gets a worse version of each"
    )


def test_the_page_prompt_is_not_the_photograph_prompt():
    """If these ever became the same string the whole item would have shipped
    as a no-op that still passed every other test in this file."""
    assert captioning.page_caption_prompt(0, 1) != captioning.CAPTION_PROMPT


def test_page_caption_text_sends_the_page_prompt_with_the_image(tmp_path, fake_ollama):
    page = tmp_path / "page-2.png"
    page.write_bytes(b"\x89PNG\r\n\x1a\n")
    answer = captioning.page_caption_text(page, 1, 9, "llava", fake_ollama)
    assert answer == fake_ollama.librarian_reply
    sent = fake_ollama.chat_calls[-1][-1]
    assert "page 2 of 9" in sent["content"].lower()
    assert sent["images"][0].startswith("data:image/png;base64,")


def test_page_caption_text_never_raises_when_the_backend_errors(tmp_path):
    class _BrokenOllama:
        def chat(self, model, messages):
            raise RuntimeError("boom")

    page = tmp_path / "page-1.png"
    page.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert captioning.page_caption_text(page, 0, 1, "llava", _BrokenOllama()) == ""


def test_page_caption_text_never_raises_on_a_file_that_is_not_there(fake_ollama):
    missing = Path("no") / "such" / "page.png"
    assert captioning.page_caption_text(missing, 0, 1, "llava", fake_ollama) == ""


# --- per-page storage ---------------------------------------------------------


def _stub_describe(monkeypatch, text="Figure 2 compares three regions."):
    """The model round-trip, replaced. Everything below this line is about
    where the answer goes, not about what a model would say."""
    monkeypatch.setattr(
        routes_files,
        "_describe_page",
        lambda path, index, key=None: routes_files._remember_page_caption(
            key, index, text, "stub-vision"
        )
        or routes_files.OcrPageReadOut(page=index, caption=text, caption_model="stub-vision"),
    )


def test_a_page_description_is_stored_on_that_page(client, monkeypatch):
    attachment_id = _attach(client, "deck.pdf", ONE_PAGE_PDF)
    if not pdfpages.available():
        pytest.skip("the PDF rasteriser extra is not installed here")
    _stub_describe(monkeypatch)

    described = client.post(f"/files/{attachment_id}/page-caption?page=0")
    assert described.status_code == 200, described.text
    assert described.json()["caption"] == "Figure 2 compares three regions."

    with deps.get_db().session() as session:
        rows = session.query(PageRead).filter(PageRead.source_id == attachment_id).all()
        assert [(r.page, r.caption, r.caption_model) for r in rows] == [
            (0, "Figure 2 compares three regions.", "stub-vision")
        ]


def test_a_description_does_not_overwrite_that_page_s_reading(client, monkeypatch):
    """The two are different claims about the same page, what it *says* and
    what its figures *show*, and neither may clear the other."""
    attachment_id = _attach(client, "deck.pdf", ONE_PAGE_PDF)
    if not pdfpages.available():
        pytest.skip("the PDF rasteriser extra is not installed here")
    monkeypatch.setattr(
        routes_files,
        "_vision_read_page",
        lambda path, index, reader="vision": routes_files.OcrPageReadOut(
            page=index, text="The words on the page.", model="stub-reader"
        ),
    )
    client.post(f"/files/{attachment_id}/ocr-page-read?page=0")
    _stub_describe(monkeypatch)
    client.post(f"/files/{attachment_id}/page-caption?page=0")

    body = client.get(f"/files/{attachment_id}/page-reads").json()
    assert len(body["pages"]) == 1
    page = body["pages"][0]
    assert page["text"] == "The words on the page."
    assert page["caption"] == "Figure 2 compares three regions."
    assert page["model"] == "stub-reader"
    assert page["caption_model"] == "stub-vision"


def test_a_page_that_is_only_described_is_not_reported_as_read(client, monkeypatch):
    """The Files badge, the workspace and the lightbox's page chips all read
    this count. A described-but-unread page saying "read" would promise a
    transcription that does not exist."""
    attachment_id = _attach(client, "deck.pdf", ONE_PAGE_PDF)
    if not pdfpages.available():
        pytest.skip("the PDF rasteriser extra is not installed here")
    _stub_describe(monkeypatch)
    client.post(f"/files/{attachment_id}/page-caption?page=0")

    body = client.get(f"/files/{attachment_id}/page-reads").json()
    assert body["read"] == 0
    assert body["pages"][0]["caption"]
    assert body["pages"][0]["text"] == ""


def test_the_upload_side_has_the_same_route(client, monkeypatch):
    """Two id spaces, two routes, one implementation, the same shape every
    other page endpoint in routes_files.py keeps."""
    upload = client.post(
        "/media/upload",
        files={"file": ("deck.pdf", io.BytesIO(ONE_PAGE_PDF), "application/pdf")},
    )
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["id"]
    if not pdfpages.available():
        pytest.skip("the PDF rasteriser extra is not installed here")
    _stub_describe(monkeypatch, "A scatter plot of cost against headcount.")

    described = client.post(f"/media/{upload_id}/page-caption?page=0")
    assert described.status_code == 200, described.text
    stored = client.get(f"/media/{upload_id}/page-reads").json()
    assert stored["pages"][0]["caption"] == "A scatter plot of cost against headcount."


def test_only_a_pdf_can_be_described_by_page(client):
    """A photograph has one page and `POST /media/{id}/caption` already
    describes it: a page-caption route that answered for it would be a second
    way to write the same field."""
    attachment_id = _attach(client, "photo.png", b"\x89PNG\r\n\x1a\n")
    refused = client.post(f"/files/{attachment_id}/page-caption?page=0")
    assert refused.status_code == 415


def test_describing_a_page_needs_a_model_and_says_so(client, fake_ollama, monkeypatch):
    """No vision model installed is an ordinary state on a fresh notebook, and
    the message has to name the fix rather than failing silently."""
    attachment_id = _attach(client, "deck.pdf", ONE_PAGE_PDF)
    if not pdfpages.available():
        pytest.skip("the PDF rasteriser extra is not installed here")
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_vision_model", lambda ollama: None, raising=False
    )
    refused = client.post(f"/files/{attachment_id}/page-caption?page=0")
    assert refused.status_code == 409
    assert "see images" in refused.json()["detail"]
