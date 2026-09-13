"""Outline a region, read just that (UI_MODERNISATION_PLAN Phase 7.4).

Asked as a question:

    "can there be a way for the user to manually outline and single out
     regions on a pdf or similar document and then the ai will read what is in
     those regions?? like maybe the user can outline a graph or diagram on a
     pdf slide and then the user cna get the image or ocr model to analyse and
     caption that thing."

The workspace crops the rectangle out of the page raster it already has on
screen and posts the crop; this endpoint runs a reader or the describe prompt
over it and stores nothing. What is checked here is the contract around that:
the two modes, the guards on the upload, that the file id is a real
authorisation check, and that nothing lands in `PageRead`.

**Every model call goes through the fake transport**, there is no vision model
and no Tesseract binary in this sandbox, so what a real reader *answers* about
a crop is not covered by anything here.
"""

from __future__ import annotations

import io

from memorymap.ai import captioning, vision_ocr
from memorymap.core import deps
from memorymap.core.database import PageRead

#: The smallest real PNG, a 1x1 greyscale pixel. Enough to satisfy the magic
#: number check, which is the only thing this endpoint looks at before handing
#: the bytes to a reader.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00"
    b"\x00\x00\x00:~\x9bU\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload_pdf(client, name="deck.pdf") -> int:
    created = client.post(
        "/media/upload",
        files={"file": (name, io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _post(client, upload_id, mode="read", data=PNG, **extra):
    form = {"page": "2", "mode": mode, "reader": "vision"}
    form.update(extra)
    return client.post(
        f"/media/{upload_id}/region-read",
        files={"crop": ("region.png", io.BytesIO(data), "image/png")},
        data=form,
    )


def test_reading_a_region_transcribes_the_crop(client, fake_ollama, monkeypatch):
    upload_id = _upload_pdf(client)
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "stub-reader", raising=False
    )
    monkeypatch.setattr(vision_ocr, "vision_ocr_text", lambda path, model, ollama: "TOTAL 42")

    answer = _post(client, upload_id)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["text"] == "TOTAL 42"
    assert body["mode"] == "read"
    assert body["model"] == "stub-reader"
    #: The page comes back so the answer can be labelled with where it came
    #: from: an answer that does not say which page is the thing the region
    #: overlay exists to avoid.
    assert body["page"] == 2


def test_describing_a_region_uses_the_figure_prompt(client, fake_ollama, monkeypatch):
    """The describe half runs the *page* caption prompt, not the photograph
    one: a cropped chart is a figure, and "what does this image show" is the
    question that produces "a bar chart on a white background"."""
    upload_id = _upload_pdf(client)
    monkeypatch.setattr(
        deps.get_model_manager(),
        "resolve_vision_model",
        lambda ollama: "stub-vision",
        raising=False,
    )
    seen: dict = {}

    def _describe(path, index, count, model, ollama):
        seen["prompt"] = captioning.page_caption_prompt(index, count)
        seen["model"] = model
        return "Revenue rises then flattens."

    monkeypatch.setattr(captioning, "page_caption_text", _describe)

    answer = _post(client, upload_id, mode="describe")
    assert answer.status_code == 200, answer.text
    assert answer.json()["text"] == "Revenue rises then flattens."
    assert answer.json()["mode"] == "describe"
    assert "figures" in seen["prompt"].lower()
    assert seen["model"] == "stub-vision"


def test_a_region_is_never_stored(client, fake_ollama, monkeypatch):
    """`PageRead` is keyed by page and a region is a part of one, usually
    several, each answering a different question. Filing one over the page's
    reading would destroy a transcription to save a note about one chart."""
    upload_id = _upload_pdf(client)
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "stub-reader", raising=False
    )
    monkeypatch.setattr(vision_ocr, "vision_ocr_text", lambda path, model, ollama: "TOTAL 42")
    _post(client, upload_id)

    with deps.get_db().session() as session:
        assert session.query(PageRead).count() == 0
    assert client.get(f"/media/{upload_id}/page-reads").json()["pages"] == []


def test_an_unknown_mode_is_refused_rather_than_guessed(client, fake_ollama):
    upload_id = _upload_pdf(client)
    refused = _post(client, upload_id, mode="summarise")
    assert refused.status_code == 400
    assert "read" in refused.json()["detail"]


def test_something_that_is_not_a_png_is_refused(client, fake_ollama):
    """The workspace sends `canvas.toBlob(..., "image/png")`. Anything else is
    a caller doing something other than what this route is for, and this is
    the one endpoint in the app that runs a model over an image nobody
    uploaded."""
    upload_id = _upload_pdf(client)
    refused = _post(client, upload_id, data=b"GIF89a not really")
    assert refused.status_code == 415


def test_an_empty_region_is_refused(client, fake_ollama):
    upload_id = _upload_pdf(client)
    refused = _post(client, upload_id, data=b"")
    assert refused.status_code == 400


def test_the_file_id_is_a_real_check(client, fake_ollama):
    """The upload is looked up and not otherwise used, and that is the point:
    without it this would be "run a model on any image anyone posts"."""
    missing = client.post(
        "/media/999999/region-read",
        files={"crop": ("region.png", io.BytesIO(PNG), "image/png")},
        data={"page": "0", "mode": "read", "reader": "vision"},
    )
    assert missing.status_code == 404


def test_nothing_found_is_an_answer_not_an_error(client, fake_ollama, monkeypatch):
    upload_id = _upload_pdf(client)
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "stub-reader", raising=False
    )
    monkeypatch.setattr(vision_ocr, "vision_ocr_text", lambda path, model, ollama: "")

    answer = _post(client, upload_id)
    assert answer.status_code == 200
    assert answer.json()["text"] == ""
    assert "No text was found" in answer.json()["message"]
    #: No model named, because nothing was produced, "read by X" over an empty
    #: answer is a claim about text that does not exist.
    assert answer.json()["model"] == ""


