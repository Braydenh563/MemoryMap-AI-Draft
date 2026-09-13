"""Reading an attached file as text, for the in-app viewer.

The property worth guarding here is not any one file type, it is that the
viewer is fed *text* and never a file. `routes_files.media_file` carries the
reason at length (an inline PDF viewer is a script host, and the folder it
serves is not guaranteed to hold only what this app wrote), and a viewer built
by widening an allowlist would re-earn that problem once per type added. So
`GET /files/{id}/text` returns extracted text and `download_file` keeps
handing over bytes as an attachment, and the test that matters most is the
one asserting a file with no viewer still gets a 200 and a message rather than
an error, because a 4xx there would make the UI show a failure for a file that
is perfectly fine.

markitdown is not installed in this environment, so the .docx/.pptx/.xlsx
branch is exercised through its own seam rather than end to end, the standing
caveat about reasoning versus reproducing applies to that branch and is said
here rather than left implicit.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from memorymap.core import docview, pdfpages


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_text_file_is_read_straight_off_disk(tmp_path):
    viewed = docview.extract(_write(tmp_path, "notes.txt", "hello\nthere"))
    assert viewed.text == "hello\nthere"
    assert viewed.kind == "plain"
    assert viewed.source == "file"
    assert not viewed.truncated


def test_markdown_is_flagged_for_markdown_rendering(tmp_path):
    viewed = docview.extract(_write(tmp_path, "readme.md", "# Title"))
    assert viewed.kind == "markdown"


def test_code_is_flagged_for_monospaced_rendering(tmp_path):
    viewed = docview.extract(_write(tmp_path, "thing.py", "x = 1"))
    assert viewed.kind == "code"


def test_a_csv_reads_as_plain_text_not_code(tmp_path):
    """A spreadsheet export is columns to read, not source to inspect."""
    viewed = docview.extract(_write(tmp_path, "rows.csv", "a,b\n1,2"))
    assert viewed.kind == "plain"


def test_a_file_with_no_viewer_says_so_rather_than_failing(tmp_path):
    viewed = docview.extract(_write(tmp_path, "thing.exe", "MZ"))
    assert viewed.text == ""
    assert "no viewer" in viewed.message


def test_a_missing_file_says_so_rather_than_raising(tmp_path):
    """The row can outlive the bytes, a synced data directory, a restore
    that missed the uploads folder. A viewer must not 500 on that."""
    viewed = docview.extract(tmp_path / "gone.txt")
    assert viewed.text == ""
    assert "missing" in viewed.message.lower()


def test_a_long_file_is_clipped_and_says_it_was(tmp_path):
    """A megabyte of extracted text is not read, it is scrolled past once
    and paid for on every open."""
    path = _write(tmp_path, "huge.txt", "x" * (docview.MAX_VIEW_CHARS + 500))
    viewed = docview.extract(path)
    assert viewed.truncated
    assert len(viewed.text) == docview.MAX_VIEW_CHARS


def test_a_bad_byte_does_not_lose_the_whole_file(tmp_path):
    """A log written by two tools routinely has one. Refusing the file over
    it is the wrong trade, the replacement character is visible, so nothing
    is silently altered."""
    path = tmp_path / "mixed.log"
    path.write_bytes(b"before \xff\xfe after")
    viewed = docview.extract(path)
    assert "before" in viewed.text and "after" in viewed.text


def test_the_viewable_set_is_the_union_of_the_four_groups():
    """One thing for a caller to check. A type that passes upload and then
    has no way to be read is the failure this guards."""
    assert docview.VIEWABLE_SUFFIXES == (
        docview.PLAIN_TEXT_SUFFIXES
        | docview.MARKDOWN_SUFFIXES
        | docview.CODE_SUFFIXES
        | docview.CONVERTED_SUFFIXES
    )


def test_a_converted_document_reports_the_install_hint_when_markitdown_is_absent(
    tmp_path, monkeypatch
):
    """Not an error: an answer. The package is installable from inside the
    app (Settings → Optional extras), so the hint is the useful thing to say."""
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: False)
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK\x03\x04not-really-a-docx")
    viewed = docview.extract(path)
    assert viewed.text == ""
    assert "markitdown" in viewed.message


def test_a_converted_document_comes_back_as_markdown(tmp_path, monkeypatch):
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(
        importer, "convert_to_markdown", lambda p: "# Heading\n\nA converted paragraph."
    )
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK\x03\x04")
    viewed = docview.extract(path)
    assert viewed.kind == "markdown"
    assert viewed.source == "converted"
    assert "converted paragraph" in viewed.text


def test_a_file_markitdown_cannot_parse_is_a_message_not_a_500(tmp_path, monkeypatch):
    from memorymap.entry import importer

    def boom(_path):
        raise RuntimeError("not a real docx")

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(importer, "convert_to_markdown", boom)
    path = tmp_path / "broken.docx"
    path.write_bytes(b"nonsense")
    viewed = docview.extract(path)
    assert viewed.text == ""
    assert viewed.message


def test_a_scanned_pdf_falls_through_to_the_vision_reader(tmp_path, monkeypatch):
    """The seam for the scanned-page case. Nothing here touches Tesseract, 
    by direct instruction, scanned pages are the vision model's job."""
    from memorymap.core import pdfpages
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    # What markitdown gives back for a scan: a line of metadata, not nothing,
    # which is why the check is a length floor rather than `if not text`.
    monkeypatch.setattr(importer, "convert_to_markdown", lambda p: "scan.pdf")
    # A real scan has real pages, pdfium can open it fine, it just has no
    # text layer. Monkeypatched rather than left to whatever is actually
    # installed in this environment (a real PDF fixture would make this
    # test's outcome depend on pypdfium2 being present), and explicit so it
    # can't be confused with the "PDFium can't open this at all" case below.
    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "page_count", lambda p: 1)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4")
    viewed = docview.extract(path, vision_reader=lambda p: "The words on the page.")
    assert viewed.source == "vision-ocr"
    assert viewed.text == "The words on the page."


