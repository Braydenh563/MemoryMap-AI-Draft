"""Turning a PDF page into an image, so a vision model can read it.

This is the piece `core/docview.py`'s docstring described as missing: a scanned
PDF has no text layer, `ai/vision_ocr.py` reads *images*, and nothing here
turned one into the other. The seam was built and the plug was not.

**Why pypdfium2 and not the alternatives.** Measured rather than assumed, 
installed into this project's own venv and run:

- ``pypdfium2`` + ``Pillow``: ~16 MB on disk, installs in seconds from a
  self-contained wheel, no system packages, **no torch**, and renders a page in
  about 20 ms. It is Google's PDFium, the renderer in Chrome, under a BSD
  licence.
- ``PyMuPDF`` renders just as well but is AGPL, which for this project is a
  licensing decision rather than a dependency (see ANALYSIS.md).
- ``pdf2image`` shells out to Poppler, a system package the user has to install
  by hand: the opposite of what a local-first app that must "just run" wants.

Optional, and it stays optional. Everything here degrades to "no pages" if the
library is absent, and `core/extras.py` carries the install button. The rule
that made the extras catalogue exist applies to this too: a new dependency is a
decision, not a side effect.

Deliberately not Tesseract, by direct instruction: *"I basically dont want to
download tesseract and only want to use an ai vision learning and ocr model for
images and scanned documents."* Nothing here reads text. It produces pixels and
hands them to the model.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

#: Serialises every call into pypdfium2. Not a performance nicety, a real
#: crash, reproduced and confirmed: FastAPI's sync routes run in an anyio
#: threadpool, and a browser viewing a multi-page PDF fires several
#: `GET /media/pdf-page/{n}` requests concurrently (one per `<img>`,
#: unthrottled by `loading="lazy"` for anything near the viewport). Hammering
#: `pdfium.PdfDocument()`/`.render()` from several threads at once, even
#: against independently opened documents, corrupts PDFium's C-level heap:
#: reproduced locally as `corrupted double-linked list` and a hard process
#: abort (SIGABRT), which no Python `except` clause can catch, since it never
#: raises a Python exception at all. Reported live, from a real PDF: several
#: pages 404ing at once and "it crashed... i couldnt scroll." The render
#: itself is ~20ms (this module's own docstring), so serialising it costs
#: nothing perceptible: an 8-page view goes from "mostly-parallel" to
#: "160ms sequential," not from fast to slow.
_pdfium_lock = threading.Lock()

#: How many pages of one PDF are ever rendered.
#:
#: A vision model reads a page in seconds, not milliseconds, so a 300-page scan
#: is an hour of GPU time nobody asked for. Eight pages is enough to answer
#: "what is this document", which is what the viewer is for, and the message
#: says plainly when there was more.
MAX_PAGES = 8

#: Render scale. PDF user units are 1/72 inch, so 2.0 is ~144 DPI.
#:
#: Chosen against what OCR models actually want rather than what looks nice:
#: below about 150 DPI small type stops being legible to them, and above 300
#: the image gets large enough that the *model* becomes the bottleneck twice
#: over: more pixels to encode, and a longer prompt to hold them.
RENDER_SCALE = 2.0

#: Refuse to rasterise anything larger. A PDF is a container format and can
#: hold a single 20,000 x 20,000 page; rendering that at 2x is several
#: gigabytes of bitmap in one allocation. The limit is on the rendered pixel
#: count rather than the file size, because those are unrelated, a 40 KB PDF
#: can declare a page a metre wide.
MAX_PIXELS = 40_000_000


def available() -> bool:
    """Is there a rasteriser in this interpreter?

    Import rather than `pip show`, same reasoning as `extras.is_installed`:
    what matters is whether this process can use it.
    """
    try:
        import pypdfium2  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def page_count(path: Path) -> int:
    """How many pages, or 0 if it cannot be read at all."""
    if not available():
        return 0
    try:
        import pypdfium2 as pdfium

        with _pdfium_lock:
            document = pdfium.PdfDocument(str(path))
            try:
                return len(document)
            finally:
                document.close()
    except Exception as exc:  # noqa: BLE001  # a viewer must not 500 on a bad file
        # `%r`, not `%s`, on `path` throughout this file: flagged by CodeQL
        # (py/log-injection) even though `path` is always `attachment.stored_name`
        # (a hash this app generated itself, see routes_files.py), never the
        # uploaded file's own name. CodeQL can't see that far through the call
        # chain, and `%r` closes the gap for free either way: repr() escapes
        # newlines and control characters, so nothing reaching this logger can
        # forge a second log line no matter where the value came from.
        logger.debug("couldn't count pages in %r: %s", path, exc)
        return 0


def _render_one(page, path: Path, index: int, *, greyscale: bool) -> bytes | None:
    """One already-open `pdfium` page to PNG bytes, or None if it is too
    large to render safely. Shared by `render_pages` (the vision-OCR batch)
    and `render_page` (one page, for the viewer) so the pixel-limit check
    and the encoding choice live in exactly one place."""
    import io

    width, height = page.get_size()
    if (width * RENDER_SCALE) * (height * RENDER_SCALE) > MAX_PIXELS:
        logger.info(
            "skipping page %d of %r: %dx%d at %.1fx exceeds the pixel limit",
            index + 1, path.name, width, height, RENDER_SCALE,
        )
        return None
    image = page.render(scale=RENDER_SCALE).to_pil()
    try:
        buffer = io.BytesIO()
        if greyscale:
            # Greyscale before PNG: a scanned page carries no colour worth
            # keeping for a vision model, and this is roughly a third of the
            # bytes for it to encode. The page *viewer* (render_page) keeps
            # colour: a person reading their own document is not paying a
            # token budget the way a model prompt is.
            image = image.convert("L")
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    finally:
        image.close()


def render_pages(path: Path, limit: int = MAX_PAGES) -> list[bytes]:
    """The first ``limit`` pages as PNG bytes, or [].

    Never raises. Every caller is a viewer or a background job, and a
    malformed, encrypted or truncated PDF is an ordinary thing to be handed, 
    the honest answer is "no pages", which the caller already has a message
    for.

    Pages are rendered one at a time and released as they go: holding eight
    decoded bitmaps at once is the difference between tens and hundreds of
    megabytes on a large scan.
    """
    if not available():
        return []
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return []

    pages: list[bytes] = []
    # Closed inside the lock, for the reason `render_page` gives below: a
    # close outside it races another thread's open in pdfium's global state.
    try:
        with _pdfium_lock:
            document = pdfium.PdfDocument(str(path))
            try:
                for index in range(min(len(document), max(0, limit))):
                    page = document[index]
                    try:
                        png = _render_one(page, path, index, greyscale=True)
                        if png is not None:
                            pages.append(png)
                    finally:
                        page.close()
            finally:
                try:
                    document.close()
                except Exception:  # noqa: BLE001  # nothing left to release
                    pass
    except Exception as exc:  # noqa: BLE001  # see the docstring
        logger.info("couldn't rasterise %r: %s", path, exc)
        return pages
    return pages


def render_page(path: Path, index: int) -> bytes | None:
    """One page, by number, as PNG bytes, for *viewing* a PDF rather than
    reading it with a model. Kept apart from `render_pages`/`MAX_PAGES`
    deliberately: that cap exists to bound vision-model cost (a model reads
    a page in seconds, so eight pages is already a lot of GPU time), and has
    nothing to do with how many pages a person can scroll past for free. In
    colour, unlike `render_pages`, nothing here is paying a model's token
    budget for the file.

    None on any failure (page out of range, a file pdfium can't open, an
    oversized page): the caller, `routes_files.pdf_page`, turns that into
    a 404, the same "no pages" contract `render_pages` already keeps.
    """
    # CodeQL (py/log-injection) flags `index` itself here, not just `path`:
    # it can't see that FastAPI's `index: int` route parameter already
    # rejects anything non-numeric before this function is ever called, so
    # it treats the value reaching `logger.info` below as still tainted.
    # An explicit int() re-cast into a fresh local breaks that taint chain
    # for CodeQL and costs nothing at runtime, a real int passes through
    # unchanged, and the `except` mirrors the `index < 0` guard it replaces.
    try:
        safe_index = int(index)
    except (TypeError, ValueError):
        return None
    if not available() or safe_index < 0:
        return None
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None

    # The document is closed INSIDE the lock. It used to be closed in an
    # outer `finally`, after the `with` had released the lock, so one thread
    # could be tearing a document down in pdfium while another was opening
    # or rendering under the lock. pdfium keeps global state, and that is a
    # segmentation fault, not an exception: the full suite died at 64% in
    # `test_concurrent_page_renders_do_not_corrupt_or_crash`, the test
    # written for exactly this shape, on a run where `-x` could not catch
    # it. Everything pdfium touches, open to close, now happens under the
    # one lock; the PNG bytes are the only thing that leaves it.
    try:
        with _pdfium_lock:
            document = pdfium.PdfDocument(str(path))
            try:
                if safe_index >= len(document):
                    return None
                page = document[safe_index]
                try:
                    return _render_one(page, path, safe_index, greyscale=False)
                finally:
                    page.close()
            finally:
                try:
                    document.close()
                except Exception:  # noqa: BLE001  # already rendered or already failed
                    pass
    except Exception as exc:  # noqa: BLE001  # a viewer must not 500 on a bad file
        logger.info("couldn't rasterise page %d of %r: %s", safe_index, path, exc)
        return None
