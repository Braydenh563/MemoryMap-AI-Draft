"""Read an attached document the moment it lands, the way an image is read.

The owner, 2026-09-09, with a screenshot of a Files row that was a wall of
transcription and no description: "the files description needs to be an
actual description or summary of what the file is about and includes, not a
transcription", and, of the same tab, "the describe with ai button in the
files tab doesnt work ... no notification, no bg process, nothing."

An `Attachment` had no analysis of any kind on upload. A `MediaUpload` image
gets Tesseract and a caption on background threads the moment it is stored
(`core/ocr.py`, `ai/captioning.py`); a document got neither, so every row in
the Files sub-tab was a filename until somebody opened each one by hand. This
module is the missing half, and it deliberately mirrors
`captioning.caption_and_store`: it runs off the request, it never raises, and
it never rewrites a reading or a description that is already there.

Two steps, and they are independent on purpose. The text comes out of
`docview`, which is local, deterministic and needs no model, so it happens on
every machine. The description is a utility-model completion over that text
(`captioning.describe_document`), so it happens only where a model is
running, and its absence costs the reader nothing they had before.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger("memorymap.docreader")

#: What this pass does not touch. An image attachment is the vision path's
#: job: `docview` would return nothing for it, and describing a picture from
#: its non-existent text would be a worse answer than no answer.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".svg", ".tiff", ".tif"}
)


def read_document_and_store(attachment_id: int) -> str | None:
    """Extract an attachment's text, then describe it. Returns the
    description, or None when there was nothing to do.

    Synchronous, so a manual call and the tests can drive it without waiting
    on a thread, exactly as `caption_and_store` is split from
    `caption_in_background`.
    """
    import os

    from memorymap.ai import captioning
    from memorymap.core import deps, docview
    from memorymap.core.database import Attachment

    with deps.get_db().session() as session:
        row = session.get(Attachment, attachment_id)
        if row is None:
            return None  # deleted, or its upload never committed, before this ran
        if Path(row.filename or "").suffix.lower() in IMAGE_SUFFIXES:
            return None
        # Nothing to do, and saying so early keeps a re-upload of the same
        # file from paying for a model call to produce what is already there.
        if row.ocr_text and row.caption:
            return row.caption
        #: The same containment check `routes_files._within_dir` makes, in
        #: the shape CodeQL's `Path::SafeAccessCheck` recognises: a
        #: `stored_name` reaches here through a database round trip, which
        #: that analysis tracks as tainted regardless. A name that escapes the
        #: uploads directory is a bug or an attack, and a background pass is
        #: not the place to act on either, so it declines and says so once.
        base = os.path.realpath(str(deps.get_config().uploads_dir))
        candidate = os.path.realpath(os.path.join(base, row.stored_name or ""))
        if not candidate.startswith(base):
            logger.warning("refusing to read an attachment outside the uploads directory")
            return None
        path = Path(candidate)
        if not path.is_file():
            return None

        if not row.ocr_text:
            try:
                text = (docview.extract(path).text or "").strip()
            except Exception:
                # A malformed document is a normal thing to be handed, and a
                # traceback out of a background thread would take the upload's
                # own log entry with it.
                logger.info("could not read %s", row.filename, exc_info=True)
                text = ""
            if text:
                row.ocr_text = text
                session.commit()

        if row.caption:
            return row.caption
        readable = (row.ocr_text or "").strip()
        if not readable:
            return None
        ollama = deps.get_ollama()
        if not ollama.is_running():
            # Not a failure worth logging on every upload: a notebook with no
            # model running would fill the log with the same expected line.
            return None
        try:
            models = deps.get_model_manager()
            described = captioning.describe_document(readable, models, ollama)
        except Exception:
            logger.info("could not describe %s", row.filename, exc_info=True)
            return None
        if not described:
            return None
        row.caption = described
        row.caption_model = models.utility_model()
        row.caption_edited = False
        session.commit()
        return described


def read_in_background(attachment_id: int) -> None:
    """Fire and forget, so `POST /entries/{id}/files` answers at once.

    A document extraction is fast and a model round trip is not, and neither
    is anything the person who just attached a file should wait behind.
    """
    threading.Thread(
        target=read_document_and_store,
        args=(attachment_id,),
        daemon=True,
        name="document-read",
    ).start()