def test_the_attachment_side_has_the_same_route(client, fake_ollama, monkeypatch):
    created = client.post("/entries", json={"content": "host note"}).json()
    attached = client.post(
        f"/entries/{created['id']}/files",
        files={"file": ("deck.pdf", io.BytesIO(b"%PDF-1.4"), "application/octet-stream")},
    )
    attachment_id = attached.json()["attachments"][-1]["id"]
    monkeypatch.setattr(
        deps.get_model_manager(), "resolve_ocr_model", lambda ollama: "stub-reader", raising=False
    )
    monkeypatch.setattr(vision_ocr, "vision_ocr_text", lambda path, model, ollama: "from a file")

    answer = client.post(
        f"/files/{attachment_id}/region-read",
        files={"crop": ("region.png", io.BytesIO(PNG), "image/png")},
        data={"page": "0", "mode": "read", "reader": "vision"},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["text"] == "from a file"


# --- the workspace side (lints; the Python suite cannot see the DOM) ---------
#
# Measured once in Chromium: dragging on the page draws the marquee, the offer
# appears under it and inside the pane, "Read text" posts a 440x180 PNG cropped
# out of an 800x600 page raster with `page`/`mode` fields beside it, the answer
# lands in a focusable card tagged "Page 1 · region", Escape clears the
# rectangle rather than closing the workspace, and an injected region box is
# still clickable through the now-pointer-transparent boxes layer. These lints
# pin the wiring that made those true.

from pathlib import Path  # noqa: E402  (the lints below are a separate concern)

LIBRARY = Path("frontend/library.js").read_text(encoding="utf-8")
INDEX = Path("frontend/index.html").read_text(encoding="utf-8")
CSS = Path("frontend/css/07-whiteboard-misc.css").read_text(encoding="utf-8")


def test_the_drag_layer_is_not_the_regions_layer():
    """`#ocr-boxes` is `display: none` whenever Regions is unticked, and a
    gesture that stops existing because of a checkbox is a feature nobody
    finds twice."""
    assert 'id="ocr-select"' in INDEX
    assert ".ocr-boxes.is-hidden" in CSS


def test_the_boxes_layer_lets_the_drag_through_and_the_boxes_do_not():
    """The boxes layer is `inset: 0` over the whole page, so with the default
    `pointer-events` it swallowed every press meant to start a drag."""
    boxes = CSS.split(".ocr-boxes {")[1].split("}")[0]
    assert "pointer-events: none" in boxes
    box = CSS.split(".ocr-box {")[1].split("}")[0]
    assert "pointer-events: auto" in box


def test_the_offer_uses_the_apps_floating_panel_shell():
    """DESIGN.md's popover shell, the rule at the end of this stylesheet, not
    a fifth recipe for "a small box that floats"."""
    shell = CSS.split(".wb-export-menu,")[-1].split("{")[0]
    assert ".ocr-region-popover" in shell
    glass_off = Path("frontend/css/03-dashboard-widgets.css").read_text(encoding="utf-8")
    assert ':root[data-glass="off"] .ocr-region-popover' in glass_off, (
        "a glass surface missing from the glass-off list stays glassy with the "
        "setting switched off: DESIGN.md says to add it"
    )


def test_escape_clears_the_rectangle_before_it_closes_the_window():
    """Asked for by name, and the only sane order: having outlined something by
    mistake, Escape must undo the mistake, not the reading session."""
    keys = LIBRARY.split('if (event.key === "Escape") {')[1].split("closeOcrWorkspace();")[0]
    assert "ocrClearRegionSelection();" in keys


def test_the_rectangle_is_cleared_once_the_request_is_away():
    run = LIBRARY.split("async function ocrRunRegion(mode)")[1].split("\n//:")[0]
    assert "ocrClearRegionSelection();" in run
    #: A FormData body with `api()`'s default JSON content type has no
    #: multipart boundary: measured against the running app as a 405 before
    #: any of the request's fields were looked at.
    assert 'headers: { "X-Auth-Token": authToken()' in run


def test_the_crop_is_taken_at_the_pages_own_resolution():
    """A page is rasterised at 2x precisely so small type is legible to a
    model; cropping from the displayed size throws that away."""
    crop = LIBRARY.split("async function ocrRegionCrop()")[1].split("\n//:")[0]
    assert "naturalWidth" in crop
    assert 'toBlob(resolve, "image/png")' in crop


def test_the_answer_is_focusable_and_says_where_it_came_from():
    show = LIBRARY.split("function ocrShowRegionResult(")[1].split("\n//:")[0]
    assert "card.tabIndex = -1;" in show
    assert "card.focus();" in show
    assert "· region" in show
