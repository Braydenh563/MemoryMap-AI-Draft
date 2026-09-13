"""Rasterising a PDF page, so a vision model can read a scan.

`core/docview.py` used to carry a docstring explaining that this could not
work: it takes a `vision_reader`, `ai/vision_ocr.py` reads images, and nothing
turned a PDF page into one. The seam was built and the plug did not exist.

pypdfium2 was then actually installed and measured, ~16 MB, no system
packages, no torch, about 20 ms a page, so the plug exists now. These tests
cover the two things that matter: it degrades to nothing when the optional
library is absent, and it never raises at a caller that has to return a page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memorymap.ai import vision_ocr
from memorymap.core import pdfpages

# The smallest legal PDF that still renders text, built by hand so the suite
# carries no binary fixture.
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

needs_pdfium = pytest.mark.skipif(
    not pdfpages.available(), reason="the pdfpages extra is not installed"
)


@pytest.fixture()
def one_page(tmp_path) -> Path:
    path = tmp_path / "scan.pdf"
    path.write_bytes(ONE_PAGE_PDF)
    return path


# --- it must never take down its caller ----------------------------------------


def test_a_missing_file_is_no_pages_rather_than_an_exception(tmp_path):
    assert pdfpages.render_pages(tmp_path / "nope.pdf") == []
    assert pdfpages.page_count(tmp_path / "nope.pdf") == 0


def test_a_file_that_is_not_a_pdf_is_no_pages(tmp_path):
    junk = tmp_path / "not.pdf"
    junk.write_bytes(b"this is not a PDF at all")
    assert pdfpages.render_pages(junk) == []


def test_a_truncated_pdf_is_no_pages(tmp_path):
    half = tmp_path / "half.pdf"
    half.write_bytes(ONE_PAGE_PDF[: len(ONE_PAGE_PDF) // 2])
    assert pdfpages.render_pages(half) == []


def test_without_the_extra_nothing_happens_and_nothing_breaks(one_page, monkeypatch):
    """The library is optional and stays optional, this is the path every
    install that never presses the button takes."""
    monkeypatch.setattr(pdfpages, "available", lambda: False)
    assert pdfpages.render_pages(one_page) == []
    assert pdfpages.page_count(one_page) == 0


# --- and when it is there, it must actually render ------------------------------


@needs_pdfium
def test_a_page_renders_to_a_png(one_page):
    pages = pdfpages.render_pages(one_page)
    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


@needs_pdfium
def test_only_the_first_few_pages_are_ever_rendered(one_page):
    """A vision model reads a page in seconds, so a 300-page scan would be an
    hour of GPU time nobody asked for."""
    assert pdfpages.MAX_PAGES <= 16
    assert pdfpages.render_pages(one_page, limit=0) == []


@needs_pdfium
def test_an_absurdly_large_page_is_skipped_rather_than_allocated(one_page, monkeypatch):
    """A 40 KB PDF can declare a page a metre wide; rendering it at 2x is
    gigabytes of bitmap in one allocation."""
    monkeypatch.setattr(pdfpages, "MAX_PIXELS", 1)
    assert pdfpages.render_pages(one_page) == []


# --- render_page: one page, for the viewer, independent of MAX_PAGES -----------


def test_render_page_without_the_extra_is_none(one_page, monkeypatch):
    monkeypatch.setattr(pdfpages, "available", lambda: False)
    assert pdfpages.render_page(one_page, 0) is None


def test_render_page_on_a_missing_file_is_none(tmp_path):
    assert pdfpages.render_page(tmp_path / "nope.pdf", 0) is None


@needs_pdfium
def test_render_page_renders_to_a_png(one_page):
    png = pdfpages.render_page(one_page, 0)
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


@needs_pdfium
def test_render_page_out_of_range_is_none(one_page):
    assert pdfpages.render_page(one_page, 5) is None




# --- the whole path, which is what was actually missing -------------------------


class _FakeOllama:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, model, messages, **kwargs):
        self.calls += 1
        return {"content": self.reply}


@needs_pdfium
def test_a_scanned_pdf_reaches_the_vision_model(one_page):
    """`docview` always took a vision_reader and its only caller always passed
    None, so this whole path was wired and had never once run."""
    fake = _FakeOllama("Hello OCR")
    read = vision_ocr.pdf_vision_reader("some-vision-model", fake)
    assert read(one_page) == "Hello OCR"
    assert fake.calls == 1


@needs_pdfium
def test_a_model_that_finds_nothing_yields_nothing(one_page):
    read = vision_ocr.pdf_vision_reader("m", _FakeOllama(""))
    assert read(one_page) == ""


def test_the_reader_survives_a_file_it_cannot_open(tmp_path):
    read = vision_ocr.pdf_vision_reader("m", _FakeOllama("x"))
    assert read(tmp_path / "gone.pdf") == ""


@needs_pdfium
def test_the_extras_catalogue_offers_it(one_page):
    from memorymap.core import extras

    entry = extras.EXTRAS_BY_ID["pdfpages"]
    assert entry.module == "pypdfium2"
    assert "Pillow" in entry.packages
    # It must not claim to read anything by itself, a model is still needed.
    assert "model" in entry.caveat.lower()


# --- concurrent access must not corrupt PDFium's C-level state -----------------
#
# Reported live, from a real multi-page PDF viewed through the new lightbox:
# several pages 404ing at once and "it crashed... i couldnt scroll." FastAPI's
# sync routes run in an anyio threadpool, and a browser fetches every page
# `<img>` on a viewed PDF roughly at once, reproduced directly below,
# without any FastAPI involved: hammering `render_page` from several threads
# at once, even against independently-opened `PdfDocument`s, corrupted
# PDFium's heap and aborted the whole process (`corrupted double-linked
# list`, SIGABRT) before `_pdfium_lock` existed. A crash like that cannot be
# asserted on with pytest.raises, the process is gone, not an exception , 
# so the only test that means anything here is "many threads, zero
# failures, still running afterwards."

_MULTI_PAGE_PDF_PAGES = 15


def _make_multipage_pdf(n: int) -> bytes:
    objs = [b"<</Type/Catalog/Pages 2 0 R>>"]
    kids = " ".join(f"{3 + i} 0 R" for i in range(n))
    objs.append(f"<</Type/Pages/Kids[{kids}]/Count {n}>>".encode())
    for _ in range(n):
        objs.append(
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]"
            f"/Contents {3 + n} 0 R/Resources<</Font<</F1 {4 + n} 0 R>>>>>>".encode()
        )
    stream = b"BT /F1 24 Tf 20 40 Td (Hello) Tj ET"
    objs.append(f"<</Length {len(stream)}>>stream\n".encode() + stream + b"\nendstream")
    objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    out = bytearray(b"%PDF-1.4\n")
    for index, body in enumerate(objs, start=1):
        out += f"{index} 0 obj".encode() + body + b"endobj\n"
    out += f"trailer<</Root 1 0 R/Size {len(objs) + 1}>>".encode()
    return bytes(out)


@pytest.fixture()
def multi_page(tmp_path) -> Path:
    path = tmp_path / "multi.pdf"
    path.write_bytes(_make_multipage_pdf(_MULTI_PAGE_PDF_PAGES))
    return path


@needs_pdfium
def test_concurrent_page_renders_do_not_corrupt_or_crash(multi_page):
    import concurrent.futures

    assert pdfpages.page_count(multi_page) == _MULTI_PAGE_PDF_PAGES

    results: dict[int, bool] = {}

    def render(job: tuple[int, int]) -> None:
        index, attempt = job
        png = pdfpages.render_page(multi_page, index)
        results[(index, attempt)] = png is not None and png.startswith(b"\x89PNG\r\n\x1a\n")

    # Every page, hammered from several threads at once, several times each
    #, the shape that reproduced the crash (a browser requesting every
    # `<img>` on a multi-page PDF roughly simultaneously).
    jobs = [(index, attempt) for attempt in range(4) for index in range(_MULTI_PAGE_PDF_PAGES)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(render, jobs))

    assert len(results) == len(jobs)
    assert all(results.values()), {k: v for k, v in results.items() if not v}
