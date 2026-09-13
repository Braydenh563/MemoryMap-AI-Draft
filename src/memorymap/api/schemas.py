"""Pydantic request/response shapes shared by the API routes."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator



class SpaceCreate(BaseModel):
    # `id` is accepted for backward compatibility with older frontend
    # payloads but is always ignored, the server slugifies `name` instead
    # (routes_spaces.create_space). A client-chosen id was how "all" and
    # "default" could be created and break the reserved sentinels, so the
    # server no longer trusts it at all rather than merely validating it.
    id: str | None = None
    name: str = Field(min_length=1)
    icon: str = Field(min_length=1, default="ph-circles-four")

class SpaceUpdate(BaseModel):
    # Optional: update_space only writes fields the caller actually sent,
    # so omitting one (e.g. renaming without touching the icon) can't
    # blank out the other with None (see routes_spaces.update_space).
    name: str | None = Field(default=None, min_length=1)
    icon: str | None = Field(default=None, min_length=1)
    #: None means "leave as it is", the same convention as the two above.
    hidden_from_all: bool | None = None

class SpaceResponse(BaseModel):
    id: str
    name: str
    icon: str
    #: True when this space's contents are kept out of "All spaces".
    hidden_from_all: bool = False
    
    class Config:
        from_attributes = True

#: The longest a note may be, and the longest a tag may be.
#:
#: Measured 2026-09-12: a 5 MB note was accepted and took 2.26 s of blocking
#: handler time, while a 5 MB *document* was refused, because
#: `routes_documents` has had `MAX_CONTENT` since it was written and capture
#: never grew one. The same app said yes and no to the same paste depending
#: on which box it went in. This is that number, not a new opinion about how
#: long a note may be: 500,000 characters is a hundred times the longest note
#: anyone writes and a tenth of what hurt.
#:
#: A tag is a label. 50,000 characters was accepted as one, which is a chip
#: 50,000 characters wide in every list the note appears in. 60 is twice what
#: `librarian.py` already allows itself when it suggests one.
MAX_NOTE_CONTENT = 500_000
MAX_TAG_LENGTH = 60


class EntryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_NOTE_CONTENT, description="The thought to store")
    tags: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("tags")
    @classmethod
    def _tags_are_labels(cls, tags: list[str]) -> list[str]:
        """A tag is a label, so it has a label's length.

        Clipped rather than refused: a save that fails because one tag was
        long throws away the note, which is a worse answer than a shortened
        tag. Blank ones drop out, which is what a trailing comma produces.
        """
        return [tag.strip()[:MAX_TAG_LENGTH] for tag in tags if tag and tag.strip()]
    # Guided mode: the user picks the category up front and
    # the AI janitor is skipped entirely.
    category: str | None = None
    # Train-of-thought: continue an existing entry.
    parent_id: int | None = None
    # Documents this note belongs with, attached as it is saved. Asked for
    # directly: "a way to link documents to new notes I create in the capture
    # tab". Doing it on create rather than afterwards is the point, the
    # connection is obvious while you are writing and forgotten by the time
    # the note is in a list.
    document_ids: list[int] = Field(default_factory=list, max_length=10)
    # A note captured from the text-selection popup, not yet reviewed.
    is_draft: bool = False
    # Where a web-reader clipping came from (BACKLOG §65): real metadata,
    # not parsed back out of the markdown blockquote `saveSelectionAsNote`
    # (app.js) still writes into `content` for portability. Both optional
    # and independent: a source without a title still renders (falls back
    # to the URL), the same as the frontend's own `clippingMarkdown` already
    # falls back.
    source_url: str | None = Field(default=None, max_length=2000)
    source_title: str | None = Field(default=None, max_length=300)
    #: Save now, decide the category later on a background thread.
    #:
    #: Filing asks a local model, which on a small machine is seconds, and
    #: it used to happen *inside* this request, so the composer stayed
    #: disabled behind "Filing…" for the whole of it. With this set the
    #: response comes back as soon as the note is on disk, carrying
    #: `filing_state: "pending"`; the caller polls `GET /entries/{id}/filing`
    #: (or just reloads the list) to find out where it landed.
    #:
    #: Ignored when `category` or `parent_id` decides the category anyway, 
    #: there is nothing to defer in either case.
    defer_filing: bool = False


class EntryUpdate(BaseModel):
    """Manual override: only provided fields change."""

    #: The same two limits `EntryCreate` carries, for the same reason. A cap
    #: that only guards the create path is not a cap: every note in the
    #: notebook can be edited, so the long paste and the 50,000-character tag
    #: just arrive through `PUT` instead. Found by asking where else the
    #: shape this was fixed in can enter.
    content: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_CONTENT)
    category: str | None = None
    tags: list[str] | None = Field(default=None, max_length=200)

    @field_validator("tags")
    @classmethod
    def _tags_are_labels(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return [tag.strip()[:MAX_TAG_LENGTH] for tag in tags if tag and tag.strip()]
    pinned: bool | None = None
    is_draft: bool | None = None


class ContextBody(BaseModel):
    """Extra context appended to an existing note."""

    text: str = Field(min_length=1, max_length=10_000)


class LinkOut(BaseModel):
    link_id: int
    entry_id: int  # the entry on the other end
    preview: str  # first few words of that entry
    reason: str | None = None  # why these are connected, if anyone said or it was deduced
    # 0..1, set only when `reason` above came from embedding similarity
    # rather than from a person or the AI saying it, see EntryLink.reason_confidence.
    reason_confidence: float | None = None
    #: "out" when this note is the link's source, "in" when it is the target.
    #:
    #: `links_for_entry` has always returned both directions merged into one
    #: list, so a note could show what it was connected to but never which
    #: way round: and "this note points at that one" and "that one points at
    #: this" are different facts. Asked for by way of Kortex's own
    #: Connections block, which shows every link with an in/out arrow.
    #: Defaults to "out" so an older client (or a caller that doesn't care)
    #: reads exactly as it did before this field existed.
    direction: str = "out"


class AttachmentOut(BaseModel):
    id: int
    filename: str
    size: int
    is_image: bool


class SimilarOut(BaseModel):
    """A near-duplicate spotted while saving."""

    id: int
    preview: str
    similarity: float


class DocumentRefOut(BaseModel):
    """Just enough of a document to name it and open it."""

    id: int
    title: str


class EntryDateOut(BaseModel):
    """A relative time phrase, and the date it resolved to.

    The phrase travels with the date on purpose: the resolution is a rule
    ("next Friday" = the Friday of next week), not a fact, and a reader can
    only disagree with it if both are visible.
    """

    phrase: str
    at: date
    precision: str = "day"


class EntryOut(BaseModel):
    id: int
    content: str
    # A note's own leading `# Heading`, if it wrote one, not a stored,
    # separately-edited field. Editing the title is editing that line, the
    # same as editing any other line of the note; there's no second field to
    # go out of sync with the content it's supposedly titling.
    title: str | None = None
    category: str
    tags: list[str]
    ai_confidence: int
    access_count: int = 0
    last_opened_at: datetime | None = None
    parent_id: int | None = None
    pinned: bool = False
    user_filed: bool = False
    # Private notes are encrypted at rest and kept out of search and the AI.
    is_private: bool = False
    # Captured from the text-selection popup, not yet reviewed.
    is_draft: bool = False
    #: A whiteboard/concept map, which is an Entry like any other (see
    #: `Entry.is_board`). The frontend had no way to tell one from a note at
    #: all, so a board could not be offered as a link target, filtered out of
    #: a note list, or labelled as what it is, every surface either treated
    #: it as a note or hard-coded a second fetch of `/whiteboard/boards`.
    is_board: bool = False
    # Where a web-reader clipping came from, when it was one (BACKLOG §65).
    source_url: str | None = None
    source_title: str | None = None
    #: Where this note sat in an imported vault (`Projects/Roadmap.md`), or
    #: "" for one written here. The Contents index groups on it, and the
    #: wiki-link resolver matches its filename, see `Entry.source_path`.
    source_path: str = ""
    #: Which space this note is filed in. Added for INBOX 1a/38: notes
    #: carried this on the row (`Entry.workspace_id`) all along, but nothing
    #: sent it to the frontend, so a note card had no way to say which space
    #: it belonged to, and "notes from a deleted space appear in All spaces"
    #: could not be told apart from "the space's own notes were correctly
    #: kept, and these are unrelated notes that were always in Default
    #: Space." "default" is where a deleted space's notes land (see
    #: routes_spaces.py); it is a real row in `spaces`, not a sentinel, so
    #: the frontend can always resolve this against the spaces list it
    #: already loads for the switcher.
    workspace_id: str = "default"
    created_at: datetime
    deleted_at: datetime | None = None  # set only in the recycle-bin view
    archived_at: datetime | None = None  # set only when archived (BACKLOG §30b)
    links: list[LinkOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    # Documents this note is attached to: [{"id": 3, "title": "Trip plan"}].
    documents: list["DocumentRefOut"] = Field(default_factory=list)
    # What the note's relative time phrases meant when it was written (§10A):
    # [{"phrase": "next friday", "at": "2026-08-07", "precision": "day"}].
    dates: list["EntryDateOut"] = Field(default_factory=list)
    # How this entry was filed, only present on the create response:
    # 'semantic-match' | 'llm' | 'user' | 'thread' | 'none'
    filed_by: str | None = None
    # 'done' | 'pending' | 'failed', see Entry.filing_state. A note saved
    # with `defer_filing` comes back 'pending' and settles later.
    filing_state: str = "done"
    # Near-duplicate warning: only present on the create response.
    similar: SimilarOut | None = None
