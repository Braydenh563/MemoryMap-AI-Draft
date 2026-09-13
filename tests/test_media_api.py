"""`/media`: uploads are tracked, not just written to disk, and the folder is
not a script host, asked for and found directly (§40 open item 6).

Split out of test_antigravity_regressions.py.
"""

from __future__ import annotations

import pytest

from memorymap.api import routes_files
from memorymap.core import pdfpages


def test_media_upload_does_not_process_a_staged_upload_by_default(ai_client, monkeypatch):
    """Asked for directly, correcting this session's own earlier choice:
    "the OCR shouldn't happen to staged files, only when they are actually
    saved as a note, actually sent in a chat message, or uploaded directly
    to the library." A plain upload (no `direct`) is the staged case, 
    OCR/captioning/vision-OCR must not run until something actually
    commits it (see test_media_process.py for those trigger points)."""
    calls = []
    monkeypatch.setattr(
        routes_files.media_process,
        "process_committed_upload",
        lambda upload, media_dir: calls.append(upload.id),
    )
    response = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    assert response.status_code == 200
    assert calls == []


def test_media_upload_with_direct_processes_immediately(ai_client, monkeypatch):
    """The Library's own "Upload images" button has no separate staging
    step: the upload itself is the commit, so `direct=true` (the form
    field it sends) processes right away, same as every upload used to."""
    calls = []
    monkeypatch.setattr(
        routes_files.media_process,
        "process_committed_upload",
        lambda upload, media_dir: calls.append(upload.id),
    )
    response = ai_client.post(
        "/media/upload",
        files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"direct": "true"},
    )
    assert response.status_code == 200
    assert calls == [response.json()["id"]]


def test_media_upload_never_processes_a_pdf_even_with_direct(ai_client, monkeypatch):
    """process_committed_upload itself guards by suffix (OCR_SUFFIXES etc.)
    - a PDF upload reaching it is a no-op, not an error; covered directly
    in test_media_process.py. This just confirms `direct=true` doesn't
    bypass the 415 that already refuses non-image/PDF types elsewhere."""
    response = ai_client.post(
        "/media/upload",
        files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")},
        data={"direct": "true"},
    )
    assert response.status_code == 200


def test_media_list_and_upload_include_ocr_text(ai_client):
    """`ocr_text` is always a string over the wire, never null, so the
    frontend gallery's substring filter never needs a null check."""
    response = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    listed = ai_client.get("/media").json()
    row = next(r for r in listed if r["id"] == response.json()["id"])
    assert row["ocr_text"] == ""


# --- manual OCR retry + edit (core/ocr.py) -----------------------------------


def test_ocr_media_retries_extraction(ai_client, monkeypatch):
    """Asked for directly: "allow for manual OCR extraction or retries."
    ocr.extract_and_store has no write-once guard, so a plain POST always
    re-reads the image: this only checks the retry actually ran and its
    result made it back onto the row (see test_ocr.py for extract_text
    itself)."""
    import memorymap.core.ocr as ocr_module

    monkeypatch.setattr(ocr_module, "extract_text", lambda path: "retried text")
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]

    response = ai_client.post(f"/media/{upload_id}/ocr")
    assert response.status_code == 200
    assert response.json()["ocr_text"] == "retried text"


def test_ocr_media_can_be_edited_by_hand(ai_client):
    """"allow the user to access, view, and edit OCR extracted text", same
    manual-text-override shape as CaptionBody.text."""
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]

    response = ai_client.post(f"/media/{upload_id}/ocr", json={"text": "corrected by hand"})
    assert response.status_code == 200
    assert response.json()["ocr_text"] == "corrected by hand"

    listed = ai_client.get("/media").json()
    row = next(r for r in listed if r["id"] == upload_id)
    assert row["ocr_text"] == "corrected by hand"


def test_ocr_media_clears_with_empty_text(ai_client):
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/ocr", json={"text": "something"})

    response = ai_client.post(f"/media/{upload_id}/ocr", json={"text": "   "})
    assert response.json()["ocr_text"] == ""