def test_a_scanned_pdf_with_no_vision_reader_says_what_is_missing(tmp_path, monkeypatch):
    """The honest state: the hook exists, and the piece that goes in it, 
    something to turn PDF pages into images, does not ship with this app."""
    from memorymap.core import pdfpages
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(importer, "convert_to_markdown", lambda p: "scan.pdf")
    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "page_count", lambda p: 1)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4")
    viewed = docview.extract(path)
    assert viewed.text == ""
    assert "scan" in viewed.message.lower()


def test_a_pdf_pdfium_cannot_open_says_so_not_probably_a_scan(tmp_path, monkeypatch):
    """The misdiagnosis a real user's own log caught: PDFium refusing a
    corrupted/truncated/encrypted PDF ("Failed to load document (PDFium: Data
    format error)") looks identical to a scan up to this point, markitdown
    also returns nothing useful for it, but sending someone to install a
    vision model does not help a file that cannot be decoded at all."""
    from memorymap.core import pdfpages
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(importer, "convert_to_markdown", lambda p: "")
    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "page_count", lambda p: 0)
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not actually valid")

    # Even with a vision reader on hand, a file PDFium can't open is never
    # reached: there's no image for it to describe.
    called = []
    viewed = docview.extract(path, vision_reader=lambda p: called.append(p) or "text")

    assert called == []
    assert viewed.text == ""
    assert "scan" not in viewed.message.lower()
    assert "couldn't be opened" in viewed.message.lower()


def test_a_vision_reader_that_throws_does_not_break_the_view(tmp_path, monkeypatch):
    from memorymap.core import pdfpages
    from memorymap.entry import importer

    def boom(_path):
        raise RuntimeError("model died")

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(importer, "convert_to_markdown", lambda p: "scan.pdf")
    # A real, openable scan, so this test actually reaches `boom()` rather
    # than being pre-empted by the "PDFium can't open this at all" branch.
    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "page_count", lambda p: 1)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4")
    viewed = docview.extract(path, vision_reader=boom)
    assert viewed.text == ""
    assert viewed.message


# --- the endpoint -------------------------------------------------------------


