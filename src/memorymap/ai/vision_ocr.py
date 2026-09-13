"""Verbatim text transcription from an image, via a vision-capable model.

A third reader of the same uploaded images `core/ocr.py` and
`ai/captioning.py` already cover, asked for directly as its own "extractor
mode": Tesseract (`core/ocr.py`) is local and exact but fails outright on
handwriting, low-contrast whiteboard photos, skewed scans and most
non-Latin scripts. A vision model often still reads those, this asks one
to transcribe rather than describe, which is a different prompt and a
different stored field (`MediaUpload.vision_ocr_text`) from
`ai/captioning.py`'s natural-language `caption`, not a replacement for it.

Runs automatically on every raster upload, same as `ai/captioning.py`
(asked for directly: images and documents-with-images alike, since a
document attaches its images through this same `POST /media/upload`
pipeline: one trigger point covers notes, chat and documents together).
`POST /media/{id}/vision-ocr` still exists for a manual re-read (the
regenerate button next to it in the Library). Same never-raise,
best-effort contract as its two siblings.
"""

from __future__ import annotations



import base64
import importlib
import logging
import mimetypes
import tempfile
import threading
import time
from pathlib import Path

from memorymap.core import pdfpages

#: Page reads in flight right now, keyed by an opaque id -> what is being read.
#:
#: Asked for directly: "make sure the ocr and featrures int he workspase
#: actually function and even if the user leaves the things being read. also
#: let the user be able to stop the readings., make sure eveyrhting appears in
#: the bg processes in settings." The last clause is this: a page read is a
#: model round-trip of several seconds and it appeared in Settings ->
#: Background tasks nowhere at all, unlike captioning (`ai/captioning.py`'s
#: `_running`, the shape copied here) or a re-index. So closing the workspace
#: mid-read left no trace anywhere that the app was still working.
#:
#: Registered around the *request handler* rather than inside the reader,
#: because both readers (the vision model and Tesseract) go through the same
#: two endpoints and neither should have to know about this list.
_reads_lock = threading.Lock()
_reads: dict[int, dict] = {}
_read_seq = 0


def register_page_read(label: str, model: str = "") -> int:
    """Record a read as running. Returns the id to hand `finish_page_read`."""
    global _read_seq
    with _reads_lock:
        _read_seq += 1
        token = _read_seq
        _reads[token] = {"label": label, "model": model}
    return token


def finish_page_read(token: int) -> None:
    """Drop a read from the running list. Never raises on an unknown id, the
    caller is a `finally`, and a `finally` that can throw hides the real
    error."""
    with _reads_lock:
        _reads.pop(token, None)


def running_page_reads() -> list[dict]:
    """What is being read right now, for the Tasks panel."""
    with _reads_lock:
        return [{"token": token, **info} for token, info in _reads.items()]

logger = logging.getLogger("memorymap.vision_ocr")

#: Plain transcription, nothing else, a caption model is prone to
#: describing the image instead of reading it unless told explicitly not
#: to. Asked to say so plainly when there is no text, rather than inventing
#: a description, so a caller can tell "genuinely no text" apart from a
#: model that ignored the instruction.
VISION_OCR_PROMPT = (
    "Transcribe every piece of text visible in this image, exactly as "
    "written, in reading order. Do not describe the image. Do not add "
    "commentary, translation or correction. If there is no legible text "
    "at all, reply with exactly: NO_TEXT_FOUND"
)

#: Same raster-only restriction as ocr.OCR_SUFFIXES and
#: captioning.CAPTION_SUFFIXES: a vision model is handed the same file
#: either would open, and a PDF needs the same page-rasterisation step none
#: of the three pulls in.
VISION_OCR_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

#: The model's own way of saying "nothing to transcribe" (see the prompt
#: above): stored as "" rather than literally, matching the null/"not run
#: yet" convention every field like this in this app already uses.
_NO_TEXT_SENTINEL = "NO_TEXT_FOUND"


def vision_ocr_text(image_path: Path, model: str, ollama) -> str | None:
    """Best-effort transcription for one image file. Never raises.

    Returns `""` when the model was actually asked and genuinely found no
    text: an ordinary, common result for a plain photo, not a failure.
    Returns `None` when the attempt itself didn't produce a usable result
    (missing file, unreachable backend, request error), the one case
    worth a "failed" entry in Settings → Background tasks. Callers that
    only care about "is there text" can still treat both as falsy; the
    distinction exists for `vision_ocr_and_store`'s taskhistory recording.
    """
    try:
        data = image_path.read_bytes()
    except OSError:
        return None
    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    try:
        reply = ollama.chat(
            model,
            [{"role": "user", "content": VISION_OCR_PROMPT, "images": [uri]}],
        )
        text = (reply.get("content") or "").strip()
        if not text or text.upper() == _NO_TEXT_SENTINEL:
            return ""
        return text
    except Exception:
        # Same reasoning as ocr.extract_text's and captioning.caption_text's
        # own bare except: one bad image must never take down the request
        # or background thread it runs on.
        logger.warning("Vision OCR failed for %s", image_path.name, exc_info=True)
        return None