def test_ocr_media_refuses_a_pdf(ai_client):
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/ocr")
    assert response.status_code == 415


def test_ocr_media_404s_for_an_unknown_id(ai_client):
    assert ai_client.post("/media/999999/ocr").status_code == 404


def test_media_upload_refuses_anything_that_is_not_an_image(ai_client):
    """`/media/{name}` serves from the app's own origin, so an .html or .svg
    landing here runs with the notebook's token rather than being a picture.
    The AI can write into this folder too, which is what makes it worth
    closing on a single-user local app."""
    for name, mime in [("x.html", "text/html"), ("x.svg", "image/svg+xml")]:
        response = ai_client.post(
            "/media/upload", files={"file": (name, b"<svg onload=alert(1)>", mime)}
        )
        assert response.status_code == 415, name


def test_media_upload_still_takes_a_png(ai_client):
    response = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    assert response.status_code == 200
    assert response.json()["url"].startswith("/media/")


def test_an_upload_is_tracked_listed_and_deletable(ai_client):
    """An image pasted into a note's own markdown had no DB row at all, it
    could not be listed in a gallery, could not be deleted, and there was
    no way to tell "still referenced" apart from "already gone off disk"
    (ROADMAP.md item 20a). `MediaUpload` closes that gap for every upload,
    not just whiteboard image objects."""
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()

    listed = ai_client.get("/media").json()
    assert any(row["url"] == uploaded["url"] and row["original_name"] == "photo.png" for row in listed)

    upload_id = next(row["id"] for row in listed if row["url"] == uploaded["url"])
    deleted = ai_client.delete(f"/media/{upload_id}")
    assert deleted.status_code == 200

    # The row and the file are both gone.
    assert not any(row["id"] == upload_id for row in ai_client.get("/media").json())
    assert ai_client.get(uploaded["url"]).status_code == 404


def test_deleting_an_unknown_upload_404s(ai_client):
    # CodeQL py/side-effect-in-assert: the DELETE call is a side effect, and
    # an assert's own expression is skipped entirely under `python -O`, 
    # split so the request always fires regardless of optimization flags.
    response = ai_client.delete("/media/999999")
    assert response.status_code == 404


def test_media_is_served_with_a_disposition_header(ai_client):
    url = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["url"]
    served = ai_client.get(url)
    assert served.status_code == 200
    assert "inline" in served.headers["content-disposition"]


def test_a_dangerous_file_already_on_disk_is_still_not_served(ai_client, app_state):
    """Upload is not the only way into this folder, a restored backup or a
    synced data directory is another, so the suffix is checked on the way out
    as well as on the way in."""
    media = app_state.data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "evil.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    assert ai_client.get("/media/evil.html").status_code == 404


# --- captioning (ai/captioning.py) -------------------------------------------