def _attach(client, name, data: bytes):
    entry = client.post("/entries", json={"content": "A note with a file"}).json()
    response = client.post(
        f"/entries/{entry['id']}/files",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["attachments"][-1]["id"]


def test_reading_an_attached_text_file_through_the_api(client):
    attachment_id = _attach(client, "notes.txt", b"the file's words")
    body = client.get(f"/files/{attachment_id}/text").json()
    assert body["text"] == "the file's words"
    assert body["kind"] == "plain"
    assert body["source"] == "file"
    assert body["filename"] == "notes.txt"


def test_reading_an_attached_code_file_says_to_render_it_as_code(client):
    attachment_id = _attach(client, "app.py", b"import os\n")
    assert client.get(f"/files/{attachment_id}/text").json()["kind"] == "code"


def test_a_type_with_no_viewer_is_a_200_with_a_message(client):
    """A 4xx here would make the viewer show a failure for a file that is
    perfectly fine: it is attached, it downloads, it just has no reader."""
    attachment_id = _attach(client, "bundle.zip", b"PK\x03\x04")
    response = client.get(f"/files/{attachment_id}/text")
    assert response.status_code == 200
    assert response.json()["text"] == ""
    assert response.json()["message"]


def test_reading_an_unknown_attachment_404s(client):
    assert client.get("/files/999999/text").status_code == 404


# --- an attachment's own PDF pages: view without AI, the sibling of the ---
# --- /media/pdf-info /pdf-page pair in test_media_api.py -------------------
#
# Direct instruction, after a note attachment's non-image chip turned out to
# only ever download rather than open: attachments needed the same "view
# real pages, no AI" path the Library's `/media/` uploads got, not a second,
# different dead end.

_ONE_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\nBT /F1 24 Tf 20 40 Td (Hello view) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


def test_attached_pdf_info_404s_for_an_unknown_attachment(client):
    assert client.get("/files/999999/pdf-info").status_code == 404


def test_attached_pdf_info_422s_for_a_non_pdf(client):
    attachment_id = _attach(client, "notes.txt", b"words")
    assert client.get(f"/files/{attachment_id}/pdf-info").status_code == 422


def test_attached_pdf_info_without_the_extra_says_so(client, monkeypatch):
    from memorymap.core import pdfpages

    monkeypatch.setattr(pdfpages, "available", lambda: False)
    attachment_id = _attach(client, "notes.pdf", _ONE_PAGE_PDF)
    payload = client.get(f"/files/{attachment_id}/pdf-info").json()
    assert payload["available"] is False
    assert payload["pages"] == 0


def test_attached_pdf_page_404s_for_a_non_pdf(client):
    attachment_id = _attach(client, "notes.txt", b"words")
    assert client.get(f"/files/{attachment_id}/pdf-page/0").status_code == 404


@pytest.mark.skipif(not pdfpages.available(), reason="the pdfpages extra is not installed")
def test_attached_pdf_page_returns_a_real_png(client):
    attachment_id = _attach(client, "notes.pdf", _ONE_PAGE_PDF)
    info = client.get(f"/files/{attachment_id}/pdf-info").json()
    assert info == {"available": True, "pages": 1, "message": ""}
    page = client.get(f"/files/{attachment_id}/pdf-page/0")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_a_short_word_document_is_not_mistaken_for_a_scan(tmp_path, monkeypatch):
    """The floor that catches a scanned PDF must not catch a short .docx.
    Caught by the test above it on the first version of this module, where the
    floor applied to every converted type: a real document whose text was 36
    characters came back as "probably a scan"."""
    from memorymap.entry import importer

    monkeypatch.setattr(importer, "markitdown_available", lambda: True)
    monkeypatch.setattr(importer, "convert_to_markdown", lambda p: "Short.")
    path = tmp_path / "memo.docx"
    path.write_bytes(b"PK\x03\x04")
    viewed = docview.extract(path)
    assert viewed.source == "converted"
    assert viewed.text == "Short."


def test_the_chat_composers_file_picker_matches_what_import_actually_reads():
    """`POST /documents/import` (routes_documents.py) 415s anything not in
    VIEWABLE_SUFFIXES: caught out of sync during a live audit: the chat
    composer's own `accept=` attribute (index.html's `#chat-image-input`)
    offered `.cs`, which the picker would let through only for the upload to
    then 415, and left out over ten extensions (`.mjs`, `.scss`, `.ppt`,
    `.swift`...) that import would have happily read. This pins the two
    lists to agree, the same drift-guard shape as test_frontend_ids.py for
    ids Python cannot otherwise see the browser check."""
    html = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )
    match = re.search(r'id="chat-image-input"[^>]*\baccept="([^"]+)"', html)
    assert match, "chat-image-input's accept attribute has moved or been removed"
    accepted = {
        token for token in match.group(1).split(",") if token.startswith(".")
    }
    assert accepted == set(docview.VIEWABLE_SUFFIXES)
