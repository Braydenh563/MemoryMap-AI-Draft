"""Everything you made before, in one list (§4, §36F).

The Library is the app's *finding* surface, and the decision behind it is worth
stating because it is what makes it worth building at all: **it replaces two
surfaces rather than sitting beside them.** A "library" that duplicated the
Documents tab and the conversation sidebar would be a third place to look for
things that already had two, which is worse than no library. So the Documents
tab's list moves here, the chat sidebar's list moves here, and the tab bar gets
no longer: it was already at the width where another tab hurts (measured: it
wraps to a second row below about 1350px).

The list is assembled **here** rather than in `app.js` out of four fetches, for
the reason `routes_tasks.py` gives for background jobs: a surface that stitches
its own list from whatever endpoints happen to exist is a surface that silently
misses the next thing anybody adds. One shape, one place to add a kind to.

What it does *not* do is filter or sort. Those are the Library's first-class
controls and they have to feel instant as you type, which means the client owns
them and the server hands over the whole (bounded) list once.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core.database import (
    Attachment,
    AuditLog,
    Category,
    Conversation,
    Document,
    Entry,
)
from memorymap.core import events
from memorymap.core.deps import get_session
from memorymap.entry.manager import extract_title, remove_title, strip_inline_markdown

router = APIRouter(tags=["library"])

#: Per kind, not overall. A notebook with 300 documents and 4 chats should not
#: hand back 300 documents and no chats, every kind gets its own allowance, so
#: the filter chips are never empty for a reason nobody can see.
PER_KIND_LIMIT = 200

#: Enough of a thing to recognise it, not enough to render a card that scrolls.
PREVIEW_CHARS = 160

#: A note's own words *are* the note, there is no title to fall back on and no
#: filename to recognise it by, so 160 characters was cutting most cards off
#: mid-sentence. Reported: "I can't see a lot of the response in the cards."
NOTE_PREVIEW_CHARS = 420

#: A log line's detail is the whole of what it says. Clipping it to a preview
#: length made "majority of the logs cut off in half", which is a log that has
#: stopped being a record.
ACTIVITY_DETAIL_CHARS = 400


#: Heading/blockquote markers, stripped before the whitespace collapse below
#: erases the line starts they depend on. The frontend card renderer does
#: this same strip (app.js's `libraryCard`) for markers still at a real line
#: start, but a document's *second* heading: "## Introduction" partway
#: through the file: only reads that way before `" ".join(text.split())`
#: below turns every newline into a space; after that it is indistinguishable
#: from a mid-sentence "##". Reported directly: a document's preview showed
#: the raw `##`.
_MD_BLOCK_MARKER = re.compile(r"^(?:#{1,6}\s+|>\s?)", re.MULTILINE)


def _clip(text: str, limit: int = PREVIEW_CHARS) -> str:
    text = _MD_BLOCK_MARKER.sub("", text or "")
    # An image-only note (a sketch, most often, but any note that's just a
    # pasted image works the same way) read as literal `![sketch](/media/
    # ...)` here: the graph's node labels had the identical bug and this is
    # the same fix, factored out so a third copy of it never has to happen.
    text = strip_inline_markdown(text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: A pasted or dropped image lives as inline markdown in a note's own
#: content (`![alt](url)`), never as an Attachment, only a sketch's drawing
#: is stored that way. `thumb_by_entry` below only ever looks at Attachment
#: rows, so a note like that got no thumbnail at all: a sketch's card showed
#: its drawing and a pasted-image note's card showed nothing, which is the
#: exact inconsistency reported ("make sketches render the same as images").
#: Bounded, linear-scan character classes, no nested quantifiers, same
#: ReDoS-avoidance shape as every other content-scanning regex in this app.
_INLINE_IMAGE_URL = re.compile(r"!\[[^\]\n]{0,200}\]\(([^)\n\s]{1,500})\)")


def _first_inline_image_url(content: str) -> str | None:
    """The first image a note's *text* points at, if any, same URL shapes
    the note editor itself already renders inline (`isRenderableUrl` in
    app.js: same-origin absolute paths or a plain `https://` link), so a
    thumbnail never appears here for something the note itself wouldn't
    have shown as a picture.
    """
    match = _INLINE_IMAGE_URL.search(content or "")
    if not match:
        return None
    url = match.group(1)
    if url.startswith("/") and not url.startswith("//"):
        return url
    if url.lower().startswith(("http://", "https://")):
        return url
    return None


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


#: The two board types, mirrored from `routes_whiteboard.BOARD_TYPES` rather
#: than imported, because importing that module here would pull the whole
#: whiteboard router into the Library's import graph for the sake of one set
#: of two strings. `tests/test_library_boards.py` fails if they drift.
_BOARD_TYPES = {"board", "map"}


def _entry_kind(entry: Entry) -> str:
    """"note", "board" or "map", for one row of the entries table.

    Reported on 2026-09-09: "in the all library subtab, the mindmap I made
    called bubble tea shows as a note", while Boards and maps drew the same
    thing correctly as a map with 3 nodes. Not a slip in one view: the
    storage model shows through. MINDMAP_PLAN §4 chose option B, so a board
    *is* an `Entry` carrying `is_board`, and a mind map is a board whose
    `board_settings` JSON says `type: "map"`. This feed selected entries and
    called every one of them a note, which is true of the row and false of
    the thing, so "Everything" listed a person's maps under the wrong icon
    and the Notes chip counted them.

    Unparseable or absent settings mean a plain board, the same fallback
    `routes_whiteboard._board_settings` takes for the same reason: a board
    whose settings JSON has been corrupted is still a board.
    """
    if not getattr(entry, "is_board", False):
        return "note"
    try:
        parsed = json.loads(entry.board_settings or "{}")
    except (TypeError, ValueError):
        parsed = {}
    board_type = parsed.get("type") if isinstance(parsed, dict) else None
    return board_type if board_type in _BOARD_TYPES else "board"


def _documents(session: Session) -> list[dict]:
    rows = session.scalars(
        select(Document).order_by(Document.updated_at.desc()).limit(PER_KIND_LIMIT)
    )
    items = []
    for doc in rows:
        words = len(doc.content.split())
        items.append(
            {
                "kind": "document",
                "id": doc.id,
                "title": doc.title or "Untitled",
                "preview": _clip(doc.content),
                "updated_at": doc.updated_at.isoformat(),
                "detail": f"{words:,} word{'' if words == 1 else 's'}",
                # What "biggest" means for this kind. Deliberately not
                # normalised across kinds: comparing a document's words with
                # an image's bytes would be a number that sorts and means
                # nothing, so the sort is within a kind or across a mixed list
                # where the person can see what they are looking at.
                "size": words,
                "entry_id": None,
                "mime": None,
                "pinned": False,
            }
        )
    return items


def _chats(session: Session) -> list[dict]:
    rows = session.scalars(
        select(Conversation)
        .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        .limit(PER_KIND_LIMIT)
    )
    items = []
    for chat in rows:
        try:
            messages = json.loads(chat.messages)
        except (ValueError, TypeError):
            # A hand-edited or truncated row costs this chat's preview, not the
            # whole Library.
            messages = []
        first_question = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        turns = len(messages) // 2
        items.append(
            {
                "kind": "chat",
                "id": chat.id,
                "title": chat.title or "Untitled chat",
                # The first question, because you remember what you asked far
                # more often than what the chat ended up being called, the
                # same reasoning the conversation list already used.
                "preview": _clip(first_question),
                "updated_at": chat.updated_at.isoformat(),
                "detail": f"{turns} turn{'' if turns == 1 else 's'}",
                "size": turns,
                "entry_id": None,
                "mime": None,
                "pinned": bool(chat.pinned),
            }
        )
    return items


def _images(session: Session) -> list[dict]:
    """Attached files, images first, but not images *only*.

    §4 says "images", and a Library that showed the photo you attached and
    silently hid the PDF beside it would be lying about what it holds. The
    filter is called Files for that reason, and images are what it mostly is.
    """
    rows = session.execute(
        select(Attachment, Entry)
        .join(Entry, Attachment.entry_id == Entry.id)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            # An attachment on a private note is as private as the note. The
            # Library is a browsing surface and would otherwise be the one
            # place a locked-away note's contents show up in plain sight.
            Entry.is_private == False,  # noqa: E712
        )
        .order_by(Attachment.created_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all()
    items = []
    for attachment, entry in rows:
        # Reported: "sketches appear in the files section in the library all
        # tab with other file attachments." A sketch is a note whose whole
        # content is its drawing (`![sketch](...)` and nothing else), stored
        # as an Attachment: it is a picture, and the Images sub-tab already
        # lists it as one. Listing its attachment here again as a "file"
        # put every sketch in two places, one of them wrong.
        # An image attachment is never a "file" here: it has the Images
        # sub-tab and the note card's own thumbnail. Reported with a
        # screenshot: "sketches still show in the library all tab's files
        # section". The old rule only skipped images on notes with no text,
        # so a captioned sketch counted as a PDF-shaped file.
        if (attachment.mime or "").startswith("image/"):
            continue
        kind_word = (attachment.mime or "").split("/")[-1].upper() or "FILE"
        items.append(
            {
                "kind": "file",
                "id": attachment.id,
                "title": attachment.filename,
                # The note it hangs on: an attachment with no context is a
                # filename, and the reason you kept it is the note.
                "preview": _clip(entry.content),
                "updated_at": attachment.created_at.isoformat(),
                "detail": f"{_human_size(attachment.size)} · {kind_word}",
                "size": attachment.size,
                "entry_id": entry.id,
                "mime": attachment.mime,
                "pinned": False,
            }
        )
    return items


def _archive(session: Session) -> list[dict]:
    """The recycle bin, under its honest name.

    §4 lists an "archive" and this app has no separate archive, it has a bin
    that keeps notes until it is emptied. Inventing a second concept so the
    word matches would give the user two places deleted notes might be; showing
    the bin here is the same list from the surface built for finding things.
    """
    rows = session.scalars(
        select(Entry)
        .where(
            Entry.is_deleted == True,  # noqa: E712
            Entry.is_private == False,  # noqa: E712
        )
        .order_by(Entry.created_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all()
    # Same reasoning as `_notes()` below: a bin card showed a sketch's
    # drawing (a real Attachment) but nothing for a pasted-image note (inline
    # markdown, no Attachment): the bin shouldn't be less consistent than
    # the live list just because it's a smaller surface.
    entry_ids = [entry.id for entry in rows]
    thumb_by_entry: dict[int, int] = {}
    if entry_ids:
        thumb_rows = session.execute(
            select(Attachment.entry_id, Attachment.id)
            .where(Attachment.entry_id.in_(entry_ids), Attachment.mime.like("image/%"))
            .order_by(Attachment.created_at.asc())
        ).all()
        for owner_id, attachment_id in thumb_rows:
            thumb_by_entry.setdefault(owner_id, attachment_id)
    items = []
    for entry in rows:
        content = entry.content or ""
        # Same fix as `_notes()` below, for the same reason: a note that wrote
        # its own heading should be titled by that heading, not by a 60-char
        # clip of the raw content, which quoted the heading into the title
        # *and* opened the preview line with it again right underneath.
        own_title = extract_title(content) if content else None
        preview_source = remove_title(content) if own_title else content
        thumb_id = thumb_by_entry.get(entry.id)
        items.append(
            {
                "kind": "archived",
                "id": entry.id,
                "title": own_title or (_clip(content)[:60] or "Empty note"),
                "preview": _clip(preview_source),
                "updated_at": entry.created_at.isoformat(),
                "detail": "in the bin",
                "size": len(content),
                "entry_id": entry.id,
                "mime": None,
                "pinned": False,
                "thumb_attachment_id": thumb_id,
                "thumb_url": None if thumb_id else _first_inline_image_url(content),
            }
        )
    return items


def _shelved(session: Session) -> list[dict]:
    """A real archive (BACKLOG §30b / ROADMAP Tier 3), distinct on purpose
    from `_archive()` above despite the similar name.

    `_archive()`'s own docstring records a deliberate earlier decision:
    this app has no separate archive, it has a bin, and inventing a second
    concept just to match the word "archive" would give a deleted note two
    possible homes. This is not that, `Entry.archived_at` never implies
    `is_deleted`, nothing here is bound for auto-clear or purge, and a
    shelved note stays reachable everywhere except the ordinary list and
    the Notes tab, the same "kept, out of the way" shape the bin already
    has for a genuinely different reason. Named "shelved" (`kind`, not the
    user-facing label) specifically so it cannot be confused with
    `"kind": "archived"` above at the code level, even though the two
    English words mean almost the same thing.

    Extended to chats and documents (BACKLOG §30b's own named remaining
    scope, after notes got this first): each carries a `"subtype"`, 
    `"note"`/`"chat"`/`"document"`, since `"kind": "shelved"` alone no
    longer says which unarchive route or menu the frontend should use.
    """
    rows = session.scalars(
        select(Entry)
        .where(
            Entry.archived_at.is_not(None),
            Entry.is_deleted == False,  # noqa: E712
            Entry.is_private == False,  # noqa: E712
        )
        .order_by(Entry.archived_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all()
    # Same reasoning as `_notes()`/`_archive()`: this shouldn't be less
    # consistent about sketch vs. pasted-image thumbnails than either.
    entry_ids = [entry.id for entry in rows]
    thumb_by_entry: dict[int, int] = {}
    if entry_ids:
        thumb_rows = session.execute(
            select(Attachment.entry_id, Attachment.id)
            .where(Attachment.entry_id.in_(entry_ids), Attachment.mime.like("image/%"))
            .order_by(Attachment.created_at.asc())
        ).all()
        for owner_id, attachment_id in thumb_rows:
            thumb_by_entry.setdefault(owner_id, attachment_id)
    items = []
    for entry in rows:
        content = entry.content or ""
        own_title = extract_title(content) if content else None
        preview_source = remove_title(content) if own_title else content
        thumb_id = thumb_by_entry.get(entry.id)
        items.append(
            {
                "kind": "shelved",
                "subtype": "note",
                "id": entry.id,
                "title": own_title or (_clip(content)[:60] or "Empty note"),
                "preview": _clip(preview_source),
                "updated_at": entry.archived_at.isoformat(),
                "detail": "archived",
                "size": len(content),
                "entry_id": entry.id,
                "mime": None,
                "pinned": False,
                "thumb_attachment_id": thumb_id,
                "thumb_url": None if thumb_id else _first_inline_image_url(content),
            }
        )
    for chat in session.scalars(
        select(Conversation)
        .where(Conversation.archived_at.is_not(None))
        .order_by(Conversation.archived_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all():
        try:
            messages = json.loads(chat.messages)
        except (ValueError, TypeError):
            messages = []
        first_question = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        items.append(
            {
                "kind": "shelved",
                "subtype": "chat",
                "id": chat.id,
                "title": chat.title or "Untitled chat",
                "preview": _clip(first_question),
                "updated_at": chat.archived_at.isoformat(),
                "detail": "archived",
                "size": len(messages) // 2,
                "entry_id": None,
                "mime": None,
                "pinned": False,
            }
        )
    for doc in session.scalars(
        select(Document)
        .where(Document.archived_at.is_not(None))
        .order_by(Document.archived_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all():
        items.append(
            {
                "kind": "shelved",
                "subtype": "document",
                "id": doc.id,
                "title": doc.title or "Untitled",
                "preview": _clip(doc.content),
                "updated_at": doc.archived_at.isoformat(),
                "detail": "archived",
                "size": len(doc.content.split()),
                "entry_id": None,
                "mime": None,
                "pinned": False,
            }
        )
    return items


def _notes(session: Session) -> list[dict]:
    """Your live notes.

    The Notes tab is where you *work with* them; this is where you manage them
    - the same distinction the Library draws everywhere else. It is what makes
    the bulk controls mean anything: selecting nine notes and retagging them is
    a management act, and there was nowhere in the app to do it across kinds.

    Private notes appear as a *count* and never as content: hiding them
    entirely would make the Library quietly disagree with the notebook's own
    total, and showing their text would defeat the encryption.
    """
    rows = session.execute(
        select(Entry, Category.name)
        .outerjoin(Category, Entry.category_id == Category.id)
        # A draft is unfinished by definition, the Notes tab's own browse
        # list already keeps every draft out of "All notes" and every
        # category filter (`app.js`'s `!e.is_draft` throughout) for exactly
        # that reason. This query didn't match it: an unfinished draft was
        # showing up as a first-class card in Library → "Everything",
        # reported directly ("draft notes appear as regular notes in the
        # main library section").
        .where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.archived_at.is_(None),
            Entry.is_draft == False,  # noqa: E712
        )
        .order_by(Entry.pinned.desc(), Entry.created_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all()
    # A sketch is a note whose actual content is an Attachment, not text, the
    # caption is all `preview` had to show, which is why a sketch card in the
    # Library read as a bare title with nothing under it. One bulk query for
    # every image attachment on this page of notes, first-per-note kept, so
    # showing a thumbnail costs one extra query total rather than one per
    # note.
    entry_ids = [entry.id for entry, _ in rows]
    thumb_by_entry: dict[int, int] = {}
    if entry_ids:
        thumb_rows = session.execute(
            select(Attachment.entry_id, Attachment.id)
            .where(Attachment.entry_id.in_(entry_ids), Attachment.mime.like("image/%"))
            .order_by(Attachment.created_at.asc())
        ).all()
        for owner_id, attachment_id in thumb_rows:
            thumb_by_entry.setdefault(owner_id, attachment_id)
    items = []
    for entry, category in rows:
        private = bool(getattr(entry, "is_private", False))
        text = "" if private else (entry.content or "")
        # A note that gave itself a heading, Capture's "Optional title"
        # field, or an AI-generated title, is titled by that heading,
        # verbatim. The old title was a 60-character clip of the raw
        # content instead, which (for a titled note) quoted the heading
        # *and* however many words of the body fit in what was left, then
        # the preview line underneath opened with the same heading text
        # again: a note titled "Car insurance renewal" read as "Car
        # insurance renewal Renew the car..." over "Car insurance renewal
        # Renew the car insurance before...". Titleless notes are
        # unaffected: `extract_title` returns None for them, same fallback
        # as before.
        own_title = extract_title(text) if text else None
        preview_source = remove_title(text) if own_title else text
        items.append(
            {
                "kind": _entry_kind(entry),
                "id": entry.id,
                "title": own_title or ((_clip(text)[:60] if text else "Private note") or "Empty note"),
                "preview": "" if private else _clip(preview_source, NOTE_PREVIEW_CHARS),
                "updated_at": entry.created_at.isoformat(),
                "detail": category or "Uncategorised",
                "size": len(text),
                "entry_id": entry.id,
                "mime": None,
                "pinned": bool(entry.pinned),
                "private": private,
                # A meeting note is tagged "meeting" at the point it's saved
                # (saveMeetingNote in app.js): this is what lets the
                # toolbar's "Meetings only" toggle filter for real, rather
                # than the earlier "Meeting Notes" sub-tab's `tag:meeting`
                # in the search box, which matched nothing: this endpoint
                # never sent tags at all, so it always showed an empty grid.
                "tags": json.loads(entry.tags) if entry.tags else [],
                # Never for a private note, hiding the text but showing a
                # thumbnail of what it's a photo of would be the same
                # encryption bypass showing the preview text would be.
                "thumb_attachment_id": None if private else thumb_by_entry.get(entry.id),
                # The other half of the same picture: a note whose image was
                # pasted or dropped in (inline markdown, no Attachment row)
                # rather than drawn (a sketch, an Attachment), only checked
                # once there's no Attachment thumbnail, so a sketch that also
                # happens to mention `![...]() ` in its caption still shows
                # its own drawing, not whatever the caption points at.
                "thumb_url": (
                    None
                    if private or thumb_by_entry.get(entry.id)
                    else _first_inline_image_url(text)
                ),
            }
        )
    return items


#: What the audit log's verbs mean to a person. The raw values are the app's
#: own vocabulary ("queried", "purged") and reading them back is how a log
#: becomes something only its author can use.
_ACTION_WORDS = {
    "created": "Created",
    "edited": "Edited",
    "deleted": "Moved to the bin",
    "restored": "Restored",
    "purged": "Deleted for good",
    "queried": "Asked",
    "linked": "Linked",
    "unlinked": "Unlinked",
    "pinned": "Pinned",
    "renamed": "Renamed",
    "merged": "Merged",
    "decrypted": "Viewed (decrypted)",
}

#: What the log's *nouns* are called, article included.
#:
#: The first version glued the verb to the raw `entity_type` and produced
#: "Edited a preferences" and "Unlocked a user". A record of what you did that
#: is written in the schema's vocabulary is a record only its author can read,
#: which is the same reason the verbs above are translated, and getting it
#: half right is arguably worse, because it reads as a bug rather than as
#: jargon. The article lives in the phrase so uncountable things can simply not
#: have one, and an unknown type falls back to itself with no article rather
#: than to broken grammar.
_ENTITY_WORDS = {
    "entry": "a note",
    "category": "a category",
    "document": "a document",
    "conversation": "a chat",
    "chat": "a chat",
    #: routes_chat.py's AGENT_SURFACE. A turn that could reach for a tool is
    #: logged apart from a plain question so the "Ask again" chips only offer
    #: back things worth asking again; the log itself still keeps both, and
    #: this is what stops the new one reading as "Asked a agent".
    "agent": "the agent",
    "reminder": "a reminder",
    "skill": "a skill",
    "tag": "a tag",
    "attachment": "a file",
    "preferences": "your settings",
    "user": "the notebook",
    "recycle_bin": "the bin",
}


def _drafts(session: Session) -> list[dict]:
    """Unfinished notes, as their own kind.

    Drafts are *deliberately* absent from `_notes()`, an unfinished draft
    showing up as a first-class card in the Library was reported and fixed,
    and that exclusion is load-bearing (see the comment on that query). So
    surfacing them here is a separate collector rather than a relaxed filter:
    they get `kind: "draft"`, which means the Drafts chip can find them while
    "Everything" still does not show them, exactly as before.

    This replaces the Library's former Drafts *sub-tab*. A draft is a state a
    note is in, not a different kind of object, so it belongs in the filter
    row beside Notes and Documents rather than in a tab of its own.
    """
    rows = session.execute(
        select(Entry, Category.name)
        .outerjoin(Category, Entry.category_id == Category.id)
        .where(
            Entry.is_deleted == False,  # noqa: E712
            Entry.archived_at.is_(None),
            Entry.is_draft == True,  # noqa: E712
        )
        .order_by(Entry.created_at.desc())
        .limit(PER_KIND_LIMIT)
    ).all()

    items = []
    for entry, category in rows:
        private = bool(getattr(entry, "is_private", False))
        text = "" if private else (entry.content or "")
        own_title = extract_title(text) if text else None
        preview_source = remove_title(text) if own_title else text
        items.append(
            {
                "kind": "draft",
                "id": entry.id,
                "title": own_title
                or ((_clip(text)[:60] if text else "Private note") or "Empty draft"),
                "preview": "" if private else _clip(preview_source, NOTE_PREVIEW_CHARS),
                "updated_at": entry.created_at.isoformat(),
                "detail": category or "Uncategorised",
                "size": len(text),
            }
        )
    return items


def _activity(session: Session) -> list[dict]:
    """What you did, as a kind rather than as a panel.

    It was behind a button in the Notes sidebar, which is a strange place for a
    record of everything you did *anywhere*, and a list of things you did is
    the same shape as a list of things you made, so it costs one entry in this
    function rather than a surface of its own.
    """
    rows = session.scalars(
        select(AuditLog)
        # The bookkeeping events (a version snapshotted before an edit, the
        # dates re-resolved because the text changed) always accompany the
        # edit that caused them, so a feed that shows both says everything
        # twice and buries the half a person recognises.
        .where(AuditLog.action.notin_(sorted(events.QUIET_ACTIONS)))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(PER_KIND_LIMIT)
    )
    items = []
    for row in rows:
        word = _ACTION_WORDS.get(row.action, row.action.capitalize())
        thing = _ENTITY_WORDS.get(row.entity_type, row.entity_type)
        items.append(
            {
                "kind": "activity",
                "id": row.id,
                "title": f"{word} {thing}",
                "preview": _clip(row.detail or "", ACTIVITY_DETAIL_CHARS),
                "updated_at": row.created_at.isoformat(),
                "detail": thing,
                # An event has no size. Its recency is the only ordering that
                # means anything, and "biggest first" falls back to it.
                "size": 0,
                "entry_id": row.entity_id if row.entity_type == "entry" else None,
                "mime": None,
                "pinned": False,
            }
        )
    return items


def _tags(session: Session) -> list[dict]:
    """Tags, with how many notes carry each.

    A tag manager is a finding surface behind a sidebar button, which is the
    exact description of everything else that moved here. Renaming and merging
    still happen through /tags, this is the list, not a second implementation.

    Capped at PER_KIND_LIMIT, the same bound every other kind section in
    this file already carries, this was the one exception, left uncapped
    when `manager.all_tags` was made cheap (§86, a cache keyed by notebook
    fingerprint), which fixed the *cost* of computing the dict but not the
    length of what this endpoint sent to the browser. `all_tags()` is
    already most-used-first, so the slice keeps the tags anyone is actually
    likely to be finding by. `GET /tags` (routes_tags.py): the Tag
    Manager's own listing, not this finder, is deliberately left
    uncapped: its job is renaming or deleting *any* tag, including a
    rarely-used one that a length cap here would hide from it entirely.
    """
    from memorymap.entry import manager

    counts = list(manager.all_tags(session).items())[:PER_KIND_LIMIT]
    return [
        {
            "kind": "tag",
            "id": index,
            "title": name,
            "preview": "",
            # Tags have no timestamp of their own. The list is sorted by use,
            # and this keeps "newest first" from shuffling it into nonsense.
            "updated_at": "",
            "detail": f"{count} note{'' if count == 1 else 's'}",
            "size": count,
            "entry_id": None,
            "mime": None,
            "pinned": False,
        }
        for index, (name, count) in enumerate(counts)
    ]


def _overview(session: Session, items: list[dict]) -> dict:
    """The state of the notebook, in the numbers a management screen opens with.

    Derived from the list that was just built wherever possible, so the panel
    and the grid can never disagree, a header saying "12 documents" above a
    grid showing 11 is worse than no header.
    """
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    stored = sum(item["size"] for item in items if item["kind"] == "file")
    private = sum(1 for item in items if item.get("private"))
    return {
        "notes": kinds.get("note", 0),
        "private_notes": private,
        "documents": kinds.get("document", 0),
        "chats": kinds.get("chat", 0),
        "files": kinds.get("file", 0),
        "tags": kinds.get("tag", 0),
        "binned": kinds.get("archived", 0),
        "shelved": kinds.get("shelved", 0),
        "attachment_bytes": stored,
        "attachment_size": _human_size(stored),
        "words": sum(
            item["size"] for item in items if item["kind"] == "document"
        ),
    }


@router.get("/library")
def library(session: Session = Depends(get_session)) -> dict:
    """Everything you made, newest first within each kind.

    One call for eight kinds, because the Library is now the app's management
    screen rather than a browser for two lists: a client assembling this from
    eight endpoints would fire eight requests to paint one page and would still
    miss the ninth kind the next person adds.

    `counts` is sent alongside rather than left for the client to derive: the
    filter chips show them, and a chip reading "Files 0" is a useful thing to
    see *before* pressing it. `overview` is the same argument one level up.
    """
    items = (
        _notes(session)
        + _documents(session)
        + _chats(session)
        + _images(session)
        + _tags(session)
        + _archive(session)
        + _shelved(session)
        + _drafts(session)
        + _activity(session)
    )
    counts: dict[str, int] = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "items": items,
        "counts": counts,
        "overview": _overview(session, items),
    }
