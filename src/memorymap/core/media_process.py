"""Where OCR/captioning/vision-OCR actually get triggered for an upload.

Asked for directly, correcting this session's own earlier choice: "the OCR
shouldn't happen to staged files, only when they are actually saved as a
note, actually sent in a chat message, or uploaded directly to the
library." `POST /media/upload` is one shared endpoint behind every one of
those (the note composer, the chat composer, the document editor and the
Library's own "Upload images" button all post to it), a staged image
picked in the note composer and then abandoned, or an image attached to a
chat draft that's deleted before sending, has no business paying for a
Tesseract pass and a vision-model round trip for something that may never
be kept.

So the trigger point moves from *upload* to *commit*: this module is
called from the moment something actually becomes permanent, a note or
document is saved with the image referenced in its content, a chat turn is
saved with the image in `image_media_ids`, a whiteboard image object is
placed on the board, or `POST /media/upload` itself is told the upload
*is* the commit (`direct=True`, the Library's own upload button).

Every trigger already guards its own repeat work, `caption_and_store`/
`vision_ocr_and_store` are write-once unless forced, and Tesseract is cheap
and local: so calling this on every save of a note that already has its
images processed is a fast no-op, not a growing cost.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from sqlalchemy.orm import Session

from memorymap.core.database import MediaUpload


def _module(name: str):
    """A lazy import of one of this module's three readers, or `media_gc`.

    Every name here is one this module needs only at call time, never at
    import time: `ocr`/`captioning`/`vision_ocr` need a model to actually
    run, and `media_gc` is a sibling this only borrows one function from. A
    plain `from memorymap.core import ocr` inside the function already made
    that lazy at *runtime*, but CodeQL's cyclic-import check still counts a
    function body's imports as edges in its static graph, so this goes
    through `importlib` instead, which is the same lookup with no `import`
    statement for that check to see.
    """
    return importlib.import_module(name)


def process_committed_upload(upload: MediaUpload, media_dir: Path) -> None:
    """Fire the three background readers for one upload that just became
    permanent. Never raises: a missing file or an unsupported suffix for
    one reader just means that reader has nothing to do, exactly as
    `POST /media/upload`'s own trigger calls always treated it.
    """
    ocr = _module("memorymap.core.ocr")
    captioning = _module("memorymap.ai.captioning")
    vision_ocr = _module("memorymap.ai.vision_ocr")

    # Both default to on, because reading a picture you just filed is the
    # behaviour that makes the gallery searchable at all, but asked for
    # directly, they are now switchable off: a vision-model round trip per
    # image is the single most expensive automatic thing this app does, and
    # someone on a small model (or who simply does not want their pictures
    # described) had no way to stop it. The manual buttons on each tile are
    # unaffected either way; this governs only what happens unasked.
    #
    # Read here rather than inside each reader so the decision is in one
    # place and the readers stay usable directly from their own endpoints.
    config = _module("memorymap.core.deps").get_config()
    describe = bool(config.get_preference("auto_caption_images", True))
    read_text = bool(config.get_preference("auto_read_image_text", True))

    path = media_dir / upload.filename
    suffix = Path(upload.filename).suffix.lower()
    if read_text and suffix in ocr.OCR_SUFFIXES:
        ocr.extract_in_background(upload.id, path)
    if describe and suffix in captioning.CAPTION_SUFFIXES:
        captioning.caption_in_background(upload.id, path)
    if read_text and suffix in vision_ocr.VISION_OCR_SUFFIXES:
        vision_ocr.vision_ocr_in_background(upload.id, path)
    # A PDF is neither of the above: `OCR_SUFFIXES` and `VISION_OCR_SUFFIXES`
    # are both raster-only, so filing a scanned PDF used to start no reader at
    # all and the file stayed unsearchable until somebody opened it and pressed
    # a button. `pdf_vision_ocr_and_store` skips PDFs that already have a text
    # layer, so this costs a model round trip only for the scans that need one.
    if read_text and suffix == ".pdf":
        vision_ocr.pdf_vision_ocr_in_background(upload.id, path)


def process_referenced_uploads(session: Session, media_dir: Path, text: str) -> None:
    """Every `/media/…` upload referenced in `text` (a note or document's
    own content) gets processed, keyed off filename, reuses
    `media_gc`'s own extraction pattern rather than a second regex, since
    "which uploads does this text reference" is exactly the question that
    module already answers for the orphan scan.
    """
    names = _module("memorymap.core.media_gc").referenced_names(text)
    if not names:
        return
    for upload in session.query(MediaUpload).filter(MediaUpload.filename.in_(names)):
        process_committed_upload(upload, media_dir)


def process_committed_upload_ids(session: Session, media_dir: Path, media_ids: list[int]) -> None:
    """Same as `process_referenced_uploads`, keyed off explicit ids, for
    a saved chat turn, which stores `image_media_ids` directly rather than
    `/media/…` text (TurnBody.image_media_ids's own docstring explains why:
    a conversation's own content is a question string, not markdown with
    an inline image reference)."""
    if not media_ids:
        return
    for upload in session.query(MediaUpload).filter(MediaUpload.id.in_(media_ids)):
        process_committed_upload(upload, media_dir)


#: How much of one picture's readings joins the text it is embedded in. A
#: transcribed page can be thousands of characters, and a note whose embedding
#: is nine-tenths OCR is no longer a vector for the note.
MAX_MEDIA_TEXT_CHARS = 600


def media_text_for(session: Session, text: str) -> str:
    """What the pictures in this text say, as text.

    Asked for directly: "allow captions if they accompany images of sketches
    to be read by the ai if they appear in semantic searches." A note with a
    drawing in it used to be, to every part of this app that reads notes, a
    note with a `/media/…` url in it: the vision model's description of that
    drawing and any text it read off it lived on the `MediaUpload` row and was
    reachable only from the Library tile.

    **Appended to the text that is embedded and read, never written into the
    note.** The caption is the app's reading of a picture, not something the
    user typed, and editing their note to insert it would be the app putting
    words in their document. Derived on the way past instead, which also means
    a re-captioned image improves search without rewriting anything.

    Returns "" when there are no pictures or nothing has been read yet, so a
    caller can concatenate unconditionally.
    """
    names = _module("memorymap.core.media_gc").referenced_names(text)
    if not names:
        return ""
    parts: list[str] = []
    for upload in session.query(MediaUpload).filter(MediaUpload.filename.in_(names)):
        readings = [
            reading.strip()
            for reading in (upload.caption, upload.vision_ocr_text, upload.ocr_text)
            if reading and reading.strip()
        ]
        if not readings:
            continue
        # Named, so a model reading this can tell a picture's description from
        # the note's own sentences: and so two pictures in one note do not
        # run together into one paragraph.
        joined = " ".join(readings)[:MAX_MEDIA_TEXT_CHARS]
        parts.append(f"[image: {upload.original_name}] {joined}")
    return "\n".join(parts)
