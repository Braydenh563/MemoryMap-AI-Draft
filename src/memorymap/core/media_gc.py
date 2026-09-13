"""Reconciles `/media/` uploads against what still references them.

ROADMAP.md item 20a: `MediaUpload` (added for the Library gallery) tracks
every file `/media/upload` has ever produced, but nothing before this
checked a row against whether any live note, document, whiteboard image
object or saved chat turn still points at it, pasting over an image in a
note, or deleting the note entirely, leaves the file on disk with only a
manual, one-at-a-time `DELETE /media/{id}` to ever find it again.

The one thing this has to get right, and would rather be slow about than
wrong about: a private note's content is encrypted at rest, so an image
referenced only inside a private note that's currently locked cannot be
ruled out as "still referenced", it can only be *not checked*. Rather than
treat "couldn't check" as "not referenced" (which would eventually delete a
real attachment out from under a locked note), any private note this pass
can't read makes the whole pass refuse to delete anything, not just skip
that one note.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import Conversation, Document, Entry, MediaUpload, WhiteboardObject
from memorymap.entry import manager

# Same shape routes_whiteboard.py's own MEDIA_URL_RE validates on the way in, 
# kept independent (not imported) since this only ever reads, never resolves
# a path from user input.
_MEDIA_NAME_RE = re.compile(r"/media/([A-Za-z0-9][A-Za-z0-9._-]{0,119})")


def referenced_names(text: str) -> set[str]:
    """Every `/media/<filename>` this text mentions. Public (not
    module-private): `core/media_process.py` reuses it to answer the same
    underlying question, "which uploads does this text reference", when
    deciding what to run OCR/captioning/vision-OCR on at save time, not
    just when deciding what counts as orphaned."""
    return set(_MEDIA_NAME_RE.findall(text or ""))


def _referenced_filenames(session: Session) -> tuple[set[str], bool]:
    """Every filename this pass can actually see referenced, plus whether a
    locked private note forced it to skip a check.
    """
    from memorymap.core import crypto, vault

    referenced: set[str] = set()
    skipped_private = False

    for obj in session.scalars(select(WhiteboardObject).where(WhiteboardObject.kind == "image")):
        referenced.update(referenced_names(obj.data))

    for doc in session.scalars(select(Document)):
        referenced.update(referenced_names(doc.content))

    for entry in session.scalars(select(Entry).where(Entry.is_deleted == False)):  # noqa: E712
        if entry.is_private and crypto.is_encrypted(entry.content) and vault.key() is None:
            skipped_private = True
            continue
        referenced.update(referenced_names(manager.readable_content(entry)))

    return referenced, skipped_private


def _conversation_referenced_ids(session: Session) -> set[int]:
    """Every MediaUpload id a saved chat turn still attaches.

    A conversation stores its images as ids
    (`routes_conversations.TurnBody.image_media_ids`, on the user message),
    not as inline `/media/…` markdown text: so `_referenced_filenames`
    above, which only ever looks for that text, can never see a chat's own
    images no matter how thoroughly it scans notes, documents and
    whiteboard content. Without this, `find_orphaned_media` would call
    every image ever attached to a chat message "orphaned", sent or not,
    and `delete_orphaned_media` would delete its file out from under a
    conversation someone can still open and read.
    """
    ids: set[int] = set()
    for conversation in session.scalars(select(Conversation)):
        try:
            messages = json.loads(conversation.messages)
        except ValueError:
            continue
        for message in messages:
            for media_id in message.get("image_media_ids") or []:
                if isinstance(media_id, int):
                    ids.add(media_id)
    return ids


def usage_map(session: Session) -> tuple[dict[str, list[dict]], bool]:
    """The reverse of `_referenced_filenames`: filename -> where it is used.

    The Library's Files & Images tab showed a thumbnail, a filename and two
    empty prompts, and nothing about what the file was *for*, so a gallery of
    sixty uploads could not answer the only question anyone brings to it,
    which is "where did this come from and what is it attached to?". Reported
    as the Files tab needing to be "properly integrated" rather than
    redesigned.

    Built from `referenced_names` rather than a second scanner, so this and
    the orphan check can never disagree about what "referenced" means: an
    important property, because a file this says is used and the GC says is
    orphaned would be a file the GC deletes out from under a live note.

    Returns `(map, skipped_private)`. `skipped_private` carries the same
    meaning it does for the orphan pass: a locked private note could not be
    read, so the answer is incomplete rather than negative, and the UI says so
    instead of claiming a file is unused.
    """
    from memorymap.core import crypto, vault

    used: dict[str, list[dict]] = {}
    skipped_private = False

    def note(name: str, kind: str, ident, label: str) -> None:
        used.setdefault(name, []).append(
            {"kind": kind, "id": ident, "label": (label or "").strip()[:80] or "Untitled"}
        )

    for obj in session.scalars(select(WhiteboardObject).where(WhiteboardObject.kind == "image")):
        for name in referenced_names(obj.data):
            note(name, "board", obj.board_id, "Whiteboard")

    for doc in session.scalars(select(Document)):
        for name in referenced_names(doc.content):
            note(name, "document", doc.id, doc.title)

    for entry in session.scalars(select(Entry).where(Entry.is_deleted == False)):  # noqa: E712
        if entry.is_private and crypto.is_encrypted(entry.content) and vault.key() is None:
            skipped_private = True
            continue
        content = manager.readable_content(entry)
        for name in referenced_names(content):
            # **A private note contributes the link but never its words.**
            # The label is rendered in the Library's file gallery, and the
            # first line of a private note is exactly the kind of thing that
            # must not appear on a wall of thumbnails anyone glancing at the
            # screen can read. The app already has this convention: a
            # document's linked-notes list (`routes_documents._linked_notes`)
            # sends `is_private` and the UI draws a lock instead of the
            # preview. Same answer here: the connection is still shown and
            # still clickable, because knowing *that* a file is in use is what
            # stops it being deleted; only the wording is withheld.
            if entry.is_private:
                note(name, "note", entry.id, "Private note")
                continue
            # `plain_label`, not the raw first line: a chip cannot render
            # markdown, and one that tries shows `# Title ![alt](/media/…)`
            # verbatim: reported exactly that way.
            note(name, "note", entry.id, manager.plain_label(content))

    return used, skipped_private


def find_orphaned_media(session: Session) -> tuple[list[MediaUpload], bool]:
    """Uploads no live note, document, whiteboard object or saved chat turn
    still points at.

    Returns `(orphans, skipped_private)`. When `skipped_private` is True,
    at least one private note's content could not be checked (vault
    locked): the list is not exhaustive, and `delete_orphaned_media`
    refuses to act on it.
    """
    referenced, skipped_private = _referenced_filenames(session)
    referenced_ids = _conversation_referenced_ids(session)
    uploads = session.scalars(select(MediaUpload)).all()
    orphans = [
        u for u in uploads if u.filename not in referenced and u.id not in referenced_ids
    ]
    return orphans, skipped_private


def delete_orphaned_media(session: Session, media_dir) -> tuple[list[dict], bool]:
    """Deletes every currently-orphaned upload's file and tracking row.

    Returns `(deleted, skipped_private)`, `deleted` holds one
    `{"id", "filename", "original_name"}` dict per row removed, captured
    *before* the delete (a row's fields aren't safely readable through the
    ORM object once `session.commit()` has expired it). Refuses outright
    (deletes nothing) when a locked private note made the reference check
    incomplete: leaving a genuinely orphaned file on disk a while longer
    is the safe side of that trade; deleting one a locked note still
    references is not.
    """
    orphans, skipped_private = find_orphaned_media(session)
    if skipped_private:
        return [], True

    media_dir = media_dir.resolve()
    deleted = [
        {"id": u.id, "filename": u.filename, "original_name": u.original_name}
        for u in orphans
    ]
    for upload in orphans:
        candidate = (media_dir / upload.filename).resolve()
        if candidate.is_relative_to(media_dir):
            candidate.unlink(missing_ok=True)
        session.delete(upload)
    session.commit()
    return deleted, False