def test_media_upload_still_accepts_a_pdf_without_direct(ai_client):
    """A staged PDF upload, nothing here processes it either way (PDFs
    aren't in any of the three SUFFIXES sets yet), but the 415 gate for
    "is this an accepted type at all" must still pass it regardless of
    `direct`."""
    response = ai_client.post(
        "/media/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert response.status_code == 200


def test_media_list_and_upload_include_caption(ai_client):
    response = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    listed = ai_client.get("/media").json()
    row = next(r for r in listed if r["id"] == response.json()["id"])
    assert row["caption"] == ""


def test_caption_media_generates_a_caption(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/caption")
    assert response.status_code == 200
    assert response.json()["caption"] == fake_ollama.librarian_reply


def test_caption_media_wont_rewrite_without_force(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/caption")
    calls_before = len(fake_ollama.chat_calls)
    response = ai_client.post(f"/media/{upload_id}/caption")
    assert response.status_code == 200
    assert len(fake_ollama.chat_calls) == calls_before  # never asked the model again


def test_caption_media_force_regenerates(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/caption")
    calls_before = len(fake_ollama.chat_calls)
    response = ai_client.post(f"/media/{upload_id}/caption", json={"force": True})
    assert response.status_code == 200
    assert len(fake_ollama.chat_calls) == calls_before + 1


def test_caption_media_refuses_a_pdf(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/caption")
    assert response.status_code == 415


def test_caption_media_reports_no_vision_model_available(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = []  # nothing declares vision
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/caption")
    assert response.status_code == 409


def test_caption_media_404s_for_an_unknown_id(ai_client, fake_ollama):
    assert ai_client.post("/media/999999/caption").status_code == 404


# --- vision OCR (ai/vision_ocr.py) -------------------------------------------


def test_media_list_and_upload_include_vision_ocr_fields(ai_client):
    response = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    )
    listed = ai_client.get("/media").json()
    row = next(r for r in listed if r["id"] == response.json()["id"])
    assert row["vision_ocr_text"] == ""
    assert row["vision_ocr_model"] == ""


def test_vision_ocr_media_reads_text(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    fake_ollama.librarian_reply = "Room 204"
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/vision-ocr")
    assert response.status_code == 200
    assert response.json()["vision_ocr_text"] == "Room 204"
    assert response.json()["vision_ocr_model"]


def test_vision_ocr_media_wont_reread_without_force(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/vision-ocr")
    calls_before = len(fake_ollama.chat_calls)
    response = ai_client.post(f"/media/{upload_id}/vision-ocr")
    assert response.status_code == 200
    assert len(fake_ollama.chat_calls) == calls_before


def test_vision_ocr_media_force_rereads(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/vision-ocr")
    calls_before = len(fake_ollama.chat_calls)
    response = ai_client.post(f"/media/{upload_id}/vision-ocr", json={"force": True})
    assert response.status_code == 200
    assert len(fake_ollama.chat_calls) == calls_before + 1


def test_vision_ocr_media_refuses_a_pdf(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/vision-ocr")
    assert response.status_code == 415


def test_vision_ocr_media_reports_no_vision_model_available(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = []
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/vision-ocr")
    assert response.status_code == 409


def test_vision_ocr_media_404s_for_an_unknown_id(ai_client, fake_ollama):
    assert ai_client.post("/media/999999/vision-ocr").status_code == 404


# --- manual caption input, asked for directly --------------------------------


def test_a_caption_can_be_typed_by_hand(ai_client, fake_ollama):
    """`text` sets the caption directly and needs no model at all, a
    person editing a caption is not asking for a second opinion."""
    fake_ollama.capabilities_declared = []  # no vision model available
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/caption", json={"text": "A hand-typed caption"})
    assert response.status_code == 200
    assert response.json()["caption"] == "A hand-typed caption"
    assert response.json()["caption_edited"] is True
    assert len(fake_ollama.chat_calls) == 0  # never asked the model


def test_a_hand_typed_caption_overwrites_an_existing_one_without_force(ai_client, fake_ollama):
    """Manual edit bypasses the write-once guard entirely, that guard
    exists to protect against silent *automatic* rewrites, not a person
    who deliberately opened the field and typed something."""
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/caption")  # AI-generated first
    response = ai_client.post(f"/media/{upload_id}/caption", json={"text": "corrected by hand"})
    assert response.json()["caption"] == "corrected by hand"
    assert response.json()["caption_edited"] is True
    # Which model wrote the pre-edit caption is kept, not cleared, the
    # badge can still credit it alongside "edited" (see
    # MediaUpload.caption_edited's docstring for why).
    assert response.json()["caption_model"]


def test_an_empty_typed_caption_clears_it(ai_client, fake_ollama):
    fake_ollama.capabilities_declared = ["vision"]
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()["id"]
    ai_client.post(f"/media/{upload_id}/caption")
    response = ai_client.post(f"/media/{upload_id}/caption", json={"text": "   "})
    assert response.json()["caption"] == ""
    # A full reset, not a caption with nothing to show for who last wrote one.
    assert response.json()["caption_edited"] is False
    assert response.json()["caption_model"] == ""


def test_a_hand_typed_caption_is_stored_on_a_pdf_upload(ai_client, fake_ollama):
    """A document may carry a description, typed or generated.

    This test asserted a 415 until 2026-09-09, when the owner asked for the
    opposite: "the describe with ai button in the files tab doesnt work. it
    should be a button for generating a description/summary of the file from
    the readable and/or extractable content of the file." The suffix guard
    that produced the refusal is gone from both caption routes, so the
    hand-typed half it also blocked works as well: a Files row's description
    field is the same field an image's is, and refusing to store what someone
    typed into it was never the part anybody asked for.
    """
    upload_id = ai_client.post(
        "/media/upload", files={"file": ("scan.pdf", b"%PDF-1.4", "application/pdf")}
    ).json()["id"]
    response = ai_client.post(f"/media/{upload_id}/caption", json={"text": "a caption"})
    assert response.status_code == 200, response.text
    assert response.json()["caption"] == "a caption"
    assert response.json()["caption_edited"] is True


def test_media_meta_returns_what_the_app_knows_about_one_upload(ai_client):
    """The lightbox's own lookup, keyed on the stored filename because a url
    is the only identifier most callers hold.

    Reported directly: a caption and OCR text showed under the picture in
    the Image Gallery and nowhere else in the app. The cause was that
    `openLightbox` took them as arguments and only the gallery had a media
    row to pass: so this endpoint exists to let the lightbox ask instead.
    """
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    ).json()
    stored = uploaded["url"].rsplit("/", 1)[-1]

    body = ai_client.get(f"/media/meta/{stored}").json()
    assert body["id"] == uploaded["id"]
    assert body["original_name"] == "shot.png"
    assert body["url"] == uploaded["url"]
    # The fields the lightbox actually renders are all present, even empty.
    for key in ("caption", "ocr_text", "vision_ocr_text", "created_at"):
        assert key in body


def test_media_meta_404s_rather_than_shadowing_the_upload_id_route(ai_client):
    """Two things at once, both real.

    A url can outlive its row, deleting an upload deliberately leaves any
    note still pointing at it alone, so a miss is an ordinary state the
    lightbox renders as "no panel", not a fault.

    And a 404 (rather than a 422) is what proves the route is not being
    shadowed: declared after `/media/{upload_id}`, "meta" would be parsed as
    an upload id and rejected as a non-integer before this handler ever ran.
    That is the same ordering trap `/media/orphans` already carries a
    comment about.
    """
    assert ai_client.get("/media/meta/never-existed.png").status_code == 404


def test_media_text_reads_an_uploaded_pdf_for_the_lightbox(ai_client):
    """The document-preview half of the lightbox.

    `docview.extract` and its whole format table already existed for
    **attachments** (`GET /files/{id}/text`); uploads simply had no way to
    reach it. Note the split this test has to respect: `MEDIA_SUFFIXES` is
    images + PDF only, and deliberately narrow (that folder is served, and
    the AI can write into it), so a PDF is the one *document* that reaches
    the viewer through `/media`. Everything wider, .docx, .csv, .py, is an
    attachment, and reaches the same extractor by the other route.
    """
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    uploaded = ai_client.post(
        "/media/upload", files={"file": ("report.pdf", pdf, "application/pdf")}
    ).json()
    assert "url" in uploaded, uploaded
    stored = uploaded["url"].rsplit("/", 1)[-1]

    viewed = ai_client.get(f"/media/text/{stored}")
    assert viewed.status_code == 200
    payload = viewed.json()
    # The name shown is the human one, not the generated storage name.
    assert payload["filename"] == "report.pdf"
    # `kind` is what tells the frontend how to render, and is why the
    # lightbox does not have to sniff the extension a second time. A PDF
    # with no real text layer still answers the shape honestly rather than
    # erroring: `source`/`message` carry that.
    assert payload["kind"] in {"markdown", "code", "plain"}
    assert "source" in payload and "message" in payload


def test_media_text_404s_for_an_unknown_upload(ai_client):
    assert ai_client.get("/media/text/never-existed.md").status_code == 404


# --- pdf-info / pdf-page: viewing a PDF's actual pages, no AI involved ---------
#
# Direct instruction, after the AI-extraction lightbox left a user stuck on
# "Reading…" for a scanned PDF: "pdfs and documents should be viewable,
# accessible and manageable without the ai, even if the ai cant read them."
# These two routes are the answer, pdfpages rasterises pages to PNG, the
# same optional, no-torch, ~20ms/page library the vision-OCR fallback
# already used, but reached without markitdown or a model anywhere in the
# path.

# A real, tiny, one-page PDF pypdfium2 can actually open, the bare
# structural stub used elsewhere in this file has no page tree, so pdfium
# (correctly) can't render anything from it.
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


def _upload_pdf(ai_client, data: bytes = _ONE_PAGE_PDF, name: str = "notes.pdf") -> str:
    uploaded = ai_client.post(
        "/media/upload", files={"file": (name, data, "application/pdf")}
    ).json()
    return uploaded["url"].rsplit("/", 1)[-1]


def test_pdf_info_404s_for_an_unknown_upload(ai_client):
    assert ai_client.get("/media/pdf-info/never-existed.pdf").status_code == 404


def test_pdf_info_422s_for_a_non_pdf(ai_client):
    stored = _upload_pdf(ai_client)
    non_pdf = stored.rsplit(".", 1)[0] + ".png"
    assert ai_client.get(f"/media/pdf-info/{non_pdf}").status_code == 422


def test_pdf_info_without_the_extra_says_so(ai_client, monkeypatch):
    from memorymap.core import pdfpages

    monkeypatch.setattr(pdfpages, "available", lambda: False)
    stored = _upload_pdf(ai_client)
    payload = ai_client.get(f"/media/pdf-info/{stored}").json()
    assert payload["available"] is False
    assert payload["pages"] == 0
    assert "rasteriser" in payload["message"].lower() or "extras" in payload["message"].lower()


def test_pdf_info_on_an_unopenable_pdf_says_so_not_probably_a_scan(ai_client, monkeypatch):
    """Same misdiagnosis this session already fixed in `docview.py`, checked
    here too since this is a second, independent path to the same file."""
    from memorymap.core import pdfpages

    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "page_count", lambda p: 0)
    stored = _upload_pdf(ai_client)
    payload = ai_client.get(f"/media/pdf-info/{stored}").json()
    assert payload["available"] is False
    assert "couldn't be opened" in payload["message"].lower()


def test_pdf_page_404s_out_of_range(ai_client, monkeypatch):
    from memorymap.core import pdfpages

    monkeypatch.setattr(pdfpages, "available", lambda: True)
    monkeypatch.setattr(pdfpages, "render_page", lambda p, i: None)
    stored = _upload_pdf(ai_client)
    assert ai_client.get(f"/media/pdf-page/{stored}/9").status_code == 404


def test_pdf_page_404s_for_a_non_pdf(ai_client):
    stored = _upload_pdf(ai_client)
    non_pdf = stored.rsplit(".", 1)[0] + ".png"
    assert ai_client.get(f"/media/pdf-page/{non_pdf}/0").status_code == 404


@pytest.mark.skipif(not pdfpages.available(), reason="the pdfpages extra is not installed")
def test_pdf_page_returns_a_real_png(ai_client):
    stored = _upload_pdf(ai_client)
    info = ai_client.get(f"/media/pdf-info/{stored}").json()
    assert info["available"] is True
    assert info["pages"] == 1

    page = ai_client.get(f"/media/pdf-page/{stored}/0")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_a_page_by_page_reading_reaches_the_gallery_row(ai_client):
    """Reported: "the extracted ocr for files doesnt actually appear in the file
    rows in the files library subtab".

    A whole-file reading lands on the row (`vision_ocr_text`); a PDF read one
    page at a time in the OCR workspace lands in `page_reads` instead, and the
    two were never joined, so a document with every page read still said "No
    text yet" in the library. The list endpoint now falls back to the joined
    page text, in page order."""
    from memorymap.core import deps
    from memorymap.core.database import MediaUpload, PageRead

    with deps.get_db().session() as session:
        upload = MediaUpload(filename="paged.pdf", original_name="paged.pdf")
        session.add(upload)
        session.flush()
        upload_id = upload.id
        # Deliberately out of page order: the join must sort, not trust
        # insertion order.
        session.add(PageRead(kind="upload", source_id=upload_id, page=1, text="second page"))
        session.add(PageRead(kind="upload", source_id=upload_id, page=0, text="first page"))
        session.commit()

    rows = ai_client.get("/media").json()
    row = next(r for r in rows if r["id"] == upload_id)
    assert row["vision_ocr_text"] == "first page\n\nsecond page"


def test_a_whole_file_reading_still_wins_over_the_page_join(ai_client):
    """The fallback is a fallback: a reading stored on the row itself is the
    one the user last made of the whole document, and must not be replaced by
    older per-page fragments."""
    from memorymap.core import deps
    from memorymap.core.database import MediaUpload, PageRead

    with deps.get_db().session() as session:
        upload = MediaUpload(
            filename="whole.pdf", original_name="whole.pdf", vision_ocr_text="the whole thing"
        )
        session.add(upload)
        session.flush()
        upload_id = upload.id
        session.add(PageRead(kind="upload", source_id=upload_id, page=0, text="a fragment"))
        session.commit()

    rows = ai_client.get("/media").json()
    row = next(r for r in rows if r["id"] == upload_id)
    assert row["vision_ocr_text"] == "the whole thing"


# --- pagination (INBOX 117: this list used to hand back the whole table,
# 300 uploads measured at 117.6 KB in one response) ------------------------


def _seed_uploads(count):
    """Rows straight through the model: this is about how the gallery is
    read, not about the upload path (covered above), and hundreds of real
    uploads would also write hundreds of files to disk."""
    from memorymap.core import deps
    from memorymap.core.database import MediaUpload

    session = deps.get_db().session()
    session.add_all(
        MediaUpload(filename=f"seed-{i:04d}.png", original_name=f"photo {i}.png", size_bytes=1)
        for i in range(count)
    )
    session.commit()
    session.close()


def test_media_pages_and_reports_the_real_total(client):
    _seed_uploads(5)

    first = client.get("/media", params={"limit": 2, "offset": 0})
    assert first.status_code == 200
    assert len(first.json()) == 2
    assert first.headers["X-Total-Count"] == "5"

    second = client.get("/media", params={"limit": 2, "offset": 2})
    assert len(second.json()) == 2

    last = client.get("/media", params={"limit": 2, "offset": 4})
    assert len(last.json()) == 1
    assert last.headers["X-Total-Count"] == "5"

    # `offset` reaches the rest, every row exactly once: the gallery pages
    # until the header is satisfied, so nothing is left unreachable.
    paged = [row["id"] for row in first.json() + second.json() + last.json()]
    assert len(set(paged)) == 5
    assert set(paged) == {row["id"] for row in client.get("/media", params={"limit": 100}).json()}


def test_media_past_the_page_size_is_still_reachable(client):
    size = routes_files.MEDIA_PAGE_SIZE
    _seed_uploads(size + 5)

    first = client.get("/media")
    assert len(first.json()) == size
    assert first.headers["X-Total-Count"] == str(size + 5)

    rest = client.get("/media", params={"offset": size})
    assert len(rest.json()) == 5
    seen = {row["id"] for row in first.json()} | {row["id"] for row in rest.json()}
    assert len(seen) == size + 5


def test_media_limit_is_validated(client):
    assert client.get("/media", params={"limit": 0}).status_code == 422
    assert client.get("/media", params={"offset": -1}).status_code == 422
    over = routes_files.MEDIA_PAGE_SIZE_MAX + 1
    assert client.get("/media", params={"limit": over}).status_code == 422
