"""File attachments on entries.

Bytes live in the uploads folder under a random name (no path traversal
possible); the original filename is kept only for downloads.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
import sys
import tempfile
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.ai import captioning, docreader, vision_ocr
from memorymap.api.routes_entries import _existing_entry, _to_out
from memorymap.api.schemas import EntryOut
from memorymap.core import deps, docview, filejobs, media_gc, media_process, ocr, pdfpages
from memorymap.core.database import Attachment, Entry, MediaUpload, PageRead
from memorymap.core.deps import get_session
from memorymap.entry import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

# `/media/{filename}` and `/files/{attachment_id}` are the two routes an
# `<img src>` points at directly rather than something the frontend fetches
# with its own X-Auth-Token header, see `require_unlock_media`'s own
# docstring in routes_auth.py for why they need a separate router (a
# router-level dependency and a route-level one are additive, not an
# override, so the header-only gate on `router` can't be loosened per-route).
media_router = APIRouter(tags=["files"])

MAX_FILE_BYTES = 50 * 1024 * 1024  # a personal notebook, not a fileserver

#: Note attachments, unlike /media/upload above, had no allowlist at all, 
#: any file, of any type, attached without a single refusal (asked for
#: directly: "make sure incompatible files are currently refused upon
#: attempted upload with an error message"). This one is broader than
#: MEDIA_SUFFIXES on purpose: attachments are downloaded (FileResponse's
#: default Content-Disposition: attachment, not rendered inline the way
#: /media/{name} is), so the stored-XSS concern that shaped that allowlist
#: doesn't apply here in the same way, but video and audio are still out
#: (no player exists for either yet; audio specifically is tracked as a
#: real feature to add, not a permanent refusal) and so are the obvious
#: executable/script shapes, since nothing in this app ever needs to run
#: an attachment.
ATTACHMENT_SUFFIXES = frozenset(
    {
        # Images
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".svg", ".tiff", ".tif",
        # Documents
        ".pdf", ".docx", ".doc", ".odt", ".rtf",
        ".pptx", ".ppt", ".odp",
        ".xlsx", ".xls", ".ods", ".csv",
        # Text & markup
        ".txt", ".md", ".markdown", ".json", ".xml", ".yaml", ".yml", ".html", ".htm", ".css",
        # Code
        ".js", ".ts", ".jsx", ".tsx", ".py", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go",
        ".rs", ".rb", ".php", ".sh", ".sql", ".swift", ".kt",
        # Archives
        ".zip",
    }
)


@router.post("/entries/{entry_id}/files", response_model=EntryOut, status_code=201)
def upload_file(
    entry_id: int, file: UploadFile, session: Session = Depends(get_session)
) -> EntryOut:
    entry = _existing_entry(session, entry_id)
    suffix = Path(file.filename or "file").suffix[:12].lower()
    if suffix not in ATTACHMENT_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"'{suffix or 'that file type'}' can't be attached. "
                "Images, PDFs, office documents, text and code files are supported, "
                "video and audio attachments aren't yet."
            ),
        )
    uploads_dir: Path = deps.get_config().uploads_dir
    # The folder is created at startup, but it only has to go missing once, 
    # a cleanup tool, a synced or unmounted data directory, a restore that
    # didn't include an empty folder, and every upload fails with a 500 and a
    # traceback instead of saving. Sketches are the usual casualty, since the
    # note saves first and only the drawing is lost.
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Random stored name, original extension kept for double-click opening.
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = uploads_dir / stored_name

    size = 0
    with destination.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                out.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File is larger than 50 MB")
            out.write(chunk)

    attachment = manager.add_attachment(
        session,
        entry,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        mime=file.content_type or "application/octet-stream",
        size=size,
    )
    #: **A document says what it is without being asked.** An image gets
    #: Tesseract and a caption on background threads the moment it lands; an
    #: attachment got neither, so every row in the Files sub-tab was a
    #: filename until somebody opened each one by hand, which is the "no bg
    #: process, nothing" half of the owner's report. `read_in_background`
    #: extracts the text locally and, where a model is running, writes a
    #: description of it. Fire and forget, so this response is not held.
    #:
    #: `getattr` because `add_attachment` has not always returned the row, and
    #: a missing return here must not turn an upload that worked into a 500.
    new_id = getattr(attachment, "id", None)
    if new_id is not None:
        docreader.read_in_background(new_id)
    return _to_out(session, entry)


def _existing_attachment(session: Session, attachment_id: int) -> Attachment:
    return deps.get_or_404(session, Attachment, attachment_id, "Attachment not found")


@media_router.get("/files/{attachment_id}")
def download_file(attachment_id: int, session: Session = Depends(get_session)) -> FileResponse:
    attachment = _existing_attachment(session, attachment_id)
    path = deps.get_config().uploads_dir / attachment.stored_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    return FileResponse(path, filename=attachment.filename, media_type=attachment.mime)


class AttachmentGalleryOut(BaseModel):
    """One note's own file, shaped for the Library's Images/Files gallery: 
    not `MediaUploadOut`: an `Attachment` has never been OCR'd, captioned, or
    read by a vision model (those are `MediaUpload`-only features, see that
    model's own docstring), so reusing that shape would mean either faking
    fields that don't apply or leaving the gallery to guess why they're
    always empty. This is deliberately the smaller, honest set of what an
    attachment actually has.

    Reported directly, and root-caused rather than patched around: "a pdf I
    uplaoded to a note doesnt show in the libary" / "my uploaded pdf file
    isnt shown in the library files subtab". `renderLibraryImagesGallery()`
    (library.js) has only ever called `GET /media`, which is `MediaUpload`
    rows: a file attached to a note through the composer or note editor
    (`POST /entries/{id}/files`, this file, above) is an `Attachment` row
    instead, a completely different table, and so never appeared no matter
    how the gallery itself was styled or filtered.
    """

    id: int
    #: `/files/{id}`, token-gated the same way as `/media/{name}`, see
    #: `mediaSrc()` (app.js) and `require_unlock_media` (routes_auth.py).
    #: Deliberately has no file extension (an attachment is served by id,
    #: not by stored name), which is why the gallery classifies Images vs.
    #: Files from `mime` here rather than sniffing the url the way it does
    #: for a `MediaUpload` row's `/media/{name}.ext`.
    url: str
    original_name: str
    mime: str
    created_at: str
    #: The one note this file hangs on, an attachment's "used in", where a
    #: `MediaUpload` row can be referenced from several places at once.
    #: Shaped as a single-item `used_by` list rather than a new field so the
    #: gallery tile's existing "used in" rendering (ROADMAP item 43) needs
    #: no branch for which kind of row it is looking at.
    used_by: list[dict] = []
    #: The file's size on disk, in bytes; 0 when it cannot be stat'ed (the
    #: row outliving its file is a real state, see the "Image deleted"
    #: placeholder the gallery already renders). The comment above says a
    #: byte count was left out because it "would cost one `stat` per row on
    #: every gallery load for a number nobody asked for", it has since been
    #: asked for directly ("file details such as the type, size, topic/
    #: category"), which settles the trade the other way. It is one `stat`
    #: per row against a local disk, on the same pass that already walks
    #: every row.
    size_bytes: int = 0
    #: What this file says, see `Attachment`'s own docstring for why these
    #: now exist on an attachment at all. Never null over the wire, the same
    #: convention `MediaUploadOut` keeps, so the gallery can filter on them
    #: with a plain substring test.
    caption: str = ""
    caption_model: str = ""
    caption_edited: bool = False
    ocr_text: str = ""
    vision_ocr_text: str = ""
    vision_ocr_model: str = ""
    #: True when this file has renderable pages (a PDF), so the tile can show
    #: the first one instead of a generic file glyph, asked for directly:
    #: "in the files tab, there is no preview".
    has_pages: bool = False
    #: How many of this document's pages have a stored reading (`PageRead`).
    #: UI_MODERNISATION_PLAN Phase 7.5: the Files row states "N pages read · N
    #: words" instead of clamping a paragraph nobody can read at that size, and
    #: counting pages by splitting the joined text would miscount any reading
    #: that happens to contain a blank line. 0 for anything never read, which
    #: is also the honest answer for an image.
    pages_read: int = 0


@router.get("/files/gallery", response_model=list[AttachmentGalleryOut])
def list_attachment_gallery(session: Session = Depends(get_session)) -> list[AttachmentGalleryOut]:
    """Every note-attached file the Library's gallery may show, the
    `Attachment` half of what `GET /media` (this file, `list_media`) already
    covers for `MediaUpload` rows. See `AttachmentGalleryOut` for why this is
    a separate, smaller shape rather than folded into that endpoint.

    Same privacy rule as the Library's own overview list (`_images()` in
    routes_library.py): a private note's attachment is as private as the
    note, so it is excluded here rather than shown in a browsing surface the
    note itself is hidden from. Workspace scoping comes for free from
    `Attachment`'s own `WorkspaceMixin`, the ambient session filter already
    applies before this query ever runs, the same as every other
    workspace-scoped read in this app.
    """
    rows = session.execute(
        select(Attachment, Entry)
        .join(Entry, Attachment.entry_id == Entry.id)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.is_private == False,  # noqa: E712
        )
        .order_by(Attachment.created_at.desc())
    ).all()
    ids = [attachment.id for attachment, _ in rows]
    page_text = _page_read_text_map("attachment", ids)
    pages_read = _page_read_count_map("attachment", ids)
    return [
        AttachmentGalleryOut(
            id=attachment.id,
            pages_read=pages_read.get(attachment.id, 0),
            url=f"/files/{attachment.id}",
            original_name=attachment.filename,
            mime=attachment.mime or "application/octet-stream",
            created_at=attachment.created_at.isoformat(),
            used_by=[{"kind": "note", "id": entry.id, "label": manager.plain_label(entry.content)}],
            caption=attachment.caption or "",
            caption_model=attachment.caption_model or "",
            caption_edited=bool(attachment.caption_edited),
            ocr_text=attachment.ocr_text or "",
            #: Falls back to the page-by-page reading -- see
            #: `_page_read_text_map` for why the two were not joined before.
            vision_ocr_text=attachment.vision_ocr_text or page_text.get(attachment.id, ""),
            vision_ocr_model=attachment.vision_ocr_model or "",
            has_pages=Path(attachment.filename).suffix.lower() == ".pdf",
            size_bytes=_attachment_size(session, attachment),
        )
        for attachment, entry in rows
    ]


class AttachmentAnalyseBody(BaseModel):
    """What to read out of a file, or what to store instead of reading it."""

    #: "caption", a vision model describes it. "ocr", Tesseract (an image)
    #: or this app's own document extractor (anything else). "vision", a
    #: vision model transcribes the pages, which is the one that answers a
    #: scanned PDF or a diagram nothing else can read.
    kind: str = Field(pattern="^(caption|ocr|vision)$")
    #: Set the value by hand instead of running anything, "the text and
    #: analysis needs to be… modifyable by the user". `""` clears it back to
    #: "nothing here", the same as the `/media` endpoints this mirrors.
    text: str | None = Field(default=None, max_length=200_000)
    #: Re-run even when there is already a value (a caption is written once
    #: and left alone otherwise, so nothing an AI wrote and a person read can
    #: silently change under them).
    force: bool = False


def _attachment_size(session: Session, attachment: Attachment) -> int:
    """Bytes on disk, or 0 when the file is gone.

    Same contract as `MediaUploadOut.size_bytes`: a row can outlive its file,
    and the gallery draws a placeholder for that rather than dropping the row,
    so this must report a number instead of raising.

    `Attachment.size` is written at upload time (`manager.add_attachment`)
    and kept current by every route that replaces the bytes on disk, so the
    column is normally already the right answer, read it first and skip the
    filesystem call `GET /files/gallery` used to pay once per attachment on
    every open (`list_media`'s sibling gallery has the same bug, open as
    PLAN.md P6; nothing here changes that one). `stat()` only runs for a row
    whose `size` is still NULL/0 (a pre-existing attachment from before this
    column existed) and whose file is actually there, and the result is
    written back so the next call, in this request's own list, and every
    request after: reads the column instead of the disk again.
    """
    if attachment.size:
        return attachment.size
    try:
        size = (deps.get_config().uploads_dir / attachment.stored_name).stat().st_size
    except OSError:
        return 0
    if size:
        attachment.size = size
        session.commit()
    return size


def _attachment_out(session: Session, attachment: Attachment) -> AttachmentGalleryOut:
    entry = session.get(Entry, attachment.entry_id)
    return AttachmentGalleryOut(
        id=attachment.id,
        url=f"/files/{attachment.id}",
        original_name=attachment.filename,
        mime=attachment.mime or "application/octet-stream",
        created_at=attachment.created_at.isoformat(),
        used_by=(
            [{"kind": "note", "id": entry.id, "label": manager.plain_label(entry.content)}]
            if entry is not None
            else []
        ),
        caption=attachment.caption or "",
        caption_model=attachment.caption_model or "",
        caption_edited=bool(attachment.caption_edited),
        ocr_text=attachment.ocr_text or "",
        vision_ocr_text=attachment.vision_ocr_text or "",
        vision_ocr_model=attachment.vision_ocr_model or "",
        has_pages=Path(attachment.filename).suffix.lower() == ".pdf",
        size_bytes=_attachment_size(session, attachment),
    )


@router.post("/files/{attachment_id}/analyse", response_model=AttachmentGalleryOut)
def analyse_attachment(
    attachment_id: int,
    body: AttachmentAnalyseBody,
    session: Session = Depends(get_session),
) -> AttachmentGalleryOut:
    """Read a note's attached file with the local models, or store a reading
    typed by hand.

    One endpoint for all three readings rather than three near-identical
    ones (the `/media` side grew that way and is three copies of the same
    twenty lines). The split that matters is not caption/ocr/vision, it is
    *image or document*: an image goes to Tesseract, a document goes through
    `docview` (the same extractor the file viewer already uses), and the
    vision path rasterises PDF pages so a scan with no text layer at all
    still has something a model can look at.
    """
    attachment = _existing_attachment(session, attachment_id)
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    suffix = Path(attachment.filename).suffix.lower()
    is_image = suffix in captioning.CAPTION_SUFFIXES

    if body.text is not None:
        stripped = body.text.strip() or None
        if body.kind == "caption":
            attachment.caption = stripped
            if stripped:
                attachment.caption_edited = True
            else:
                attachment.caption_model = None
                attachment.caption_edited = False
        elif body.kind == "ocr":
            attachment.ocr_text = stripped
        else:
            attachment.vision_ocr_text = stripped
            if not stripped:
                attachment.vision_ocr_model = None
        session.commit()
        return _attachment_out(session, attachment)

    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")

    if body.kind == "ocr":
        # Tesseract for a picture; this app's own document extractor for
        # everything else: a .docx or a text-layer PDF has real text in it
        # that no OCR pass should be guessing at.
        # Registered even though no model is involved: Tesseract on a long
        # scan is one of the slowest things this app does, and "is it working
        # or is it stuck" is the same question whether the work is a model or
        # a binary.
        with filejobs.reading("ocr", attachment.id, attachment.filename):
            if is_image:
                text = ocr.extract_text(path)
            else:
                # No `vision_reader` passed on purpose: this is the "read it
                # locally, no model" path, and the vision kind below is the one
                # that costs a model round trip. A scan with no text layer comes
                # back empty here, which is the honest answer and is exactly what
                # sends the reader to "Read with AI".
                text = docview.extract(path).text
        attachment.ocr_text = (text or "").strip() or None
        session.commit()
        return _attachment_out(session, attachment)

    #: **Describing a document needs no vision model, only its own text.**
    #: Reported on 2026-09-09: "the describe with ai button in the files tab
    #: doesnt work. it should be a button for generating a
    #: description/summary of the file from the readable and/or extractable
    #: content of the file." It refused with a 415 for everything that was
    #: not a picture or a PDF, and even a PDF went to a vision model, which
    #: most machines do not have installed.
    #:
    #: This branch sits above the vision-model checks deliberately: a .md, a
    #: .docx, a .csv or a text-layer PDF is described by the utility model
    #: that already writes tag suggestions, on a machine with no vision model
    #: at all. `ocr_text` first when it is there, since that is this file's
    #: reading as the reader has it (corrections included) rather than a
    #: second extraction that may disagree with what they can see.
    #:
    #: **`vision_ocr_text` was missing from this chain entirely.** Reported
    #: directly: a scan already read page by page with the AI document
    #: reader (fourteen pages stored here) still had "Describe with AI" call
    #: a vision model itself, on one raw page image, because this fallback
    #: only ever checked the Tesseract field and a fresh local extraction,
    #: never the field this exact reading is written to. Checked second,
    #: after `ocr_text`: Tesseract's own reading, when both exist, is the
    #: one already corrected by hand and shown as the file's own text; the
    #: AI reader's is the one likelier to exist at all for a scan, since it
    #: needs no separate OCR binary. `docview.extract` stays last of the
    #: three, since it is a *native* text layer and only a text-layer PDF or
    #: a `.docx`/`.csv`/etc. has one at all.
    #:
    #: A file whose text extraction comes back empty is a scan with nothing
    #: already read either, and falls through to the vision path below,
    #: which rasterises its first page. A file whose text is there but whose
    #: model had nothing to say stores nothing and says so: those are
    #: different answers and must not share a branch.
    if body.kind == "caption" and not is_image:
        if attachment.caption and not body.force:
            return _attachment_out(session, attachment)
        readable = (
            (attachment.ocr_text or "").strip()
            or (attachment.vision_ocr_text or "").strip()
            or (docview.extract(path).text or "").strip()
        )
        if readable:
            if not deps.get_ollama().is_running():
                raise HTTPException(status_code=409, detail="The AI model isn't running.")
            models = deps.get_model_manager()
            with filejobs.reading(
                "describe", attachment.id, attachment.filename, models.utility_model()
            ):
                described = captioning.describe_document(readable, models, deps.get_ollama())
            attachment.caption = described or None
            attachment.caption_model = models.utility_model() if described else None
            attachment.caption_edited = False
            session.commit()
            return _attachment_out(session, attachment)
        if suffix != ".pdf":
            raise HTTPException(
                status_code=415,
                detail="There is no readable text in this file to describe.",
            )

    # Both remaining kinds need a vision model.
    if not deps.get_ollama().is_running():
        raise HTTPException(status_code=409, detail="The AI model isn't running.")
    model = deps.get_model_manager().resolve_vision_model(deps.get_ollama())
    if not model:
        raise HTTPException(
            status_code=409,
            detail="No installed model reports it can see images, install or "
            "pick one in Settings → Models.",
        )
    ollama = deps.get_ollama()

    if body.kind == "caption":
        if attachment.caption and not body.force:
            return _attachment_out(session, attachment)
        # `pdf_vision_reader` returns the reader callable itself (docview's
        # `vision_reader` contract), not an object with a `.read`: calling
        # `.read(path)` on it was the reported 500 on "generate a caption" for
        # a PDF ("'function' object has no attribute 'read'").
        with filejobs.reading("describe", attachment.id, attachment.filename, model):
            text = (
                captioning.caption_text(path, model, ollama)
                if is_image
                else vision_ocr.pdf_vision_reader(model, ollama)(path)
            )
        attachment.caption = (text or "").strip() or None
        attachment.caption_model = model if attachment.caption else None
        attachment.caption_edited = False
    else:
        if attachment.vision_ocr_text and not body.force:
            return _attachment_out(session, attachment)
        # A PDF is rasterised page by page (`pdf_vision_reader`), which is
        # the whole point for a scan, where there is no text layer to read
        # and Tesseract has already found nothing.
        with filejobs.reading("vision", attachment.id, attachment.filename, model):
            text = (
                vision_ocr.vision_ocr_text(path, model, ollama)
                if is_image
                else vision_ocr.pdf_vision_reader(model, ollama)(path)
            )
        attachment.vision_ocr_text = (text or "").strip() or None
        attachment.vision_ocr_model = model if attachment.vision_ocr_text else None
    session.commit()
    return _attachment_out(session, attachment)


class AttachedFileTextOut(BaseModel):
    """One attached file, read as text for the in-app viewer."""

    filename: str
    #: "markdown" | "code" | "plain", how to render `text`, not what the file
    #: is. A converted .docx comes back as markdown, so it renders like one.
    kind: str
    #: "file" | "converted" | "vision-ocr". Shown to the reader, not merely
    #: logged: a vision model's transcription of a scan is a *reading* of the
    #: file, and presenting it identically to text read out of a .txt would be
    #: the app stating a guess as a fact.
    source: str
    text: str = ""
    truncated: bool = False
    #: Why there is no text, when there is none. Never an error status: "this
    #: file has no viewer yet" and "install markitdown" are both answers, and
    #: a 4xx would make the viewer show a failure for a file that is fine.
    message: str = ""
    #: Whether this file may be saved back over (`docview.editability`). True
    #: only where the text *is* the file, .md, .txt, .csv, code, so a .docx
    #: never is, and neither is a file too long to have been shown in full.
    editable: bool = False
    #: Why not, when `editable` is False. Written to be shown next to a
    #: disabled Edit button: §R7.1 item 2 asks for the honest reason in the UI
    #: rather than a control that does nothing.
    edit_message: str = ""


@router.get("/files/{attachment_id}/text", response_model=AttachedFileTextOut)
def attached_file_text(
    attachment_id: int, session: Session = Depends(get_session)
) -> AttachedFileTextOut:
    """An attached file's text, for reading it without leaving the app.

    Deliberately returns *text*, never the file. `download_file` above hands
    the browser the bytes with `Content-Disposition: attachment`, and
    `media_file` at the bottom of this module explains at length why serving
    anything new inline is the thing to avoid. A viewer built by widening
    either of those would inherit that problem once per file type; this one
    cannot, because what it sends has already stopped being a .docx.

    Read-only, and that is a property of the extraction rather than a missing
    feature: see `core/docview.py`'s module docstring. Editing an attached
    file's text would mean writing text back into a format it was never in.
    """
    attachment = _existing_attachment(session, attachment_id)
    path = deps.get_config().uploads_dir / attachment.stored_name
    # The scanned-PDF fallback, passed rather than omitted. `docview` has
    # always taken a `vision_reader` and this, its only caller, passed
    # nothing, so the whole path was wired and never once ran: exactly the
    # "features that never executed" shape CLAUDE.md warns about. It only does
    # any work for a PDF with no text layer, and only when the pdfpages extra
    # and a vision model are both present; every other file returns before it
    # is consulted.
    viewed = docview.extract(path, vision_reader=vision_ocr.pdf_reader_or_none())
    editable, edit_message = docview.editability(path, viewed)
    return AttachedFileTextOut(
        filename=attachment.filename,
        kind=viewed.kind,
        source=viewed.source,
        text=viewed.text,
        truncated=viewed.truncated,
        message=viewed.message,
        editable=editable,
        edit_message=edit_message,
    )


class FileTextIn(BaseModel):
    """The edited text of a file, on its way back to disk."""

    text: str


@router.put("/files/{attachment_id}/text", response_model=AttachedFileTextOut)
def save_attached_file_text(
    attachment_id: int, payload: FileTextIn, session: Session = Depends(get_session)
) -> AttachedFileTextOut:
    """Save an edited text file back over itself.

    **This does not widen the read-only rule above; it draws the line where
    the rule's own reason stops applying.** That reason is that extraction is
    one-way: text pulled out of a .docx is not a .docx. For a .md, a .txt, a
    .csv or a source file, "extraction" is `bytes.decode()`: the text *is* the
    file, and writing it back is lossless. `docview.editability` owns which is
    which, so this route and the viewer cannot disagree about it.

    Re-checked here rather than trusting the `editable` flag the GET returned:
    a client is not the authority on what may be overwritten, and the file can
    have been replaced between the two calls.
    """
    attachment = _existing_attachment(session, attachment_id)
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    viewed = docview.extract(path)
    editable, edit_message = docview.editability(path, viewed)
    if not editable:
        raise HTTPException(status_code=409, detail=edit_message)
    docview.write_text_file(path, payload.text)
    #: The row's `size` is what the Library shows beside the name, so it has to
    #: follow the file rather than stay at whatever was uploaded. Nothing here
    #: touches the semantic index: that indexes *notes*, and a file's text has
    #: never been in it, `search_files` reads the file itself.
    attachment.size = path.stat().st_size
    session.commit()
    saved = docview.extract(path)
    return AttachedFileTextOut(
        filename=attachment.filename,
        kind=saved.kind,
        source=saved.source,
        text=saved.text,
        truncated=saved.truncated,
        message=saved.message,
        editable=True,
    )


class PdfInfoOut(BaseModel):
    #: Whether the matching pdf-page endpoint can serve anything for this
    #: file: `media_pdf_page` for a `/media/` upload, `attached_file_pdf_page`
    #: for a note's own attachment. Moved up here, ahead of both `pdf-info`
    #: endpoints that return it: a FastAPI route decorator's `response_model`
    #: evaluates at import time, not lazily like a `from __future__ import
    #: annotations` type hint, so this has to exist before either decorator
    #: runs rather than merely before either function is called.
    available: bool
    #: Real page count, or 0 when `available` is False.
    pages: int
    #: Why `available` is False, for a caller that wants to say so rather
    #: than just hide the button. "" when `available` is True.
    message: str = ""


@router.get("/files/{attachment_id}/pdf-info", response_model=PdfInfoOut)
def attached_file_pdf_info(attachment_id: int, session: Session = Depends(get_session)) -> PdfInfoOut:
    """`media_pdf_info`'s sibling for a note's own attached PDF (the
    `Attachment` model, `uploads_dir`, a different file and a different
    table from a `/media/` upload, which is why this is a second endpoint
    rather than one that takes either id). See that docstring for why this
    exists apart from `attached_file_text` at all."""
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=422, detail="Not a PDF.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    if not pdfpages.available():
        return PdfInfoOut(
            available=False,
            pages=0,
            message=(
                "Viewing PDF pages needs a small rasteriser: install "
                "“Read scanned PDFs” in Settings → Extras."
            ),
        )
    count = pdfpages.page_count(path)
    if count == 0:
        return PdfInfoOut(
            available=False,
            pages=0,
            message=(
                "This PDF couldn't be opened. It may be corrupted, "
                "password-protected, or saved in a way this app's reader "
                "doesn't support."
            ),
        )
    return PdfInfoOut(available=True, pages=count)


@media_router.get("/files/{attachment_id}/pdf-page/{index}")
def attached_file_pdf_page(attachment_id: int, index: int, session: Session = Depends(get_session)) -> Response:
    """`media_pdf_page`'s sibling for an attached PDF, see that docstring
    for why this is always a freshly rendered PNG, never the file's own
    bytes. On `media_router`, same reason: loaded via `mediaSrc()`-tokened
    `<img src>`, not `apiJson`."""
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Not a PDF.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    png = pdfpages.render_page(path, index)
    if png is None:
        raise HTTPException(status_code=404, detail="That page doesn't exist.")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


#: The policy the HTML preview's own response carries, and every token in it
#: is load-bearing.
#:
#: **Why a response of its own rather than a `blob:` iframe.** The first
#: version built a Blob in the browser and framed it, and a `blob:` document
#: inherits its creator's CSP, so the app's `style-src 'self'` applied to the
#: framed page and **the page's own `<style>` block was refused.** Measured in
#: Chromium: "Refused to apply inline style", and `background-color` came back
#: `rgba(0, 0, 0, 0)` on a page that sets `#eef`. A preview that strips the
#: file's styling is not a preview of that file, and relaxing the *app's*
#: `style-src` to fix it would trade the notebook's own protection for a
#: viewer feature. A same-origin HTTP response carries its own policy instead,
#: and this is it.
#:
#: - `sandbox` (no tokens): opaque origin, no scripts, no forms, no
#:   navigation, no storage. This is what makes serving a file this app did
#:   not write safe to render at all.
#: - `script-src 'none'`: belt and braces beside the sandbox.
#: - `style-src 'unsafe-inline'`: the whole point: a page's own `<style>`
#:   and `style=` attributes. Harmless inside an opaque, scriptless frame.
#: - `img-src data:`: inline images only. **No `'self'`**, so a page cannot
#:   probe this app's own endpoints by pointing an `<img>` at them.
#: - `default-src 'none'` catches everything unlisted: no fetch, no fonts, no
#:   frames, no media, nothing off the network.
#: - `frame-ancestors 'self'`: **named explicitly, and it has to be.**
#:   `default-src 'none'` covers `frame-ancestors` too, so without this line
#:   the response forbids *being framed at all* and the pane renders
#:   `chrome-error://`. Measured, after the first version shipped with only
#:   `default-src 'none'`. The matching `X-Frame-Options: SAMEORIGIN` below
#:   is for the same reason: the app's middleware `setdefault`s `DENY` on
#:   every response, which a route that knows better may override.
HTML_PREVIEW_CSP = (
    "sandbox; default-src 'none'; script-src 'none'; "
    "style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'self'"
)


@media_router.get("/files/{attachment_id}/html-preview")
def attached_file_html_preview(
    attachment_id: int, session: Session = Depends(get_session)
) -> Response:
    """Render an attached .html file, for the viewer's preview pane.

    **This is the one exception to "nothing new is ever served inline", and it
    is narrow enough to state exactly.** `core/docview.py`'s docstring gives
    the rule and its reason: an inline viewer is a script host, and widening a
    file-serving endpoint's allowlist would inherit that problem once per type
    added. Here the response is `sandbox`ed with `script-src 'none'`, so it is
    the opposite of a script host, and it serves .html *only*, one suffix,
    checked below rather than by an allowlist that can be widened later.

    What is sent is the file's own text, read through `docview.extract`, the
    same clip and the same forgiving decode every other reader in the app
    gets, so a 40 MB file cannot be handed to the browser whole.

    On `media_router` because an `<iframe src>` is a declarative load and
    cannot attach a header: `require_unlock_media` is the gate that accepts
    the token as a query parameter, the same way `<img src>` already does.
    """
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() not in {".html", ".htm"}:
        raise HTTPException(status_code=404, detail="Not an HTML file.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    viewed = docview.extract(path)
    return Response(
        content=viewed.text,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": HTML_PREVIEW_CSP,
            # The middleware `setdefault`s DENY; this is the one response in
            # the app that is *meant* to be framed, by the app itself.
            "X-Frame-Options": "SAMEORIGIN",
            # No sniffing past the type we declared, and no caching of one
            # notebook's file into another view.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/files/{attachment_id}", response_model=EntryOut)
def delete_file(
    attachment_id: int,
    strip_references: bool = False,
    session: Session = Depends(get_session),
) -> EntryOut:
    """`strip_references` is `delete_media`'s flag on the other table, same
    reason, same default. An attached image can be embedded in the note it is
    attached to (`![](/files/12)`), and deleting the file used to leave that
    markdown behind forever."""
    attachment = _existing_attachment(session, attachment_id)
    entry = _existing_entry(session, attachment.entry_id)
    if strip_references:
        _strip_embeds(session, f"/files/{attachment.id}")
    manager.delete_attachment(session, attachment, deps.get_config().uploads_dir)
    return _to_out(session, entry)


class AttachmentRenameBody(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


@router.put("/files/{attachment_id}", response_model=EntryOut)
def rename_file(
    attachment_id: int, body: AttachmentRenameBody, session: Session = Depends(get_session)
) -> EntryOut:
    """Rename a file in the Library, the display name only, never the bytes.

    Mirrors `delete_file` above for the two checks that make this safe to
    expose per-item rather than globally:

    - `_existing_attachment` then `_existing_entry(attachment.entry_id)`, in
      that order, the same as `delete_file`. `Attachment` carries no
      workspace column of its own, its note does, so re-fetching the note
      through the same workspace-filtered query every other route uses is
      what makes an attachment in a workspace this request isn't in 404
      rather than quietly renaming across the boundary.
    - a private note's attachment is refused outright (403), matching the
      Library's own listing (`routes_library._images`), which already hides
      a private note's files from view entirely, renaming one from a
      surface that can't show it would be a hole the same shape as the ones
      CLAUDE.md's review section warns about: the guard here is new, but the
      boundary it enforces already exists elsewhere in the app.
    """
    attachment = _existing_attachment(session, attachment_id)
    entry = _existing_entry(session, attachment.entry_id)
    if entry.is_private:
        raise HTTPException(
            status_code=403,
            detail="This file is on a private note and can't be renamed until the note is readable.",
        )
    try:
        manager.rename_attachment(session, attachment, body.filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(session, entry)


# --- saving a file the app generated (§35E) ---------------------------------------
#
# Every export in this app builds a Blob in the browser and clicks a hidden
# `<a download>`. That works in a browser tab and does nothing at all in the
# desktop window: pywebview has no download handler, so the click is swallowed
# and the user gets no file and no error. Reported as "I don't think any of the
# file save features in the whole application work on the python desktop app".
#
# The fix is available because this app already runs a local server, it can
# write the file itself and say where it went. That is strictly more reliable
# than a download in every shell, and it is the only thing that works in the
# window.

#: Where generated files land by default. Beside the notes rather than in the
#: OS Downloads folder, so "where your data is" stays one answer unless the
#: user deliberately points it elsewhere, see `_exports_dir` below, added
#: after a direct request for a configurable location ("I have to dig in the
#: app data files to find and access them").
EXPORTS_DIRNAME = "exports"

#: A generated export is text or a small archive, never a media library.
MAX_SAVE_BYTES = 50 * 1024 * 1024


def _exports_dir() -> Path:
    """`export_save_dir` preference if set (validated at save time, see
    `_validated_export_dir` in routes_settings.py: so this is always a real,
    writable directory when non-empty), else the default beside the notes.
    """
    custom = deps.get_config().get_preference("export_save_dir", "")
    return Path(custom) if custom else deps.get_config().data_dir / EXPORTS_DIRNAME


class SaveFileBody(BaseModel):
    """One file the browser built and wants written to disk."""

    filename: str = Field(min_length=1, max_length=120)
    #: Base64, because the same route has to carry a .zip as well as a .md.
    content_base64: str


def safe_filename(name: str) -> str:
    """A filename that cannot escape the exports folder.

    Not a sanitiser that tries to be clever, a whitelist. The name arrives
    from the browser, and the browser is not the trust boundary here even
    though the app is single-user: the AI writes some of these names.
    """
    cleaned = os.path.basename(str(name))  # drops any directory part, "..", drive letters
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", cleaned).strip(". ")
    if not cleaned:
        raise HTTPException(status_code=422, detail="That filename can't be used.")
    return cleaned[:120]


def _within_exports(exports: Path, name: str) -> Path:
    """`exports / name`, refusing anything whose resolved path lands outside
    `exports`. `safe_filename` already whitelists to a flat, traversal-free
    name, but CodeQL's `py/path-injection` still flagged the join as tainted
    (alerts #289/#290): the same shape HANDOVER.md already documents for
    the update-apply SSRF fix: a query's sanitiser recognition is narrower
    than "the code is provably safe," so the fix is a real containment
    check at the point of use, not a stronger filter upstream of it.

    **Third attempt at the exact recognised shape, not just an equivalent
    check.** `os.path.realpath`/`os.path.normpath`/`os.path.abspath` are all
    modelled by CodeQL's Python library as `Path::PathNormalization`, they
    mark the result "normalised" but do not by themselves clear the taint.
    The actual barrier is `Path::SafeAccessCheck`, whose only recognised
    Python implementation is a bare `<path>.startswith(<base>)` call used as
    a guard's sole condition (`if not fullpath.startswith(base_path): raise`
    - GitHub's own CWE-022 remediation example, and the shape
    `StartswithCall` in the standard library actually matches). The first
    attempt here used `Path.resolve()`/`Path.relative_to()`, which CodeQL's
    Python model does not extend `PathNormalization`/`SafeAccessCheck` to at
    all. The second attempt switched to `os.path` but combined the guard
    with `candidate != base and` and appended `+ os.sep` to the `startswith`
    argument: still flagged, most likely because a compound condition and a
    computed (rather than bare) argument stop the guard-node matcher from
    recognising it as the same `SafeAccessCheck` shape; a query's pattern
    matcher can be exactly this literal about it.

    So: the single-condition, bare-argument form below, and nothing else.
    The dropped nuance (a candidate exactly equal to `base`, and a
    sibling-directory collision like `base-evil` slipping past a
    separator-less prefix check) is not a real gap here specifically, 
    `safe_filename` already strips every path separator out of `name`
    before either caller passes it in, so `os.path.join(base, name)` can
    only ever produce `base + os.sep + <flat name>`, never a sibling path or
    `base` itself unless `name` were empty (already rejected upstream).
    """
    base = os.path.realpath(str(exports))
    candidate = os.path.realpath(os.path.join(base, name))
    if not candidate.startswith(base):
        raise HTTPException(status_code=422, detail="That filename can't be used.") from None
    return Path(candidate)


def _within_dir(base_dir: Path, name: str) -> Path:
    """`_within_exports`'s own containment check, generalised to any base
    directory: the PDF-page endpoints' `_media_upload_path` and the two
    attachment `pdf-page`/`pdf-info` routes each build a path from a name
    that traces back to a request parameter (via a DB round trip, but
    CodeQL's `py/path-injection` tracks the taint through the query filter
    regardless), the same shape `_within_exports` already exists to close.
    Kept as its own function rather than reusing `_within_exports` directly:
    that one is precision-tuned to the exact guard shape CodeQL's
    `Path::SafeAccessCheck` recognises (see its own long comment on how many
    equivalent-looking forms it rejected) and duplicating the same five
    lines here is safer than risking that tuning by generalising its name
    or signature for a second, differently-named caller.
    """
    base = os.path.realpath(str(base_dir))
    candidate = os.path.realpath(os.path.join(base, name))
    if not candidate.startswith(base):
        raise HTTPException(status_code=422, detail="That file can't be used.") from None
    return Path(candidate)


@router.post("/files/save")
def save_generated_file(body: SaveFileBody) -> dict:
    """Write a generated export next to the notes and say where it went."""
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="That file couldn't be read.") from exc
    if len(data) > MAX_SAVE_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large to save.")

    exports = _exports_dir()
    exports.mkdir(parents=True, exist_ok=True)
    name = safe_filename(body.filename)
    target = _within_exports(exports, name)
    # Never silently overwrite: two exports of the same chat on the same day
    # are two files someone may want to compare.
    if target.exists():
        stem, suffix = target.stem, target.suffix
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = _within_exports(exports, f"{stem}-{stamp}{suffix}")
    target.write_bytes(data)
    return {"path": str(target), "filename": target.name, "bytes": len(data)}


@router.post("/files/open-exports-folder")
def open_exports_folder() -> dict:
    """Reveal the exports folder in the OS file manager.

    Asked for directly ("I have to dig in the app data files to find and
    access them") after `save_generated_file` above started writing graph
    PNGs, chat exports and the like into `data_dir/exports` with only a
    toast naming the path, real, but no help finding it again later.
    Desktop only: a browser tab has no file manager to hand this to, and
    `webbrowser.open`-ing a `file://` URL from a server request a browser
    could also reach is a foothold a purely local desktop shell doesn't
    have to give a page.
    """
    if os.getenv("MEMORYMAP_DESKTOP") != "1":
        raise HTTPException(
            status_code=409, detail="Only the desktop app can open a file manager window."
        )
    exports = _exports_dir()
    exports.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            # Safe even though the path can now be user-configured: passed as
            # a single argument, never through a shell, and _validated_export_dir
            # already refused anything that isn't a real, writable directory.
            os.startfile(exports)
        elif sys.platform == "darwin":
            # Popen, not run(): the launcher forks its own file-manager window
            # and normally returns at once, but this request must not hang
            # waiting on a GUI process either way, same reasoning as
            # `restart_in_console_mode` being fire-and-forget rather than
            # something this response waits on.
            subprocess.Popen(["open", str(exports)])
        else:
            subprocess.Popen(["xdg-open", str(exports)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Couldn't open {exports}: {exc}") from exc
    return {"path": str(exports)}


#: What `/media/` will accept and, more to the point, what it will serve.
#:
#: This folder exists for images dropped into markdown, and `/media/{name}`
#: serves its contents from the app's **own origin**: so an `.html` or `.svg`
#: landing here is a script running with the notebook's cookies and unlock
#: token, not a picture. That is a stored-XSS shape even though the app is
#: single-user and local, and it is worth closing for one reason above the
#: others: the AI can write into this folder too, so "the only person who can
#: put a file here is the person at the keyboard" is not true.
#:
#: An allowlist rather than a denylist of dangerous types, because the failure
#: mode of a missing entry is "this image didn't upload", and the failure mode
#: of a missed denylist entry is the paragraph above.
MEDIA_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".pdf"}
)


@router.post("/media/upload")
def upload_media(
    file: UploadFile,
    direct: bool = Form(False),
    session: Session = Depends(get_session),
) -> dict:
    """General file/image upload for drag-and-drop in markdown (documents &
    notes), and for the Library's own direct "Upload images" button.

    `direct` distinguishes the two: a note, document or chat composer
    upload is *staged*: it may be discarded before ever being saved or
    sent, so nothing runs on it here (see `direct` below) and OCR/
    captioning/vision-OCR instead fire when whatever referenced it is
    actually committed (`core/media_process.py`, called from the note,
    document and conversation save routes). The Library's own upload
    button sends `direct=True`: there is no separate "save" step for it: 
    the upload itself *is* the commit, the third case named directly
    ("uploaded directly to the library").
    """
    media_dir = deps.get_config().data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "file").suffix[:12].lower()
    if suffix not in MEDIA_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Only images and PDFs can be dropped in here. "
                "Use the note's attachments for anything else."
            ),
        )
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = media_dir / stored_name

    size = 0
    with destination.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                out.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File is larger than 50 MB")
            out.write(chunk)

    original_name = file.filename or stored_name
    # `size` was already counted above while streaming the upload to disk, 
    # storing it here means `GET /media` never has to `stat()` this file to
    # answer "how big is it" (PLAN.md §0 P6).
    upload = MediaUpload(
        filename=stored_name, original_name=original_name[:300], size_bytes=size
    )
    session.add(upload)
    session.commit()
    session.refresh(upload)
    # OCR, captioning and vision OCR (core/media_process.py) all run on a
    # background thread, never on this request, Tesseract alone can take a
    # second or two per image, and a vision-model round trip far longer.
    # Only fired here for `direct=True` (the Library's own upload button);
    # every staged upload gets processed later, at the moment it's actually
    # committed: see this function's own docstring and media_process.py's.
    if direct:
        media_process.process_committed_upload(upload, media_dir)
    # `id` lets a caller that changes its mind (the capture form's own
    # attachment chip, removable with a click) call DELETE /media/{id}
    # instead of just detaching the markdown reference and leaving the
    # file behind: asked for directly.
    return {"id": upload.id, "url": f"/media/{stored_name}", "filename": original_name}


class MediaUploadOut(BaseModel):
    id: int
    url: str
    original_name: str
    #: "" until OCR finishes (or never, off the tesseract binary, or a PDF)
    #:, never null over the wire, so the frontend can filter on it with a
    #: plain substring match without a null check at every call site.
    ocr_text: str = ""
    #: "" until captioning finishes (or never, no vision model available, or
    #: a PDF): same never-null convention as ocr_text, same reason.
    caption: str = ""
    #: Which model wrote `caption`, or "" when there is none or it was only
    #: ever typed by hand. Surfaced so a caption reads as one model's guess,
    #: not the app's own opinion (asked for directly).
    caption_model: str = ""
    #: True once a person has typed over an AI caption, or typed one from
    #: scratch: see `MediaUpload.caption_edited`'s docstring.
    caption_edited: bool = False
    #: A vision model's verbatim transcription of text in the image
    #: (`ai/vision_ocr.py`), distinct from `ocr_text` (Tesseract) and from
    #: `caption` (a description). "" until run, or when a run found no
    #: legible text: same never-null convention as the other two.
    vision_ocr_text: str = ""
    #: Which model wrote `vision_ocr_text`, or "" when there is none.
    vision_ocr_model: str = ""
    #: When it was uploaded, ISO-8601. Asked for with the lightbox rework, 
    #: "maybe it can have the image information and other info about it below
    #: the image", and it is the one fact of that kind the browser cannot
    #: work out for itself: dimensions come from the decoded image, the name
    #: is already here, and a byte count would cost one `stat` per row on
    #: every gallery load for a number nobody asked for.
    created_at: str = ""
    #: **Where this file is actually used**, one entry per note, document or
    #: board that references it, as `{kind, id, label}`. The gallery showed a
    #: thumbnail, a filename and two empty prompts and could not answer the
    #: only question anyone brings to it: what is this attached to? Empty
    #: means genuinely unreferenced (the same condition the orphan check uses
    #:, both read `media_gc.referenced_names`, so they cannot disagree).
    used_by: list[dict] = []
    #: True when a locked private note made the usage scan incomplete, so an
    #: empty `used_by` means "could not check" rather than "not used". The UI
    #: must not call a file unused on this basis.
    usage_incomplete: bool = False
    #: Size on disk in bytes; 0 when the file cannot be stat'ed (a row
    #: outliving its file is a real state the gallery already draws a
    #: placeholder for). Asked for directly with the Files sub-tab redesign:
    #: "file details such as the type, size, topic/category".
    size_bytes: int = 0
    #: How many of this document's pages have a stored reading, see
    #: `AttachmentGalleryOut.pages_read` for why the count is sent rather than
    #: derived from the joined text.
    pages_read: int = 0


#: A page of the gallery, not a ceiling on how many uploads a notebook may
#: hold: `X-Total-Count` reports the real size and `offset` reaches the
#: rest, so `renderLibraryImagesGallery` and `ocrLoadSiblings` (library.js)
#: page until they have everything. 200 rather than the grid's own page
#: size because both of those need the whole set (one to search it, one to
#: build the OCR workspace's rail), and 200 keeps the number of round trips
#: sane. The **max** is 500 rather than the 1000 the document and reminder
#: lists allow, because a row here is not a fixed cost: `ocr_text`,
#: `caption` and `vision_ocr_text` ride along, and a page of scanned text
#: can be kilobytes on its own, so a row count is a poor proxy for bytes and
#: the ceiling is set lower to compensate.
MEDIA_PAGE_SIZE = 200
MEDIA_PAGE_SIZE_MAX = 500


@router.get("/media", response_model=list[MediaUploadOut])
def list_media(
    response: Response,
    limit: int = Query(default=MEDIA_PAGE_SIZE, ge=1, le=MEDIA_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[MediaUploadOut]:
    """A page of the uploads `/media/upload` has produced: asked for
    directly (a gallery for note-attached and whiteboard images alike).
    Newest first, the same convention the Library's own sort defaults to.

    Paged for the reason `GET /entries` is: one response used to be the
    whole table (300 uploads measured at 117.6 KB, growing with the table),
    which is a real risk for a local app that is supposed to degrade
    gracefully rather than stall. `X-Total-Count` is the real size whatever
    the page, and the id breaks a tie on `created_at` so two uploads made in
    the same second cannot swap places between pages and hide a row.
    """
    total = session.scalar(select(func.count(MediaUpload.id))) or 0
    uploads = (
        session.query(MediaUpload)
        .order_by(MediaUpload.created_at.desc(), MediaUpload.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    response.headers["X-Total-Count"] = str(total)
    # One scan for the whole gallery rather than one per file: `usage_map`
    # walks each table once and inverts the result, so this stays a single
    # pass no matter how many uploads there are.
    used, usage_incomplete = media_gc.usage_map(session)
    media_dir = deps.get_config().data_dir / "media"

    # PLAN.md §0 P6: `size_bytes` used to be `Path.stat()`'d here on *every*
    # row of *every* call, the disk hit this whole column exists to remove.
    # Uploads made after the column existed already carry it (see
    # `upload_media`); this backfills only the rows that predate it, NULL,
    # never 0, is what a pre-existing row reads as (the column's own
    # docstring): one `stat()` each, the only time each row ever pays it,
    # in a single commit rather than one write per row.
    unsized = [u for u in uploads if u.size_bytes is None]
    if unsized:
        for u in unsized:
            try:
                u.size_bytes = (media_dir / u.filename).stat().st_size
            except OSError:
                # A row whose file is gone still lists, the gallery has a
                # placeholder for exactly that, so this leaves size_bytes at
                # 0 rather than leaving it NULL (which would just retry the
                # same failing stat() on every future call) or raising.
                u.size_bytes = 0
        session.commit()

    media_page_text = _page_read_text_map("upload", [u.id for u in uploads])
    media_pages_read = _page_read_count_map("upload", [u.id for u in uploads])
    return [
        MediaUploadOut(
            id=u.id,
            pages_read=media_pages_read.get(u.id, 0),
            used_by=used.get(u.filename, []),
            usage_incomplete=usage_incomplete,
            size_bytes=u.size_bytes or 0,
            url=f"/media/{u.filename}",
            original_name=u.original_name,
            ocr_text=u.ocr_text or "",
            caption=u.caption or "",
            caption_model=u.caption_model or "",
            caption_edited=u.caption_edited,
            vision_ocr_text=u.vision_ocr_text or media_page_text.get(u.id, ""),
            vision_ocr_model=u.vision_ocr_model or "",
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in uploads
    ]


class MediaOrphansOut(BaseModel):
    orphans: list[MediaUploadOut]
    #: True when a locked private note made the check incomplete, the list
    #: above is not exhaustive in that case, and DELETE refuses to act on it.
    skipped_private: bool
    #: How many uploads DELETE actually removed. Always 0 for the GET dry run.
    deleted: int = 0


# Declared ahead of the `/media/{upload_id}` routes below: FastAPI compiles
# `{upload_id}` as a plain path segment and only rejects a non-integer value
# (like "orphans") when the handler runs, by which point an earlier-declared
# `/media/{upload_id}` would already have claimed the match and returned a
# 422 instead of ever reaching these.
@router.get("/media/orphans", response_model=MediaOrphansOut)
def list_orphaned_media(session: Session = Depends(get_session)) -> MediaOrphansOut:
    """Uploads no live note, document or whiteboard image object still
    points at (ROADMAP.md item 20a). A dry run: nothing is deleted here.
    """
    orphans, skipped_private = media_gc.find_orphaned_media(session)
    return MediaOrphansOut(
        orphans=[
            MediaUploadOut(id=u.id, url=f"/media/{u.filename}", original_name=u.original_name)
            for u in orphans
        ],
        skipped_private=skipped_private,
    )


@router.delete("/media/orphans", response_model=MediaOrphansOut)
def clean_orphaned_media(session: Session = Depends(get_session)) -> MediaOrphansOut:
    """Deletes every currently-orphaned upload's file and tracking row.

    Refuses to delete anything (`skipped_private: true`, `deleted: 0`)
    while a locked private note leaves the check incomplete, see
    `media_gc`'s own docstring for why.
    """
    media_dir = deps.get_config().data_dir / "media"
    deleted, skipped_private = media_gc.delete_orphaned_media(session, media_dir)
    return MediaOrphansOut(
        orphans=[
            MediaUploadOut(
                id=row["id"], url=f"/media/{row['filename']}", original_name=row["original_name"]
            )
            for row in deleted
        ],
        skipped_private=skipped_private,
        deleted=len(deleted),
    )


# Declared ahead of `/media/{upload_id}` for the same reason `/media/orphans`
# above is: "meta" would otherwise be matched as an `{upload_id}` and 422 out
# before ever reaching this handler.
@router.get("/media/meta/{filename}", response_model=MediaUploadOut)
def media_meta(filename: str, session: Session = Depends(get_session)) -> MediaUploadOut:
    """Everything the app knows *about* one upload, looked up by its stored
    filename: which is the only identifier most of the app actually holds.

    Reported directly: the lightbox showed a caption, OCR text and the
    picture's own facts when opened from the Image Gallery and nothing at
    all anywhere else. The cause was not the lightbox, it was that
    `openLightbox` took this metadata as *arguments*, and of its nine
    callers only the gallery had a full `MediaUpload` row to pass. Every
    other one (a note's attachment, a chat image, a graph or dashboard
    thumbnail, a whiteboard object) has a `/media/<filename>` url and
    nothing else, so it passed a filename and a url and the panel below the
    picture stayed empty.

    Handing the lightbox a way to *ask* fixes it in one place instead of
    nine, and keeps working for any caller added later, which is the same
    reason `GET /media` exists rather than each surface keeping its own
    list. Keyed on filename rather than id precisely because a url is what
    those callers have.
    """
    upload = session.query(MediaUpload).filter(MediaUpload.filename == filename).first()
    if not upload:
        # A url can outlive its row: deleting an upload deliberately leaves
        # any note still pointing at it alone (see delete_media below), so a
        # miss here is an ordinary state, not a fault.
        raise HTTPException(status_code=404, detail="No upload by that name.")
    return MediaUploadOut(
        id=upload.id,
        url=f"/media/{upload.filename}",
        original_name=upload.original_name,
        ocr_text=upload.ocr_text or "",
        caption=upload.caption or "",
        caption_model=upload.caption_model or "",
        caption_edited=upload.caption_edited,
        vision_ocr_text=upload.vision_ocr_text or "",
        vision_ocr_model=upload.vision_ocr_model or "",
        created_at=upload.created_at.isoformat() if upload.created_at else "",
    )


@router.get("/media/text/{filename}", response_model=AttachedFileTextOut)
def media_text(filename: str, session: Session = Depends(get_session)) -> AttachedFileTextOut:
    """One uploaded document's *text*, for reading it in the lightbox.

    Asked for directly: the lightbox should become "a sort of document
    preview… for viewing pdfs, word documents, spreadsheets, text files, code
    files etc but in a presentable way that isn't editable".

    Almost none of that is new work, and deliberately so, `docview.extract`
    and its whole format table already existed for **attachments**
    (`GET /files/{id}/text`), and it already returns the `kind`
    (markdown/code/plain) that says how to render and the `source` that says
    whether a human wrote the text or a vision model read it off a scan. The
    only thing missing was that uploads, which is what the Library and the
    lightbox actually hold, had no way to reach it. So this is the same
    extraction pointed at `media/` instead of `uploads/`.

    **There is no `PUT` beside this one, and that is not an oversight.** Its
    sibling `save_attached_file_text` exists because a note's attachment can
    be a .md, a .txt or a source file. A `/media/` upload cannot: `MEDIA_SUFFIXES`
    is images and PDF, so `editable` here is always False and a save route
    would be a feature that never ran once, the shape CLAUDE.md names. The
    flag and its message are still returned, so the viewer can say *why*
    rather than silently omitting Edit.

    Deliberately returns **text, never the file**, for the reason
    `read_file_text` above states at length and `media_file` at the bottom of
    this module explains: what this sends has already stopped being a .docx,
    so a viewer built on it cannot inherit the serve-it-inline problem once
    per file type. That is also why the preview is read-only, a property of
    the extraction, not a missing feature. Editing here would mean writing
    text back into a format it was never in.
    """
    upload = session.query(MediaUpload).filter(MediaUpload.filename == filename).first()
    if not upload:
        raise HTTPException(status_code=404, detail="No upload by that name.")
    path = deps.get_config().data_dir / "media" / upload.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    # Same scanned-PDF fallback the attachment viewer passes. It only does any
    # work for a PDF with no text layer, and only when the pdfpages extra and
    # a vision model are both present; every other file returns before it is
    # consulted.
    viewed = docview.extract(path, vision_reader=vision_ocr.pdf_reader_or_none())
    editable, edit_message = docview.editability(path, viewed)
    return AttachedFileTextOut(
        filename=upload.original_name,
        kind=viewed.kind,
        source=viewed.source,
        text=viewed.text,
        truncated=viewed.truncated,
        message=viewed.message,
        editable=editable,
        edit_message=edit_message,
    )


def _media_upload_path(session: Session, filename: str) -> tuple[MediaUpload, Path]:
    upload = session.query(MediaUpload).filter(MediaUpload.filename == filename).first()
    if not upload:
        raise HTTPException(status_code=404, detail="No upload by that name.")
    path = _within_dir(deps.get_config().data_dir / "media", upload.filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    return upload, path


@router.get("/media/pdf-info/{filename}", response_model=PdfInfoOut)
def media_pdf_info(filename: str, session: Session = Depends(get_session)) -> PdfInfoOut:
    """Page count for `pdf_page` below to page through, deliberately its
    own round trip rather than folded into `media_text`'s response, so the
    lightbox can show real PDF pages **without ever calling `media_text` (and
    therefore without markitdown or a vision model in the loop at all)**.
    That split is the point: viewing a PDF like a PDF and *reading* it with
    AI are two different questions (`docview.py`'s module docstring answers
    the second one at length), and until now this app only had an answer for
    the second: a scanned lecture PDF got stuck on the AI extraction path
    with no way to just look at the pages, direct instruction: "pdfs and
    documents should be viewable, accessible and manageable without the ai,
    even if the ai cant read them."
    """
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=422, detail="Not a PDF.")
    _upload, path = _media_upload_path(session, filename)
    if not pdfpages.available():
        return PdfInfoOut(
            available=False,
            pages=0,
            message=(
                "Viewing PDF pages needs a small rasteriser: install "
                "“Read scanned PDFs” in Settings → Extras."
            ),
        )
    count = pdfpages.page_count(path)
    if count == 0:
        return PdfInfoOut(
            available=False,
            pages=0,
            message=(
                "This PDF couldn't be opened. It may be corrupted, "
                "password-protected, or saved in a way this app's reader "
                "doesn't support."
            ),
        )
    return PdfInfoOut(available=True, pages=count)


@media_router.get("/media/pdf-page/{filename}/{index}")
def media_pdf_page(filename: str, index: int, session: Session = Depends(get_session)) -> Response:
    """One page of an uploaded PDF, rasterised to a PNG, the actual pixels
    a `<img>` in the lightbox loads, one per page, so a PDF scrolls like a
    PDF. On `media_router` rather than `router`: this is loaded the same
    declarative way `/media/{filename}` already is (`mediaSrc()` in app.js
    appends the unlock token as a query param for exactly these routes,
    since a plain `<img src>` cannot carry a header), not fetched with
    `apiJson` the way `media_pdf_info` above is.

    Always a **freshly rendered PNG**, never the PDF's own bytes: the
    security reasoning `get_media`'s own docstring gives for refusing to
    serve a PDF inline (a script host, from a folder not guaranteed to hold
    only what this app wrote) does not apply to pixels this process drew
    itself. A rasterised page cannot carry a PDF action, an embedded script,
    or anything else a PDF's own structure can.
    """
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Not a PDF.")
    _upload, path = _media_upload_path(session, filename)
    png = pdfpages.render_page(path, index)
    if png is None:
        raise HTTPException(status_code=404, detail="That page doesn't exist.")
    # Regenerated on every request rather than cached to disk: ~20ms/page
    # (measured, pdfpages.py's own docstring) and this app has no existing
    # per-file render cache to hang a second one off. `Cache-Control`
    # still lets the *browser* avoid re-fetching a page it already has.
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


#: An embed of one stored file: `![alt](/media/name.png)` or
#: `![alt](/files/12)`, with the optional title markdown allows. Written
#: against a *literal* url (escaped by the caller), so there is no
#: user-controlled repetition in it, the shape CodeQL flags as
#: polynomial-ReDoS is exactly what this avoids.
def _embed_pattern(url: str) -> re.Pattern[str]:
    #: Markdown's optional title, in either quote style.
    title = r"""(?:\s+["'][^"'\n]{0,200}["'])?"""
    return re.compile(r"!\[[^\]\n]{0,200}\]\(" + re.escape(url) + title + r"\)")


def _strip_embeds(session: Session, url: str) -> list[int]:
    """Remove every `![...](url)` from the notes that hold one.

    Reported directly: *"notes still mention removed images"*. Deleting the
    file left the markdown behind, so the note rendered a placeholder saying
    the image was gone, forever, with no way to tidy it but editing the note
    by hand and knowing what to look for.

    Only the **embed** is removed, never a link: `[see the scan](/media/x.png)`
    is a sentence the author wrote and would be a hole in their prose if it
    vanished. And only exact-url matches, so nothing else in the note moves.
    """
    pattern = _embed_pattern(url)
    touched: list[int] = []
    #: `LIKE` narrows the scan to notes that mention the url at all; the
    #: regex above decides. A private note is encrypted at rest and its
    #: content is not readable here, which is also why one cannot embed a
    #: Library image into one in the first place.
    rows = session.scalars(
        select(Entry).where(
            Entry.is_deleted.is_(False),
            Entry.is_private.is_(False),
            Entry.content.contains(url),
        )
    ).all()
    for entry in rows:
        cleaned = pattern.sub("", entry.content or "")
        if cleaned == entry.content:
            continue
        #: The blank line the embed used to sit on goes with it, otherwise a
        #: note loses a picture and gains a gap where it was.
        entry.content = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        touched.append(entry.id)
    if touched:
        session.commit()
    return touched


@router.delete("/media/{upload_id}")
def delete_media(
    upload_id: int,
    strip_references: bool = False,
    session: Session = Depends(get_session),
) -> dict:
    """Removes the file and its tracking row.

    `strip_references` also takes the `![...](...)` out of every note that
    embedded it: asked for after the placeholder shipped: a note that keeps
    pointing at a file you deleted is a note that renders "this image was
    removed" for the rest of its life. Off by default, because deleting a
    file and editing someone's notes are different acts and the second one
    has to be chosen: the caller asks, the UI offers it in the confirm.
    """
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    media_dir = (deps.get_config().data_dir / "media").resolve()
    candidate = (media_dir / upload.filename).resolve()
    cleaned: list[int] = []
    if strip_references:
        #: Before the row goes: the url is built from `upload.filename`.
        cleaned = _strip_embeds(session, f"/media/{upload.filename}")
    if candidate.is_relative_to(media_dir):
        candidate.unlink(missing_ok=True)
    session.delete(upload)
    session.commit()
    return {"status": "ok", "cleaned_notes": cleaned}


class MediaRenameBody(BaseModel):
    original_name: str = Field(min_length=1, max_length=300)


@router.put("/media/{upload_id}", response_model=MediaUploadOut)
def rename_media(
    upload_id: int, body: MediaRenameBody, session: Session = Depends(get_session)
) -> MediaUploadOut:
    """Rename a Library image, the display name only.

    `original_name` is a label, exactly like `Attachment.filename`: the bytes
    live under `upload.filename`, a generated name, and nothing here touches
    the disk. So it goes through the same validator rather than a laxer one of
    its own: two "rename a file" endpoints in one module with two different
    ideas of what a filename may contain is how the strict one quietly stops
    being the rule.
    """
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    try:
        upload.original_name = manager.validate_attachment_filename(body.original_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return MediaUploadOut(
        id=upload.id, url=f"/media/{upload.filename}", original_name=upload.original_name
    )


class CaptionBody(BaseModel):
    #: The write-once rule (`captioning.caption_and_store`) otherwise leaves
    #: an existing caption alone, this is the one way to overwrite one,
    #: asked for directly: "if one is already there, another doesn't need
    #: to be written unless the user presses the button to rewrite it."
    force: bool = False
    #: A caption typed by hand instead of generated, asked for directly
    #: ("allow for manual input of image captions"). `None` (the default)
    #: means "generate one"; any string, including "", sets the caption to
    #: exactly that text and skips the model entirely, a person editing a
    #: caption is not asking for a second opinion. `""` clears it back to
    #: uncaptioned rather than storing an empty string as if it meant
    #: something, matching the null/"not captioned yet" convention
    #: `MediaUpload.caption` already uses.
    text: str | None = Field(default=None, max_length=2000)


@router.post("/media/{upload_id}/caption", response_model=MediaUploadOut)
def caption_media(
    upload_id: int, body: CaptionBody = CaptionBody(), session: Session = Depends(get_session)
) -> MediaUploadOut:
    """Generate (or, with `force`, regenerate) a caption for one image, or, 
    with `text`, set one by hand. The manual-generate trigger and the
    manual-edit field are both reached from the Library and the Notes tab.

    Runs synchronously: captioning one image is a single model round trip,
    no different in shape from the AI-edit or link-reason calls this app
    already blocks on behind a spinner. `caption_and_store` opens its own
    session (the same shape `ocr.extract_and_store` uses from a background
    thread): `session.refresh` below picks up what it committed.
    """
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    is_picture = Path(upload.filename).suffix.lower() in captioning.CAPTION_SUFFIXES
    if body.text is not None:
        # A hand-typed caption needs no model at all, set it and return,
        # skipping every Ollama/vision-model check below.
        stripped = body.text.strip() or None
        upload.caption = stripped
        if stripped:
            # `caption_model` is left as-is: if this text started as one
            # model's caption, the badge can still credit it alongside
            # "edited" instead of losing that history the moment someone
            # fixes a typo (see MediaUpload.caption_edited's docstring).
            upload.caption_edited = True
        else:
            # Cleared back to "no caption", a full reset, not a caption
            # with nothing to show for whichever model or person last wrote one.
            upload.caption_model = None
            upload.caption_edited = False
        session.commit()
    elif not is_picture:
        #: The same document describer the attachment route uses, for the
        #: rows that arrived through `/media/upload` rather than as a note's
        #: attachment: both kinds land in the same Files sub-tab, and a
        #: button that works on one of them and 415s on the other would be
        #: the same report again from the other side.
        if upload.caption and not body.force:
            pass
        else:
            if not deps.get_ollama().is_running():
                raise HTTPException(status_code=409, detail="The AI model isn't running.")
            media_dir = deps.get_config().data_dir / "media"
            path = _within_dir(media_dir, upload.filename)
            readable = (upload.ocr_text or "").strip() or (docview.extract(path).text or "").strip()
            if not readable:
                raise HTTPException(
                    status_code=415,
                    detail="There is no readable text in this file to describe.",
                )
            models = deps.get_model_manager()
            described = captioning.describe_document(readable, models, deps.get_ollama())
            upload.caption = described or None
            upload.caption_model = models.utility_model() if described else None
            upload.caption_edited = False
            session.commit()
    else:
        if not deps.get_ollama().is_running():
            raise HTTPException(status_code=409, detail="The AI model isn't running.")
        model = deps.get_model_manager().resolve_vision_model(deps.get_ollama())
        if not model:
            raise HTTPException(
                status_code=409,
                detail="No installed model reports it can see images, install or "
                "pick one in Settings → Models.",
            )
        media_dir = deps.get_config().data_dir / "media"
        captioning.caption_and_store(upload.id, media_dir / upload.filename, force=body.force)
        session.refresh(upload)
    return MediaUploadOut(
        id=upload.id,
        url=f"/media/{upload.filename}",
        original_name=upload.original_name,
        ocr_text=upload.ocr_text or "",
        caption=upload.caption or "",
        caption_model=upload.caption_model or "",
        caption_edited=upload.caption_edited,
        vision_ocr_text=upload.vision_ocr_text or "",
        vision_ocr_model=upload.vision_ocr_model or "",
    )


class OcrBody(BaseModel):
    #: A correction typed by hand instead of re-run, asked for directly
    #: ("allow the user to access, view, and edit OCR extracted text"),
    #: same "None means generate, any string sets it exactly" convention as
    #: `CaptionBody.text`. `""` clears it back to "nothing extracted",
    #: matching `ocr_text`'s own null/"not run or found nothing" meaning.
    text: str | None = Field(default=None, max_length=10_000)


@router.post("/media/{upload_id}/ocr", response_model=MediaUploadOut)
def ocr_media(
    upload_id: int, body: OcrBody = OcrBody(), session: Session = Depends(get_session)
) -> MediaUploadOut:
    """Re-read one image with Tesseract, or, with `text`, set the
    extracted text by hand. The manual retry asked for directly: `ocr_text`
    otherwise only ever gets written once, automatically, at the moment the
    image is actually saved into a note/document/chat (`core/media_process.
    py`), this is the only way to try again (a first Tesseract pass that
    misread something, or ran before Tesseract was installed) or to correct
    what it found.

    `extract_text`/`extract_and_store` (core/ocr.py) have no write-once
    guard of their own, every call re-reads the image, which is exactly
    what "retry" needs, no `force` field required. Runs synchronously:
    local OCR is fast, and the frontend already blocks caption/vision-OCR
    regenerate behind a spinner the same way.
    """
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    if Path(upload.filename).suffix.lower() not in ocr.OCR_SUFFIXES:
        raise HTTPException(status_code=415, detail="Only images can be read this way.")
    if body.text is not None:
        upload.ocr_text = body.text.strip() or None
        session.commit()
    else:
        media_dir = deps.get_config().data_dir / "media"
        ocr.extract_and_store(upload.id, media_dir / upload.filename)
        session.refresh(upload)
    return MediaUploadOut(
        id=upload.id,
        url=f"/media/{upload.filename}",
        original_name=upload.original_name,
        ocr_text=upload.ocr_text or "",
        caption=upload.caption or "",
        caption_model=upload.caption_model or "",
        caption_edited=upload.caption_edited,
        vision_ocr_text=upload.vision_ocr_text or "",
        vision_ocr_model=upload.vision_ocr_model or "",
    )


class OcrRegionBox(BaseModel):
    #: Fractions of the image, top-left origin, see `ocr.extract_regions`
    #: for why these are not pixels.
    x: float
    y: float
    w: float
    h: float


class OcrRegionOut(BaseModel):
    index: int
    #: From Tesseract: "text" or "heading" only: it reports boxes and
    #: confidences, and a semantic label guessed from box *geometry* would be a
    #: guess presented as a fact. From a reading (`ocr.regions_from_reading`),
    #: also "list", "table" and "code", because those are read off the block's
    #: own shape, pipes, bullets, a fence, which is evidence rather than
    #: inference.
    kind: str
    text: str
    confidence: float
    #: **None when nothing measured where this block sits.** A reading gives
    #: order and structure but no pixels, and a box covering the whole page
    #: would be a wrong answer rather than a missing one, the workspace can
    #: render a list without a rectangle, but it cannot un-draw a lie about
    #: where the text was.
    box: OcrRegionBox | None = None


class OcrRegionsOut(BaseModel):
    width: int
    height: int
    regions: list[OcrRegionOut]
    #: "tesseract" when the boxes are real; "reading" when they were derived
    #: from the text the vision model (or any other reader) already produced, 
    #: real blocks in real order, with no box; "none" when the page has not
    #: been read at all. The reader is told which, because a block list without
    #: boxes and a page of measured rectangles answer different questions and
    #: the UI draws them differently.
    #:
    #: "stored-text" is the retired third value: it meant "one region covering
    #: the whole page", which was a fallback that told you nothing about
    #: structure and existed only because splitting the reading had not been
    #: tried. Nothing emits it now.
    source: str
    message: str = ""
    #: How many pages this file has, when it is a document the workspace can
    #: page through (a PDF). 1 for an image, one page, no rail. The page rail
    #: is built from this rather than from a second request, because the
    #: workspace needs the count before it can draw anything at all.
    pages: int = 1
    #: Which page (0-based) these regions were read from. Echoed rather than
    #: assumed: `page` is clamped into range server-side, so a workspace that
    #: asked for page 99 of a 3-page PDF must be told which page it actually
    #: got.
    page: int = 0


#: **Reading a PDF page is rasterise-then-read, not a second OCR engine.**
#:
#: Reported: *"I begin generating ocr for a document… is the document ocr even
#: working??"* It was not, for the case that matters: `ocr.OCR_SUFFIXES` is
#: raster formats only, so both region routes below answered a PDF with 415, 
#: the workspace this feature was asked for ("for the document ocr I want smth
#: like this", three screenshots of Baidu's Unlimited-OCR) could not open a
#: document at all. Every piece needed already existed and was never joined up:
#: `core/pdfpages.py` renders a page to PNG for the lightbox, and
#: `ocr.extract_regions` reads a PNG.
def _pdf_regions_for(
    path: Path, index: int, stored_text: str, stored_label: str
) -> OcrRegionsOut:
    if not pdfpages.available():
        return OcrRegionsOut(
            width=0,
            height=0,
            regions=[],
            source="none",
            pages=0,
            message=(
                "Reading a PDF page needs the small PDF rasteriser: install "
                "the “PDF pages” extra in Settings → Optional extras."
            ),
        )
    count = pdfpages.page_count(path)
    if count <= 0:
        return OcrRegionsOut(
            width=0,
            height=0,
            regions=[],
            source="none",
            pages=0,
            message="That PDF could not be opened.",
        )
    index = max(0, min(index, count - 1))
    png = pdfpages.render_page(path, index)
    if not png:
        return OcrRegionsOut(
            width=0,
            height=0,
            regions=[],
            source="none",
            pages=count,
            page=index,
            message=f"Page {index + 1} could not be rendered.",
        )
    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / f"page-{index}.png"
        page_path.write_bytes(png)
        #: Stored text belongs to the *document*, not to this page. Offering
        #: the whole file's reading as page 7's fallback would be the app
        #: stating a guess about where the text came from as a fact, the same
        #: line `_regions_for`'s own "stored-text" badge exists to hold.
        out = _regions_for(page_path, stored_text if index == 0 else "", stored_label)
    out.pages = count
    out.page = index
    if out.source == "none":
        #: Points at the button, not at a system package. The vision reader is
        #: named first because it is the default and the one that needs no
        #: install; Tesseract is named too, but only when it is actually here, 
        #: an app that suggests a thing you do not have is an app telling you
        #: to go and solve a problem it created (see `READERS`, and the two
        #: opposite instructions this feature has been given).
        out.message = (
            f"Nothing has been read off page {index + 1} yet. "
            "Use “Read this page” to transcribe it."
        )
        if ocr.tesseract_available():
            out.message += (
                " Either reader works here, the AI vision model, or "
                "Tesseract, which is faster and marks where each block sits."
            )
    if out.source == "stored-text":
        out.message = f"{stored_label}: this is the whole document's reading, not page {index + 1}."
    return out


def _regions_for(path: Path, stored_text: str, stored_label: str) -> OcrRegionsOut:
    """Region extraction with the honest fallback both callers below share."""
    found = ocr.extract_regions(path)
    if found is not None:
        return OcrRegionsOut(
            width=found["width"],
            height=found["height"],
            regions=[OcrRegionOut(**region) for region in found["regions"]],
            source="tesseract",
            message="" if found["regions"] else "No text was found on this page.",
        )
    text = (stored_text or "").strip()
    if not text:
        return OcrRegionsOut(
            width=0,
            height=0,
            regions=[],
            source="none",
            message=(
                "This page hasn't been read yet, read it and its sections "
                "will appear here."
            ),
        )
    #: **The page was read; split what it said.** Reported as "the regions
    #: dont work without tesseract but surely there's a better way", and there
    #: is: the vision model is this app's primary reader and it returns the
    #: page in order with its structure intact, so the blocks are already
    #: there: only the rectangles are missing. `regions_from_reading` types
    #: them from their own shape and numbers them, which is what makes "this
    #: text came from section 4 of page 2" answerable with nothing installed.
    blocks = ocr.regions_from_reading(text)
    return OcrRegionsOut(
        width=0,
        height=0,
        regions=[OcrRegionOut(**block) for block in blocks],
        source="reading",
        message=(
            f"{stored_label}: sections come from the reading itself. "
            "Install Tesseract to also see where each one sits on the page."
        ),
    )


@router.get("/media/{upload_id}/ocr-regions", response_model=OcrRegionsOut)
def media_ocr_regions(
    upload_id: int, page: int = 0, session: Session = Depends(get_session)
) -> OcrRegionsOut:
    """The page, region by region, what the OCR workspace draws its boxes
    from. Asked for with three screenshots of Baidu's Unlimited-OCR: a page
    beside its regions, each separately readable, instead of one wall of
    text with no way to tell which part of the page a line came from."""
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ocr.OCR_SUFFIXES and suffix != ".pdf":
        raise HTTPException(status_code=415, detail="Only images and PDFs can be read this way.")
    path = _within_dir(deps.get_config().data_dir / "media", upload.filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    stored = (upload.vision_ocr_text or upload.ocr_text or "")
    label = (
        f"Read by {upload.vision_ocr_model or 'a vision model'}"
        if upload.vision_ocr_text
        else "Text already extracted from this file"
    )
    if suffix == ".pdf":
        return _pdf_regions_for(path, page, stored, label)
    return _regions_for(path, stored, label)


@router.get("/files/{attachment_id}/ocr-regions", response_model=OcrRegionsOut)
def attachment_ocr_regions(
    attachment_id: int, page: int = 0, session: Session = Depends(get_session)
) -> OcrRegionsOut:
    """`media_ocr_regions`'s sibling for an attached file. Two tables, two
    routes: the same split every other file endpoint in this module has."""
    attachment = _existing_attachment(session, attachment_id)
    suffix = Path(attachment.filename).suffix.lower()
    if suffix not in ocr.OCR_SUFFIXES and suffix != ".pdf":
        raise HTTPException(status_code=415, detail="Only images and PDFs can be read this way.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    stored = (attachment.vision_ocr_text or attachment.ocr_text or "")
    label = (
        f"Read by {attachment.vision_ocr_model or 'a vision model'}"
        if attachment.vision_ocr_text
        else "Text already extracted from this file"
    )
    if suffix == ".pdf":
        return _pdf_regions_for(path, page, stored, label)
    return _regions_for(path, stored, label)


class OcrPageReadOut(BaseModel):
    """One page of a document, read by a vision model."""

    page: int
    text: str = ""
    model: str = ""
    message: str = ""
    #: **What the figures on this page show**, a different claim from `text`,
    #: which is what the page *says*. Asked for directly: "image captioning,
    #: how it is done and displayed needs to be refined for pdf documents and
    #: other similar documents. with graphs, images and diagrams in them."
    #:
    #: On this model rather than in a separate response so the workspace and
    #: the lightbox render a page's reading and its description from one
    #: object; `""` when the page has never been described, which is the
    #: ordinary case and not an error. Same never-null convention the rest of
    #: this module keeps.
    caption: str = ""
    caption_model: str = ""


#: **A vision read scoped to the page you are looking at.**
#:
#: The existing vision path (`analyse`, kind="vision") reads a whole PDF, up
#: to `pdfpages.MAX_PAGES`, and stores one blob. That is the right shape for
#: "what is this document"; it is the wrong shape for the OCR workspace, where
#: the question is always "what does *this page* say" and a reader who wants
#: page 6 should not wait through five pages they have already checked.
#:
#: Nothing is stored: the workspace shows the reading beside the page and the
#: reader decides what to keep (Copy, Save to a note, or Save the reading onto
#: the file through the existing analyse endpoint). Reading is cheap to repeat
#: and a wrong transcription written onto the row is not.
def _reader_model(reader: str) -> str:
    """The model the named reader will actually use, or "" if there is none.

    One function so the picker (`ocr_readers`) and the read (`_vision_read_page`)
    cannot answer this differently, which is exactly what they did before, and
    is why "my ocr model shows as a vision model" survived a first fix.
    """
    manager = deps.get_model_manager()
    ollama = deps.get_ollama()
    if reader == "ocr":
        # The general "can anything here see an image" resolver. Named `ocr`
        # only because it is the *other* one from the workspace's default;
        # what it returns is whatever vision model the app would otherwise use.
        return manager.resolve_vision_model(ollama) or ""
    return manager.resolve_ocr_model(ollama) or ""


def _vision_read_page(path: Path, index: int, reader: str = "vision") -> OcrPageReadOut:
    if not pdfpages.available():
        return OcrPageReadOut(
            page=index,
            message=(
                "Reading a PDF page needs the small PDF rasteriser: install "
                "the “PDF pages” extra in Settings → Optional extras."
            ),
        )
    if not deps.get_ollama().is_running():
        raise HTTPException(status_code=409, detail="The AI model isn't running.")
    model = _reader_model(reader)
    if not model:
        raise HTTPException(
            status_code=409,
            detail="No installed model reports it can see images, install or "
            "pick one in Settings → Models.",
        )
    count = pdfpages.page_count(path)
    if count <= 0:
        return OcrPageReadOut(page=index, message="That PDF could not be opened.")
    index = max(0, min(index, count - 1))
    png = pdfpages.render_page(path, index)
    if not png:
        return OcrPageReadOut(page=index, message=f"Page {index + 1} could not be rendered.")
    with tempfile.TemporaryDirectory(prefix="mm-pageocr-") as scratch:
        page_path = Path(scratch) / f"page-{index}.png"
        page_path.write_bytes(png)
        text = vision_ocr.vision_ocr_text(page_path, model, deps.get_ollama()) or ""
    return OcrPageReadOut(
        page=index,
        text=text.strip(),
        model=model if text.strip() else "",
        message="" if text.strip() else f"{model} found no text on page {index + 1}.",
    )


#: **The two readers, and why both exist.**
#:
#: This project was told, twice, in opposite directions. First: *"I basically
#: dont want to download tesseract and only want to use an ai vision learning
#: and ocr model for images and scanned documents"*, which is why every read
#: path here defaults to a vision model and why `core/pdfpages.py` exists at
#: all. Then, later and just as directly: *"make sure tesseract exists as an
#: alternative as well."*
#:
#: Both are satisfiable because they are not the same claim. The vision model
#: is the *default*; Tesseract is an *alternative you can pick*, and it is a
#: genuinely better answer for some work: it needs no model running, it reads a
#: page in about a tenth of a second rather than several seconds, it never
#: invents words that were not on the page (the failure `VisionOcrBody.text`
#: exists to let you correct), and it returns *where* each block sits, which a
#: vision model cannot. It is also the only reader that works with no GPU and
#: no model installed at all.
#:
#: Neither is silently substituted for the other: the reader that produced a
#: reading is named in the response, and a request for one that is not
#: installed says so rather than quietly answering with the other.
#: **Three, not two, because "the AI" was hiding two different models.**
#: Reported: *"in the ocr workspace, my ocr model shows as a vision model and
#: my actual vision model doesnt appear as an option at all."* Exactly right.
#: `resolve_ocr_model` prefers a dedicated document reader (GLM-OCR,
#: DeepSeek-OCR, PaddleOCR-VL) and falls back to a general vision model;
#: `resolve_vision_model` answers "can anything here see an image". On a
#: machine with both installed they return different models, and the
#: workspace offered one option, labelled "AI vision model", which named
#: whichever of the two the picker happened to resolve. The other model was
#: unreachable from the UI entirely.
#:
#: Worse, the two halves disagreed: `ocr_readers` was fixed to call
#: `resolve_ocr_model` and `_vision_read_page` was left calling
#: `resolve_vision_model`, so the picker could name one model and the read use
#: the other. That is the same "fixed at one of two call sites" shape this
#: repo keeps hitting, and it is why the report came back after the first fix.
#:
#: So each resolver gets its own reader name and its own option, and the read
#: uses the resolver its name promises. `"vision"` keeps meaning "the app's
#: default choice" for every existing caller and stored preference, it maps
#: to `resolve_ocr_model`, which is what a read has always actually done.
READERS = ("vision", "ocr", "tesseract")


def _checked_reader(reader: str) -> str:
    """400 on an unknown reader rather than silently using the default.

    A typo'd `?reader=tesserract` that quietly ran the vision model would
    charge a reader seconds of GPU time for a request they meant to be
    instant, and tell them Tesseract had done it.
    """
    name = (reader or "vision").strip().lower()
    if name not in READERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reader {reader!r}: expected one of {', '.join(READERS)}.",
        )
    return name


def _page_read_key(attachment_id: int | None, upload_id: int | None) -> tuple[str, int] | None:
    """Which id space this read belongs to. See `PageRead` on why both."""
    if attachment_id is not None:
        return ("attachment", int(attachment_id))
    if upload_id is not None:
        return ("upload", int(upload_id))
    return None


def _remember_page_read(key: tuple[str, int] | None, result: OcrPageReadOut, reader: str) -> None:
    """Store one page's reading, replacing any earlier one for the same page.

    Silent on failure and never raises: a reading that reached the caller is a
    success, and losing the *cache* of it must not turn that into an error the
    reader sees. Empty readings are not stored, "the model found nothing on
    page 4" is not a transcription, and storing it would stop a later, better
    reader from being asked.
    """
    if not key or not (result.text or "").strip():
        return
    kind, source_id = key
    try:
        with deps.get_db().session() as session:
            row = (
                session.query(PageRead)
                .filter(
                    PageRead.kind == kind,
                    PageRead.source_id == source_id,
                    PageRead.page == int(result.page),
                )
                .one_or_none()
            )
            if row is None:
                row = PageRead(kind=kind, source_id=source_id, page=int(result.page))
                session.add(row)
            row.reader = reader
            row.model = result.model or ""
            row.text = result.text
            row.created_at = datetime.now(timezone.utc)
            #: Explicit: `DatabaseManager.session()` hands back a bare Session,
            #: and `with` on one closes it without committing, the whole point
            #: of this table is that the reading outlives the request.
            session.commit()
    except Exception:  # noqa: BLE001 - a cache write must never fail a read
        logger.debug("could not store the page reading", exc_info=True)


def _remember_page_caption(key: tuple[str, int] | None, page: int, caption: str, model: str) -> None:
    """Store one page's description, beside that page's reading.

    A near-twin of `_remember_page_read` above, and separate from it on
    purpose: a page can be described without being transcribed and transcribed
    without being described, so neither may touch the other's columns. Folding
    them into one function with optional arguments is how a describe call ends
    up quietly clearing a reading that took a minute of GPU time to produce.

    Silent on failure and never raises, same contract: a description that
    reached the caller is a success, and losing the *cache* of it must not turn
    that into an error the reader sees.
    """
    if not key or not (caption or "").strip():
        return
    kind, source_id = key
    try:
        with deps.get_db().session() as session:
            row = (
                session.query(PageRead)
                .filter(
                    PageRead.kind == kind,
                    PageRead.source_id == source_id,
                    PageRead.page == int(page),
                )
                .one_or_none()
            )
            if row is None:
                #: A page described but never read is a real state, the whole
                #: point of this being its own column, so the row is created
                #: here rather than requiring a reading to exist first.
                row = PageRead(kind=kind, source_id=source_id, page=int(page))
                session.add(row)
            row.caption = caption.strip()
            row.caption_model = model or ""
            session.commit()
    except Exception:  # noqa: BLE001 - a cache write must never fail a describe
        logger.debug("could not store the page description", exc_info=True)


def _page_read_text_map(kind: str, ids: list[int]) -> dict[int, str]:
    """The joined per-page reading for each of `ids`, page order, one query.

    **Why a list endpoint needs this at all.** Reported: "the extracted ocr for
    files doesnt actually appear in the file rows in the files library subtab".
    A whole-file reading is stored on the row itself (`vision_ocr_text`); a PDF
    read *page by page* in the OCR workspace is stored as `PageRead` rows
    instead, and nothing joined the two, so a document with every page read
    still said "No text yet" everywhere outside the workspace, including to
    anyone scanning the library for it.

    One grouped query rather than one per row: these endpoints render whole
    galleries, and the same lookup done per row is the N+1 that makes a library
    of a hundred files feel broken.
    """
    #: `kind` is the same vocabulary `_page_read_key` writes: "attachment" for
    #: a file hanging off a note, "upload" for one in the media gallery. Using
    #: the route prefixes ("file"/"media") here instead would match no rows at
    #: all and fail silently, which is the shape this join exists to fix.
    if not ids:
        return {}
    try:
        with deps.get_db().session() as session:
            rows = (
                session.query(PageRead)
                .filter(PageRead.kind == kind, PageRead.source_id.in_(ids))
                .order_by(PageRead.source_id.asc(), PageRead.page.asc())
                .all()
            )
    except Exception:  # noqa: BLE001 - an unreadable cache is an empty one
        logger.debug("could not load stored page readings for a list", exc_info=True)
        return {}
    out: dict[int, list[str]] = {}
    for row in rows:
        text = (row.text or "").strip()
        if text:
            out.setdefault(row.source_id, []).append(text)
    return {source_id: "\n\n".join(parts) for source_id, parts in out.items()}


def _page_read_count_map(kind: str, ids: list[int]) -> dict[int, int]:
    """How many pages of each file have a stored reading, one query.

    **Why the count and not just the text.** UI_MODERNISATION_PLAN Phase 7.5:
    "OCR text for a long document does not fit where a photo's caption fits.
    The Files row shows a one-line summary (first sentence / N pages read / N
    words)". The joined text is already carried (`_page_read_text_map`), but
    counting pages out of it means splitting a string on a separator and
    hoping: a reading that happens to contain a blank line would be counted
    as two pages.

    A count of rows rather than of distinct pages, because `(kind, source_id,
    page)` is unique on this table: re-reading a page replaces its row, so
    there is exactly one row per page that has ever been read.
    """
    if not ids:
        return {}
    try:
        with deps.get_db().session() as session:
            rows = (
                session.query(PageRead.source_id, PageRead.text)
                .filter(PageRead.kind == kind, PageRead.source_id.in_(ids))
                .all()
            )
    except Exception:  # noqa: BLE001 - an unreadable cache is an empty one
        logger.debug("could not count stored page readings for a list", exc_info=True)
        return {}
    counts: dict[int, int] = {}
    for source_id, text in rows:
        #: Only pages with a *reading*. A page that has only been described
        #: (Phase 7.3) has a row here too, and counting it would tell the row
        #: that a transcription exists where none does.
        if (text or "").strip():
            counts[source_id] = counts.get(source_id, 0) + 1
    return counts


def _stored_page_reads(key: tuple[str, int] | None) -> list[OcrPageReadOut]:
    """Every page of this document that has already been read, oldest page first."""
    if not key:
        return []
    kind, source_id = key
    try:
        with deps.get_db().session() as session:
            rows = (
                session.query(PageRead)
                .filter(PageRead.kind == kind, PageRead.source_id == source_id)
                .order_by(PageRead.page.asc())
                .all()
            )
            return [
                OcrPageReadOut(
                    page=row.page,
                    text=row.text or "",
                    model=row.model or "",
                    caption=row.caption or "",
                    caption_model=row.caption_model or "",
                )
                for row in rows
            ]
    except Exception:  # noqa: BLE001 - an unreadable cache is an empty one
        logger.debug("could not load stored page readings", exc_info=True)
        return []


def _read_page(
    path: Path,
    index: int,
    reader: str,
    key: tuple[str, int] | None = None,
) -> OcrPageReadOut:
    """One page, by whichever reader was asked for.

    Registered in `vision_ocr`'s running-reads list for the length of the call,
    which is what puts it in Settings → Background tasks. Asked for directly:
    "make sure eveyrhting appears in the bg processes in settings." A read is a
    model round-trip of several seconds and it appeared there nowhere, so
    closing the workspace mid-read left no sign anywhere that the app was still
    working.

    Here rather than in either reader, and here rather than in the two
    endpoints: `_read_range` loops over this function, so a range read shows up
    as its pages complete, which is also the only progress a range read has to
    report.
    """
    token = vision_ocr.register_page_read(
        f"Reading page {index + 1} of {path.name}",
        model="Tesseract" if reader == "tesseract" else "",
    )
    try:
        result = (
            _tesseract_read_page(path, index)
            if reader == "tesseract"
            else _vision_read_page(path, index, reader)
        )
        #: Stored as each page completes, not once the whole range is done:
        #: the point is that a read which finishes after the workspace has been
        #: closed is not lost, and a range read that is interrupted half way
        #: should keep the half it managed. See `PageRead`.
        _remember_page_read(key, result, reader)
        return result
    finally:
        vision_ocr.finish_page_read(token)


def _describe_page(
    path: Path,
    index: int,
    key: tuple[str, int] | None = None,
) -> OcrPageReadOut:
    """Describe one page's figures with a vision model, and store the answer.

    Deliberately the same envelope (`OcrPageReadOut`) as a page *read*: the two
    are the two halves of "what is on page 4", the workspace renders them in
    one panel, and a second response shape would be a second renderer that can
    drift from it: the mistake `_stored_range`'s own docstring records.

    `resolve_vision_model`, not `resolve_ocr_model`: describing a figure is the
    general "can anything here see an image" job, and a dedicated document
    reader (GLM-OCR and friends) is tuned to transcribe, not to explain. That
    is also the distinction the reader picker draws between its two AI options
    - see `READERS` above.
    """
    if not pdfpages.available():
        return OcrPageReadOut(
            page=index,
            message=(
                "Describing a PDF page needs the small PDF rasteriser: install "
                "the “PDF pages” extra in Settings → Optional extras."
            ),
        )
    if not deps.get_ollama().is_running():
        raise HTTPException(status_code=409, detail="The AI model isn't running.")
    model = deps.get_model_manager().resolve_vision_model(deps.get_ollama()) or ""
    if not model:
        raise HTTPException(
            status_code=409,
            detail="No installed model reports it can see images, install or "
            "pick one in Settings → Models.",
        )
    count = pdfpages.page_count(path)
    if count <= 0:
        return OcrPageReadOut(page=index, message="That PDF could not be opened.")
    index = max(0, min(index, count - 1))
    png = pdfpages.render_page(path, index)
    if not png:
        return OcrPageReadOut(page=index, message=f"Page {index + 1} could not be rendered.")
    #: Registered in the same running-reads list a page read uses, so a
    #: describe shows up in Settings → Background tasks like everything else, 
    #: "make sure eveyrhting appears in the bg processes in settings."
    token = vision_ocr.register_page_read(f"Describing page {index + 1} of {path.name}", model=model)
    try:
        with tempfile.TemporaryDirectory(prefix="mm-pagecap-") as scratch:
            page_path = Path(scratch) / f"page-{index}.png"
            page_path.write_bytes(png)
            caption = captioning.page_caption_text(
                page_path, index, count, model, deps.get_ollama()
            )
    finally:
        vision_ocr.finish_page_read(token)
    caption = (caption or "").strip()
    _remember_page_caption(key, index, caption, model)
    return OcrPageReadOut(
        page=index,
        caption=caption,
        caption_model=model if caption else "",
        message="" if caption else f"{model} had nothing to say about page {index + 1}.",
    )


def _tesseract_read_page(path: Path, index: int) -> OcrPageReadOut:
    """Rasterise one PDF page and read it with Tesseract.

    Same shape as `_vision_read_page` on purpose: the caller should not have
    to know which reader it asked for to understand the answer. `model` carries
    the reader's name for the same reason the vision path puts the model's name
    there: the workspace prints *who read this*, and "a vision model" and
    "Tesseract" are different enough claims that the difference must survive
    the round trip.
    """
    if not pdfpages.available():
        return OcrPageReadOut(
            page=index,
            message=(
                "Reading a PDF page needs the small PDF rasteriser: install "
                "the “PDF pages” extra in Settings → Optional extras."
            ),
        )
    if not ocr.tesseract_available():
        raise HTTPException(
            status_code=409,
            detail="Tesseract isn't installed. Install the “OCR” extra in "
            "Settings → Optional extras, or read this page with the AI instead.",
        )
    count = pdfpages.page_count(path)
    if count <= 0:
        return OcrPageReadOut(page=index, message="That PDF could not be opened.")
    index = max(0, min(index, count - 1))
    png = pdfpages.render_page(path, index)
    if not png:
        return OcrPageReadOut(page=index, message=f"Page {index + 1} could not be rendered.")
    with tempfile.TemporaryDirectory(prefix="mm-pagetess-") as scratch:
        page_path = Path(scratch) / f"page-{index}.png"
        page_path.write_bytes(png)
        text = (ocr.extract_text(page_path) or "").strip()
    return OcrPageReadOut(
        page=index,
        text=text,
        model="tesseract" if text else "",
        message="" if text else f"Tesseract found no text on page {index + 1}.",
    )


class OcrReadersOut(BaseModel):
    """Which readers this machine can actually use, right now.

    The workspace asks before it offers: a picker whose second entry always
    fails is worse than no picker, and "install Tesseract" is a real, one-click
    answer this app already knows how to give (`core/extras.py`).
    """

    #: The reader used when nothing is chosen.
    default: str = "vision"
    tesseract: bool = False
    vision: bool = False
    #: The model that would answer for the *default* reader, so the picker can
    #: name it rather than saying "a vision model" and leaving you to go and
    #: look. This is `resolve_ocr_model`: a dedicated document reader if one is
    #: installed, else the general vision model.
    vision_model: str = ""
    #: Why the default reader is unavailable, when it is, "the model isn't
    #: running" and "nothing installed can see images" need different fixes.
    vision_reason: str = ""
    #: The *other* model: what `resolve_vision_model` returns. Offered as its
    #: own reader whenever it differs from `vision_model`, because a machine
    #: with both GLM-OCR and Qwen-VL installed has two genuinely different
    #: readers and the workspace used to expose only one of them under a label
    #: that named the other. Empty when there is no second choice to make.
    ocr: bool = False
    ocr_model: str = ""
    ocr_reason: str = ''


@router.get("/ocr-readers", response_model=OcrReadersOut)
def ocr_readers() -> OcrReadersOut:
    """What can read a page here, asked by the workspace's reader picker.

    Reported directly: "I can only select the vision models not OCR
    models." This called `resolve_vision_model`, the same, name-agnostic
    "can anything here see an image" resolver `/models/vision-model` uses: 
    so the picker always described whatever generic vision model
    auto-detect happened to find first, never the dedicated document
    reader (GLM-OCR/DeepSeek-OCR/PaddleOCR-VL) an explicit `ocr_model`
    preference names, even though the actual read (`routes_files.py`'s own
    page-read endpoint) already calls `resolve_ocr_model` and gets it
    right. The picker's own idea of "which model" just never matched what
    a read would actually use."""
    ollama = deps.get_ollama()
    running = ollama.is_running()
    model = _reader_model("vision") if running else ""
    other = _reader_model("ocr") if running else ""
    if not running:
        reason = "The AI model isn't running."
    elif not model:
        reason = "No installed model reports it can see images."
    else:
        reason = ""
    #: Only when it is a genuinely *different* model. On the common machine
    #: with one vision model both resolvers return it, and offering the same
    #: model twice under two names is a worse picker than offering it once.
    second = other if (other and other != model) else ""
    return OcrReadersOut(
        tesseract=ocr.tesseract_available(),
        vision=bool(model),
        vision_model=model or "",
        vision_reason=reason,
        ocr=bool(second),
        ocr_model=second,
        ocr_reason="" if second else reason,
    )


class OcrRangeReadOut(BaseModel):
    """Several pages of a document, read by one of the readers above."""

    pages: list[OcrPageReadOut] = []
    #: How many pages the spec asked for *after* clamping to the document, so
    #: the UI can say "read 8 of the 20 you asked for" rather than silently
    #: returning fewer.
    requested: int = 0
    read: int = 0
    page_count: int = 0
    message: str = ""


#: How many pages one range request may read. A vision pass is seconds per
#: page, so "all" on a 300-page scan is not a request anyone means to make
#: synchronously: the cap keeps a mis-click from occupying the model for an
#: hour, and the response says plainly how far it got so the reader can ask
#: for the next block rather than wondering.
MAX_RANGE_PAGES = 25


def _parse_page_spec(spec: str, count: int) -> list[int]:
    """`"all"`, `"3"`, `"1-5"`, `"1,4,7-9"` -> sorted 0-based page indices.

    **One-based on the way in, because that is what the page rail shows and
    what a person means by "page 1".** Anything unparseable is skipped rather
    than raising: a range typed with a stray character should read the pages
    it could understand, not refuse the lot.
    """
    text = (spec or "").strip().lower()
    if not text or text in {"all", "*"}:
        return list(range(count))
    wanted: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part[1:]:  # not a leading minus
            start_text, _, end_text = part.partition("-")
            if not (start_text.isdigit() and end_text.isdigit()):
                continue
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            wanted.update(range(start - 1, end))
        elif part.isdigit():
            wanted.add(int(part) - 1)
    return sorted(i for i in wanted if 0 <= i < count)


#: Tesseract reads a rendered page in about a tenth of a second, so the cap
#: that keeps a mis-click from occupying a *model* for an hour has no reason to
#: apply to it. Still bounded: a 2,000-page scan is not a synchronous request
#: either: just bounded by what is actually slow.
MAX_TESSERACT_RANGE_PAGES = 200


def _read_range(
    path: Path,
    spec: str,
    reader: str = "vision",
    key: tuple[str, int] | None = None,
) -> OcrRangeReadOut:
    """Read every page the spec names, reusing the single-page reader.

    Deliberately a loop over `_read_page` rather than a second implementation:
    one place decides what "no rasteriser", "no vision model" and "nothing
    legible" mean, and a range read cannot drift away from what the per-page
    button does.
    """
    if not pdfpages.available():
        return OcrRangeReadOut(
            message=(
                "Reading a PDF needs the small PDF rasteriser: install the "
                "“PDF pages” extra in Settings → Optional extras."
            )
        )
    count = pdfpages.page_count(path)
    if count <= 0:
        return OcrRangeReadOut(message="That PDF could not be opened.")
    indices = _parse_page_spec(spec, count)
    if not indices:
        return OcrRangeReadOut(
            page_count=count,
            message=f"No pages matched that range. This document has {count} page(s).",
        )
    requested = len(indices)
    limit = MAX_TESSERACT_RANGE_PAGES if reader == "tesseract" else MAX_RANGE_PAGES
    capped = indices[:limit]
    pages = [_read_page(path, index, reader, key) for index in capped]
    read = sum(1 for page in pages if page.text)
    note = ""
    if requested > len(capped):
        last = capped[-1] + 1
        note = (
            f" Stopped after {len(capped)} pages (the limit for one go), "
            f"ask for {last + 1}-{min(last + limit, count)} to carry on."
        )
    return OcrRangeReadOut(
        pages=pages,
        requested=requested,
        read=read,
        page_count=count,
        message=(f"Read {read} of {len(capped)} page(s)." + note).strip(),
    )


def _stored_range(key: tuple[str, int] | None) -> OcrRangeReadOut:
    """What is already known about a document, in the shape a range read returns.

    The same shape on purpose: the workspace has one renderer for "here are
    some pages of text", and giving stored readings a different envelope would
    mean a second one that could drift from it.
    """
    pages = _stored_page_reads(key)
    if not pages:
        return OcrRangeReadOut()
    #: Counted on `text`, not on the number of rows: a page that has only been
    #: *described* (Phase 7.3: `PageRead.caption` with no reading beside it)
    #: has a row here too, and calling it "read" would tell the workspace, the
    #: Files row's badge and the lightbox's page chips that a transcription
    #: exists where none does.
    read = sum(1 for page in pages if (page.text or "").strip())
    return OcrRangeReadOut(
        pages=pages,
        requested=len(pages),
        read=read,
        message=(f"{read} page(s) already read." if read != 1 else "1 page already read."),
    )


@router.post("/files/{attachment_id}/ocr-range-read", response_model=OcrRangeReadOut)
def attachment_ocr_range_read(
    attachment_id: int,
    pages: str = "all",
    reader: str = "vision",
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Read a whole PDF, or the pages named by `pages` (e.g. `1-5`, `2,7`)."""
    reader = _checked_reader(reader)
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDFs are read by page range.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    return _read_range(path, pages, reader, _page_read_key(attachment_id, None))


@router.post("/media/{upload_id}/ocr-range-read", response_model=OcrRangeReadOut)
def media_ocr_range_read(
    upload_id: int,
    pages: str = "all",
    reader: str = "vision",
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Read a whole PDF, or the pages named by `pages` (e.g. `1-5`, `2,7`)."""
    reader = _checked_reader(reader)
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    if Path(upload.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDFs are read by page range.")
    path = _within_dir(deps.get_config().data_dir / "media", upload.filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    return _read_range(path, pages, reader, _page_read_key(None, upload_id))


@router.post("/files/{attachment_id}/ocr-page-read", response_model=OcrPageReadOut)
def attachment_ocr_page_read(
    attachment_id: int,
    page: int = 0,
    reader: str = "vision",
    session: Session = Depends(get_session),
) -> OcrPageReadOut:
    reader = _checked_reader(reader)
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF pages are read one at a time.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    return _read_page(path, page, reader, _page_read_key(attachment_id, None))


@router.post("/media/{upload_id}/ocr-page-read", response_model=OcrPageReadOut)
def media_ocr_page_read(
    upload_id: int,
    page: int = 0,
    reader: str = "vision",
    session: Session = Depends(get_session),
) -> OcrPageReadOut:
    reader = _checked_reader(reader)
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    if Path(upload.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF pages are read one at a time.")
    path = _within_dir(deps.get_config().data_dir / "media", upload.filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    return _read_page(path, page, reader, _page_read_key(None, upload_id))


class OcrRegionReadOut(BaseModel):
    """One rectangle a person drew on a page, read or described.

    Deliberately *not* `OcrPageReadOut`: nothing here is stored, and a shape
    that carries `page` and looks like a stored page reading would be an
    invitation to file it as one. Asked as a question and it is a good one:
    *"can there be a way for the user to manually outline and single out
    regions on a pdf or similar document and then the ai will read what is in
    those regions?? like maybe the user can outline a graph or diagram on a pdf
    slide and then the user cna get the image or ocr model to analyse and
    caption that thing."*
    """

    #: Which page the rectangle was drawn on, echoed back so the answer can be
    #: labelled with it: a result that does not say where it came from is the
    #: thing the region overlay exists to avoid.
    page: int = 0
    #: "read" or "describe", echoed for the same reason.
    mode: str = "read"
    text: str = ""
    model: str = ""
    message: str = ""


#: A drawn rectangle is a crop of a page render, not an upload: at the viewer's
#: own 2x scale a full page is a few hundred KB and a region is far less. The
#: cap is generous enough never to refuse a real crop and small enough that a
#: mistyped request cannot stream 50 MB into memory before anything looks at it.
MAX_REGION_BYTES = 8 * 1024 * 1024


def _region_image(crop: UploadFile) -> bytes:
    """The uploaded crop's bytes, refused if it is not a PNG or too large.

    **Read into memory rather than streamed to disk**, unlike `/media/upload`:
    nothing here is stored, the model is handed a data URI built from these
    bytes, and writing a scratch file the request then has to clean up is more
    moving parts for no gain. The size cap is what makes that safe.

    The magic-number check is not decoration either: this is the one endpoint
    in the app that takes an image nobody in the notebook uploaded, and
    `canvas.toBlob` produces a PNG, so anything else here is a caller doing
    something other than what this route is for.
    """
    data = crop.file.read(MAX_REGION_BYTES + 1)
    if len(data) > MAX_REGION_BYTES:
        raise HTTPException(status_code=413, detail="That region is too large to read.")
    if not data:
        raise HTTPException(status_code=400, detail="That region came through empty.")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="A region has to be sent as a PNG.")
    return data


def _read_region(crop: UploadFile, page: int, mode: str, reader: str) -> OcrRegionReadOut:
    """Read or describe one drawn rectangle. Never stores anything.

    **Why the crop is uploaded rather than described by four numbers.** The
    obvious alternative is to send the rectangle and let this render and crop
    the page itself: but the workspace already has the page raster on screen,
    the person drew the rectangle *on that raster*, and cropping it in the
    browser guarantees the model is handed exactly what they outlined. It also
    means the same gesture works on a plain image, which has no page to
    re-render at all.

    **Why nothing is stored.** `PageRead` is keyed by page, and a region is a
    part of a page, several of them, usually, each answering a different
    question. Filing one over the page's reading would destroy a transcription
    to save a note about one chart in the corner of it.
    """
    mode = (mode or "read").strip().lower()
    if mode not in {"read", "describe"}:
        raise HTTPException(
            status_code=400, detail=f"Unknown mode {mode!r}: expected 'read' or 'describe'."
        )
    data = _region_image(crop)
    if mode == "read":
        reader = _checked_reader(reader)
    if mode == "read" and reader == "tesseract":
        if not ocr.tesseract_available():
            raise HTTPException(
                status_code=409,
                detail="Tesseract isn't installed. Install the “OCR” extra in "
                "Settings → Optional extras, or read this region with the AI instead.",
            )
    else:
        if not deps.get_ollama().is_running():
            raise HTTPException(status_code=409, detail="The AI model isn't running.")
    #: A read uses whichever reader the workspace's picker named; a describe is
    #: always the general vision model, for the same reason `_describe_page`
    #: is: a dedicated document reader is tuned to transcribe, not to explain.
    model = (
        "tesseract"
        if mode == "read" and reader == "tesseract"
        else _reader_model(reader)
        if mode == "read"
        else deps.get_model_manager().resolve_vision_model(deps.get_ollama()) or ""
    )
    if not model:
        raise HTTPException(
            status_code=409,
            detail="No installed model reports it can see images, install or "
            "pick one in Settings → Models.",
        )
    label = "Describing" if mode == "describe" else "Reading"
    token = vision_ocr.register_page_read(
        f"{label} a region of page {page + 1}",
        model="Tesseract" if model == "tesseract" else model,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="mm-region-") as scratch:
            crop_path = Path(scratch) / "region.png"
            crop_path.write_bytes(data)
            if mode == "describe":
                #: `count=1` and page 0: the prompt's "page N of M" would be a
                #: lie about a crop, and what is wanted here is a description of
                #: the *figure*, which is what the prompt asks for either way.
                text = captioning.page_caption_text(crop_path, 0, 1, model, deps.get_ollama())
            elif model == "tesseract":
                text = (ocr.extract_text(crop_path) or "").strip()
            else:
                text = (vision_ocr.vision_ocr_text(crop_path, model, deps.get_ollama()) or "").strip()
    finally:
        vision_ocr.finish_page_read(token)
    text = (text or "").strip()
    nothing = (
        f"{model} had nothing to say about that region."
        if mode == "describe"
        else "No text was found in that region."
    )
    return OcrRegionReadOut(
        page=page,
        mode=mode,
        text=text,
        model=model if text else "",
        message="" if text else nothing,
    )


@router.post("/files/{attachment_id}/region-read", response_model=OcrRegionReadOut)
def attachment_region_read(
    attachment_id: int,
    crop: UploadFile,
    page: int = Form(0),
    mode: str = Form("read"),
    reader: str = Form("vision"),
    session: Session = Depends(get_session),
) -> OcrRegionReadOut:
    """Read or describe a rectangle drawn on one page of an attached file.

    The attachment is looked up and not otherwise used, and that is the point:
    it is the authorisation check. Without it this would be "run a model on any
    image anyone posts", which is a different endpoint from the one that was
    asked for.
    """
    _existing_attachment(session, attachment_id)
    return _read_region(crop, page, mode, reader)


@router.post("/media/{upload_id}/region-read", response_model=OcrRegionReadOut)
def media_region_read(
    upload_id: int,
    crop: UploadFile,
    page: int = Form(0),
    mode: str = Form("read"),
    reader: str = Form("vision"),
    session: Session = Depends(get_session),
) -> OcrRegionReadOut:
    """`attachment_region_read`'s sibling for a `/media/` upload."""
    deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    return _read_region(crop, page, mode, reader)


@router.post("/files/{attachment_id}/page-caption", response_model=OcrPageReadOut)
def attachment_page_caption(
    attachment_id: int,
    page: int = 0,
    session: Session = Depends(get_session),
) -> OcrPageReadOut:
    """Describe the figures on one page of an attached PDF.

    The document half of captioning (UI_MODERNISATION_PLAN Phase 7.3). A file
    already has one whole-file caption; a slide deck needs one per page, since
    "a document with charts in it" describes every page in it equally badly.
    """
    attachment = _existing_attachment(session, attachment_id)
    if Path(attachment.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF pages are described one at a time.")
    path = _within_dir(deps.get_config().uploads_dir, attachment.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File is missing from disk")
    return _describe_page(path, page, _page_read_key(attachment_id, None))


@router.post("/media/{upload_id}/page-caption", response_model=OcrPageReadOut)
def media_page_caption(
    upload_id: int,
    page: int = 0,
    session: Session = Depends(get_session),
) -> OcrPageReadOut:
    """`attachment_page_caption`'s sibling for a `/media/` upload: two id
    spaces, two routes, one implementation underneath."""
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    if Path(upload.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF pages are described one at a time.")
    path = _within_dir(deps.get_config().data_dir / "media", upload.filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That file is no longer on disk.")
    return _describe_page(path, page, _page_read_key(None, upload_id))


@router.get("/files/{attachment_id}/page-reads", response_model=OcrRangeReadOut)
def attachment_page_reads(
    attachment_id: int,
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Every page of this attachment that has already been read.

    Asked by the OCR workspace as it opens a document, so a reading that
    finished while the workspace was closed is still there when you come back
    - which is the whole point of `PageRead`. See that model's docstring for
    the report.
    """
    _existing_attachment(session, attachment_id)
    return _stored_range(_page_read_key(attachment_id, None))


@router.get("/media/{upload_id}/page-reads", response_model=OcrRangeReadOut)
def media_page_reads(
    upload_id: int,
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Every page of this upload that has already been read."""
    deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    return _stored_range(_page_read_key(None, upload_id))


def _forget_page_read(key: tuple[str, int] | None, page: int) -> None:
    """Remove one page's stored reading, if there is one.

    **The half of "delete or redo" that redo already had.** Reported directly:
    *"there's also no way to delete or redo ocr text extractions in the ocr
    workspace."* Redo was already there, `PageRead`'s own docstring notes that
    re-reading a page replaces its row rather than appending, it was just
    never labelled as such. Delete genuinely was not: the only way to get rid
    of a wrong reading was to cover it with a better one, which still needs a
    working reader, and there was no way at all to simply take a note off the
    list of "already read" pages.

    Idempotent and quiet either way, matching `_remember_page_read`'s own
    stance that this table is a cache of a reading, not the reading itself, 
    deleting a row that is not there is not an error, it is the state the
    caller wanted.
    """
    if not key:
        return
    kind, source_id = key
    with deps.get_db().session() as session:
        row = (
            session.query(PageRead)
            .filter(
                PageRead.kind == kind,
                PageRead.source_id == source_id,
                PageRead.page == int(page),
            )
            .one_or_none()
        )
        if row is not None:
            session.delete(row)
            session.commit()


@router.delete("/files/{attachment_id}/page-reads/{page}", response_model=OcrRangeReadOut)
def delete_attachment_page_read(
    attachment_id: int,
    page: int,
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Forget one page's reading. Returns what is left, in the same envelope
    `GET .../page-reads` uses, so the workspace can repaint from the response
    rather than issuing a second request."""
    _existing_attachment(session, attachment_id)
    _forget_page_read(_page_read_key(attachment_id, None), page)
    return _stored_range(_page_read_key(attachment_id, None))


@router.delete("/media/{upload_id}/page-reads/{page}", response_model=OcrRangeReadOut)
def delete_media_page_read(
    upload_id: int,
    page: int,
    session: Session = Depends(get_session),
) -> OcrRangeReadOut:
    """Forget one page's reading."""
    deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    _forget_page_read(_page_read_key(None, upload_id), page)
    return _stored_range(_page_read_key(None, upload_id))


class VisionOcrBody(BaseModel):
    #: Same "already there and not forced, leave it alone" rule as
    #: `CaptionBody.force`, a manual re-read the user pressed the button
    #: for, not a background pass overwriting a reading they already saw.
    force: bool = False
    #: A correction typed by hand, exactly as `OcrBody.text` already allows for
    #: the Tesseract reading: `None` means "read it", any string sets it, and
    #: `""` clears it.
    #:
    #: Reported: a vision model asked to transcribe a picture with no text in
    #: it returned four Pokémon names, and there was no way to remove or edit
    #: them. That failure is inherent to asking a small VLM to read an image
    #: with nothing to read, the prompt already asks it to say so and it
    #: ignored the instruction: so the fix is not a better prompt, it is that
    #: a wrong reading must be correctable like every other AI output in this
    #: app. The Tesseract line has been editable since it shipped; this one
    #: was the odd one out.
    text: str | None = Field(default=None, max_length=10_000)


@router.post("/media/{upload_id}/vision-ocr", response_model=MediaUploadOut)
def vision_ocr_media(
    upload_id: int, body: VisionOcrBody = VisionOcrBody(), session: Session = Depends(get_session)
) -> MediaUploadOut:
    """Read the text in one image with a vision model, the "extractor
    mode" asked for directly, distinct from the local Tesseract pass
    (`ocr_text`, automatic on upload) and from the AI caption (`caption`, a
    description rather than a transcription). Manual only: never triggered
    by `POST /media/upload` itself, unlike captioning.

    Same synchronous, single-round-trip shape as `caption_media` above: 
    one model call, no different from the AI-edit or link-reason calls this
    app already blocks on behind a spinner.
    """
    upload = deps.get_or_404(session, MediaUpload, upload_id, "No upload with that id")
    if Path(upload.filename).suffix.lower() not in vision_ocr.VISION_OCR_SUFFIXES:
        raise HTTPException(status_code=415, detail="Only images can be read this way.")
    if body.text is not None:
        # A hand-typed correction, or "" to clear a wrong reading. Checked
        # before the backend is: fixing a bad transcription must not require
        # the model that produced it to still be running.
        upload.vision_ocr_text = body.text.strip() or None
        if not upload.vision_ocr_text:
            # Clearing the text clears the attribution with it, "Read by X"
            # under nothing is a claim about a reading that no longer exists.
            upload.vision_ocr_model = None
        session.commit()
        return MediaUploadOut(
            id=upload.id,
            url=f"/media/{upload.filename}",
            original_name=upload.original_name,
            ocr_text=upload.ocr_text or "",
            caption=upload.caption or "",
            caption_model=upload.caption_model or "",
            caption_edited=upload.caption_edited,
            vision_ocr_text=upload.vision_ocr_text or "",
            vision_ocr_model=upload.vision_ocr_model or "",
        )
    if not deps.get_ollama().is_running():
        raise HTTPException(status_code=409, detail="The AI model isn't running.")
    model = deps.get_model_manager().resolve_ocr_model(deps.get_ollama())
    if not model:
        raise HTTPException(
            status_code=409,
            detail="No installed model reports it can see images, install or "
            "pick one in Settings → Models.",
        )
    media_dir = deps.get_config().data_dir / "media"
    vision_ocr.vision_ocr_and_store(upload.id, media_dir / upload.filename, force=body.force)
    session.refresh(upload)
    return MediaUploadOut(
        id=upload.id,
        url=f"/media/{upload.filename}",
        original_name=upload.original_name,
        ocr_text=upload.ocr_text or "",
        caption=upload.caption or "",
        caption_model=upload.caption_model or "",
        caption_edited=upload.caption_edited,
        vision_ocr_text=upload.vision_ocr_text or "",
        vision_ocr_model=upload.vision_ocr_model or "",
    )


@media_router.get("/media/{filename}")
def get_media(filename: str) -> FileResponse:
    """Serve generic uploaded media.

    The suffix is checked again on the way out, not only on the way in. Upload
    is not the only route into this folder, a restored backup, a synced data
    directory, or a future writer could put something here, and this is the
    endpoint that decides what the browser executes.
    """
    name = safe_filename(filename)
    if Path(name).suffix.lower() not in MEDIA_SUFFIXES:
        raise HTTPException(status_code=404, detail="Media file not found")
    path = deps.get_config().data_dir / "media" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    # `nosniff` is already set globally, but the header below is the one that
    # decides whether a PDF opens in the page or downloads, and an inline PDF
    # viewer is a script host. Nothing here needs to render in-place: markdown
    # embeds images with <img>, which ignores Content-Disposition.
    return FileResponse(
        path, headers={"Content-Disposition": f'inline; filename="{name}"'}
    )