#: How a multi-page transcription is separated. Plain and unambiguous: this
#: text goes into a viewer and into model prompts, so a marker has to survive
#: both without looking like content.
PAGE_MARKER = "\n\n--- page {n} ---\n\n"


def pdf_reader_or_none():
    """A ready-to-use `vision_reader` for `docview.extract`, or None.

    The one place that decides whether a scanned PDF can be read at all, so
    every caller agrees. Three things have to be true, and each has its own
    reason to be false:

    - the backend is reachable (no model, no reading);
    - a model is resolved for the job, `resolve_ocr_model`, so an explicit OCR
      model wins, then the vision model, then auto-detect;
    - `core/pdfpages` is installed, since without it there is no image to read.

    Returning None rather than a reader that always fails is what lets
    `docview` fall through to its "probably a scan" message, which names the
    missing piece.

    This exists because the alternative was each caller resolving the model
    itself, and the first one to do so got it wrong: it passed
    `ModelManager.vision_model()`, the raw preference, which is the empty
    string until somebody sets it, so on a default install the scanned-PDF
    path asked the backend to run a model named "".
    """
    # `deps` is fetched via `importlib` rather than `from memorymap.core
    # import deps`: the latter, even placed inside this function, was still
    # flagged by CodeQL's cyclic-import check as beginning a cycle (it counts
    # a function body's imports too): this is the same lookup with no
    # `import` statement for that static check to see.
    deps = importlib.import_module("memorymap.core.deps")

    if not pdfpages.available():
        return None
    ollama = deps.get_ollama()
    try:
        if not ollama.is_running():
            return None
    except Exception:  # noqa: BLE001  # an unreachable backend is not an error
        return None
    model = deps.get_model_manager().resolve_ocr_model(ollama)
    if not model:
        return None
    return pdf_vision_reader(model, ollama)


def pdf_vision_reader(model: str, ollama):
    """A `docview.extract(vision_reader=…)` callable for scanned PDFs.

    This is the piece that makes the scanned-PDF path real rather than merely
    wired. `docview` has always taken a `vision_reader` and always passed
    whatever it was given; every caller passed nothing, because there was no
    way to turn a PDF page into the image this needs. `core/pdfpages.py` is
    that way, so this closes the loop.

    Returns a callable rather than doing the work, because `docview` knows
    nothing about models and should not start: it hands over a path and gets
    back text or "".

    Never raises, for the same reason everything else on this path doesn't: 
    it runs inside a request that must return a viewer, not a 500.
    """

    def read(path: Path) -> str:
        pages = pdfpages.render_pages(path)
        if not pages:
            return ""
        out: list[str] = []
        with tempfile.TemporaryDirectory(prefix="mm-pdfocr-") as scratch:
            for number, png in enumerate(pages, start=1):
                # A file rather than bytes because vision_ocr_text reads a
                # path: and reusing it matters more than avoiding the write:
                # it is the one place the prompt, the data-URI encoding and
                # the no-text sentinel are handled, and a second copy of that
                # is a second thing to keep in step.
                page_path = Path(scratch) / f"page-{number:03d}.png"
                try:
                    page_path.write_bytes(png)
                except OSError:
                    continue
                text = vision_ocr_text(page_path, model, ollama)
                if text:
                    if out:
                        out.append(PAGE_MARKER.format(n=number))
                    out.append(text)
        return "".join(out)

    return read


