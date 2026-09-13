"""The OCR workspace, pointed at a document rather than a picture.

Reported: *"I begin generating ocr for a document… is the document ocr even
working??"*, and it was not. `core/ocr.py`'s `OCR_SUFFIXES` is raster formats
only (Tesseract cannot open a PDF), and both region routes refused anything
outside it with a 415, so the one window in this app built for reading a
document was the one window a document could not be opened in.

Nothing new reads text here: `core/pdfpages.py` already rendered a page to PNG
for the file viewer, and `ocr.extract_regions` already read a PNG. These tests
cover the join, and the two honest answers it has to give when there is no
Tesseract on the machine, which is the normal case for this project, by
instruction ("I basically dont want to download tesseract").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memorymap.api.routes_files import _pdf_regions_for
from memorymap.core import pdfpages

TWO_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 6 0 R]/Count 2>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 24 Tf 20 40 Td (Page one) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"6 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 7 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"7 0 obj<</Length 44>>stream\nBT /F1 24 Tf 20 40 Td (Page two) Tj ET\n"
    b"endstream endobj\n"
    b"trailer<</Root 1 0 R>>"
)

needs_pdfium = pytest.mark.skipif(
    not pdfpages.available(), reason="the pdfpages extra is not installed"
)


@pytest.fixture()
def two_pages(tmp_path) -> Path:
    path = tmp_path / "lecture.pdf"
    path.write_bytes(TWO_PAGE_PDF)
    return path


@needs_pdfium
def test_a_pdf_reports_its_page_count(two_pages: Path):
    """The workspace builds its page rail from this number, so it has to come
    back on every page, not only on the first request."""
    assert _pdf_regions_for(two_pages, 0, "", "").pages == 2
    assert _pdf_regions_for(two_pages, 1, "", "").pages == 2


@needs_pdfium
def test_the_page_asked_for_is_echoed_and_clamped(two_pages: Path):
    """Page 99 of a 2-page document is page 2, and the caller is told so, a
    rail that highlighted the page it *asked* for would point at the wrong
    thumbnail for the picture on screen."""
    assert _pdf_regions_for(two_pages, 1, "", "").page == 1
    assert _pdf_regions_for(two_pages, 99, "", "").page == 1
    assert _pdf_regions_for(two_pages, -4, "", "").page == 0


@needs_pdfium
def test_without_tesseract_it_points_at_the_button_and_not_at_an_install(
    two_pages: Path, monkeypatch
):
    """Never "install Tesseract": this project was told directly to use a
    vision model for scanned documents, and the workspace has a button for
    exactly that. A message naming a remedy the reader cannot act on is how a
    working feature gets reported as broken."""
    monkeypatch.setattr("memorymap.core.ocr.tesseract_available", lambda: False)
    out = _pdf_regions_for(two_pages, 0, "", "")
    assert out.source == "none"
    assert "Read this page" in out.message
    assert "Tesseract" not in out.message


@needs_pdfium
def test_with_tesseract_installed_both_readers_are_offered(two_pages: Path, monkeypatch):
    """The other half of the same rule, and the later instruction, *"make sure
    tesseract exists as an alternative as well"*. When it **is** on the machine
    it is named, because then it is a choice rather than an errand: no model
    needed, and it marks where each block sits.

    `extract_regions` is stubbed to None separately from `tesseract_available`:
    the two answer different questions (is the binary here / did it find
    anything on *this* page), and a page it read successfully would not reach
    the `source == "none"` branch this message lives in at all."""
    monkeypatch.setattr("memorymap.core.ocr.tesseract_available", lambda: True)
    monkeypatch.setattr("memorymap.core.ocr.extract_regions", lambda path: None)
    out = _pdf_regions_for(two_pages, 0, "", "")
    assert out.source == "none"
    assert "Read this page" in out.message
    assert "Tesseract" in out.message


@needs_pdfium
def test_a_stored_reading_stands_in_for_the_first_page_only(two_pages: Path, monkeypatch):
    """A document's stored reading belongs to the *document*. Offering it as
    page 7's sections would be the app stating a guess about where the text
    came from as a fact, the same line the source badge exists to hold.

    (The badge is "reading" now, not "stored-text": without Tesseract the
    reading is split into its own typed blocks rather than returned as one
    whole-page region. What is being pinned here is unchanged, page 2 gets
    nothing, because page 1's text is not page 2's.)
    """
    monkeypatch.setattr("memorymap.core.ocr.tesseract_available", lambda: False)
    first = _pdf_regions_for(two_pages, 0, "Some text read earlier", "Read by a model")
    assert first.source == "reading"
    assert first.regions[0].text == "Some text read earlier"
    later = _pdf_regions_for(two_pages, 1, "Some text read earlier", "Read by a model")
    assert later.source == "none"


def test_without_the_rasteriser_it_says_so_rather_than_failing(two_pages: Path, monkeypatch):
    monkeypatch.setattr(pdfpages, "available", lambda: False)
    out = _pdf_regions_for(two_pages, 0, "", "")
    assert out.source == "none"
    assert out.pages == 0
    assert "rasteriser" in out.message