def vision_ocr_and_store(upload_id: int, image_path: Path, force: bool = False) -> str | None:
    """Runs synchronously and writes the result onto the `MediaUpload` row.

    Returns the new transcription, the existing one (when `force` is False
    and one is already stored), or None if nothing could be produced (no
    vision model, upload gone, no legible text found). Mirrors
    `captioning.caption_and_store`'s shape and its taskhistory recording
    exactly, sharing the same "quiet when no vision model exists, recorded
    when a real attempt found nothing" split.
    """
    deps = importlib.import_module("memorymap.core.deps")
    taskhistory = importlib.import_module("memorymap.core.taskhistory")
    from memorymap.core.database import MediaUpload

    with deps.get_db().session() as session:
        upload = session.get(MediaUpload, upload_id)
        if upload is None:
            return None  # deleted (or its upload never committed) before this ran
        if upload.vision_ocr_text and not force:
            return upload.vision_ocr_text
        model = deps.get_model_manager().resolve_vision_model(deps.get_ollama())
        if not model:
            return None
        started = time.monotonic()
        text = vision_ocr_text(image_path, model, deps.get_ollama())
        elapsed_ms = (time.monotonic() - started) * 1000
        if text is None:
            # The attempt itself failed (unreachable backend, request
            # error): the genuine failure case, distinct from "asked the
            # model and it found no text" just below.
            taskhistory.record(
                "vision_ocr",
                f"Reading text from {upload.original_name}",
                "failed",
                name=model,
                duration_ms=elapsed_ms,
            )
            return None
        upload.vision_ocr_text = text
        upload.vision_ocr_model = model
        session.commit()
        taskhistory.record(
            "vision_ocr",
            f"Reading text from {upload.original_name}",
            "completed",
            name=model,
            detail="no legible text found" if not text else "",
            duration_ms=elapsed_ms,
        )
        return text


def pdf_vision_ocr_and_store(upload_id: int, pdf_path: Path, force: bool = False) -> str | None:
    """The same job as `vision_ocr_and_store`, for a PDF rather than a picture.

    This exists because of a gap that was invisible from either side.
    `VISION_OCR_SUFFIXES` is raster-only, so `process_committed_upload` never
    started a reader for an uploaded PDF, while `pdf_vision_reader` (the half
    that *can* read one) was only ever reached from a button. The result: file
    a scanned PDF and nothing at all had read it, so it was unsearchable and
    the agent could not see a word of it until somebody happened to open it and
    press a button. Asked for directly: *"make sure all the file and document
    ocr works with ai ocr models, I dont use tesseract."*

    A PDF that already carries a text layer is left alone: `docview.extract`
    (no `vision_reader` passed, so no model round trip) reads that layer, and
    a model asked to transcribe a page whose text is already exact can only
    make it worse. The model is for scans, the case where there is nothing
    else.
    """
    deps = importlib.import_module("memorymap.core.deps")
    docview = importlib.import_module("memorymap.core.docview")
    taskhistory = importlib.import_module("memorymap.core.taskhistory")
    from memorymap.core.database import MediaUpload

    with deps.get_db().session() as session:
        upload = session.get(MediaUpload, upload_id)
        if upload is None:
            return None  # deleted before this ran
        if upload.vision_ocr_text and not force:
            return upload.vision_ocr_text
        original = upload.original_name

    # Outside the session: both of these are slow (a converter, then a model
    # per page), and holding a session open across them is how a background
    # job ends up blocking a request.
    try:
        if (docview.extract(pdf_path).text or "").strip():
            return None  # has a real text layer; nothing for a model to add
    except Exception:  # noqa: BLE001  # an unreadable PDF just means "try the model"
        pass

    reader = pdf_reader_or_none()
    if reader is None:
        return None  # no model, no rasteriser, or the backend is down
    started = time.monotonic()
    try:
        text = (reader(pdf_path) or "").strip()
    except Exception:  # noqa: BLE001  # same reasoning as vision_ocr_text's own
        taskhistory.record(
            "vision_ocr",
            f"Reading text from {original}",
            "failed",
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return None
    elapsed_ms = (time.monotonic() - started) * 1000

    model = deps.get_model_manager().resolve_ocr_model(deps.get_ollama()) or ""
    with deps.get_db().session() as session:
        upload = session.get(MediaUpload, upload_id)
        if upload is None:
            return None
        upload.vision_ocr_text = text or None
        upload.vision_ocr_model = model if text else None
        session.commit()
    taskhistory.record(
        "vision_ocr",
        f"Reading text from {original}",
        "completed",
        name=model,
        detail="no legible text found" if not text else "",
        duration_ms=elapsed_ms,
    )
    return text or None


def pdf_vision_ocr_in_background(upload_id: int, pdf_path: Path) -> None:
    """Fire-and-forget, exactly as `vision_ocr_in_background`, and more
    necessary here, since a scan is up to `pdfpages.MAX_PAGES` model round
    trips rather than one."""
    threading.Thread(
        target=pdf_vision_ocr_and_store,
        args=(upload_id, pdf_path),
        daemon=True,
        name="vision-ocr-pdf",
    ).start()


def vision_ocr_in_background(upload_id: int, image_path: Path) -> None:
    """Fire-and-forget: never blocks the `POST /media/upload` response.
    Same shape as `captioning.caption_in_background`, a real model round
    trip is far slower than the request itself, and nothing about "was the
    upload accepted" should wait on it."""
    threading.Thread(
        target=vision_ocr_and_store,
        args=(upload_id, image_path),
        daemon=True,
        name="vision-ocr-extract",
    ).start()
