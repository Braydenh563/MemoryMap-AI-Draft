"""Capture, read, edit, soft-delete, restore, and link entries.

Handlers are plain `def` (not async) on purpose: FastAPI then runs them
in a threadpool, which keeps the server responsive while blocking AI
calls run (plan §4).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.ai import extractor, janitor, learning, librarian, links
from memorymap.ai.ollama_client import OllamaError
from memorymap.api.schemas import (
    AttachmentOut,
    ContextBody,
    DocumentRefOut,
    EntryCreate,
    EntryDateOut,
    EntryOut,
    EntryUpdate,
    LinkOut,
    SimilarOut,
)
from memorymap.core import deps, events, vault
from memorymap.core.database import (  # noqa: F401 (EntryLink used in link_suggestions)
    AuditLog,
    Bookmark,
    Document,
    DocumentLink,
    EmbeddingRecord,
    Entry,
    EntryBookmark,
    EntryLink,
    EntryRevision,
    MediaUpload,
    WhiteboardNode,
    utcnow,
)
from memorymap.core.deps import get_session
from memorymap.entry import duplicates, manager
from memorymap.search import engine as search_engine
from memorymap.search import search_manager

router = APIRouter(prefix="/entries", tags=["entries"])

logger = logging.getLogger("memorymap.api.entries")


def _preview(text: str, length: int = 60) -> str:
    """A short, readable version of a note for link chips and lists.

    The [[link]] syntax is scaffolding rather than content, so a preview shows
    the words without the brackets, seeing "[[bread proving]]" on a link chip
    that already means "linked to bread proving" is just noise.
    """
    plain = manager.WIKI_LINK.sub(r"\1", text or "")
    return plain if len(plain) <= length else plain[: length - 1] + "…"


def _to_out(
    session: Session,
    entry,  # noqa: ANN001
    filed_by: str | None = None,
    similar: SimilarOut | None = None,
    *,
    category_name: str | None = None,
    dates: list | None = None,
    documents: list | None = None,
    links: list | None = None,
    attachments: list | None = None,
) -> EntryOut:
    # Decrypted here if private and the vault is open, every read of a
    # note's text goes through this one helper.
    #
    # The four `category_name`/`dates`/`documents`/`links` overrides let a
    # list endpoint pass in pre-fetched, bulk-queried values instead of this
    # function issuing one query per entry per field (ROADMAP.md #0 priority,
    # item 1: `GET /entries` was doing exactly that). Single-entry callers
    # (create/update/get) pass none of them and keep the original per-entry
    # queries below, unchanged.
    content = manager.readable_content(entry)
    resolved_dates = manager.entry_dates(session, entry) if dates is None else dates
    resolved_documents = (
        manager.documents_for_entry(session, entry) if documents is None else documents
    )
    resolved_links = manager.links_for_entry(session, entry) if links is None else links
    resolved_attachments = (
        manager.attachments_for(session, entry) if attachments is None else attachments
    )
    return EntryOut(
        id=entry.id,
        content=content,
        title=manager.extract_title(content),
        category=(
            manager.category_name_for(session, entry) if category_name is None else category_name
        ),
        tags=manager.entry_tags(entry),
        ai_confidence=entry.ai_confidence,
        access_count=entry.access_count,
        last_opened_at=getattr(entry, "last_opened_at", None),
        parent_id=entry.parent_id,
        pinned=entry.pinned,
        user_filed=entry.user_filed,
        is_private=bool(getattr(entry, "is_private", False)),
        is_draft=bool(getattr(entry, "is_draft", False)),
        source_url=getattr(entry, "source_url", None),
        source_title=getattr(entry, "source_title", None),
        source_path=getattr(entry, "source_path", "") or "",
        is_board=bool(getattr(entry, "is_board", False)),
        workspace_id=getattr(entry, "workspace_id", "default") or "default",
        created_at=entry.created_at,
        deleted_at=entry.deleted_at if entry.is_deleted else None,
        archived_at=entry.archived_at,
        dates=[
            EntryDateOut(phrase=d.phrase, at=d.at.date(), precision=d.precision)
            for d in resolved_dates
        ],
        documents=[
            DocumentRefOut(id=doc.id, title=doc.title) for doc in resolved_documents
        ],
        links=[
            LinkOut(
                link_id=link.id,
                entry_id=other.id,
                preview=_preview(manager.readable_content(other)),
                reason=link.reason,
                reason_confidence=link.reason_confidence,
                # The one fact the merged list could never carry. See
                # `LinkOut.direction`.
                direction="out" if link.source_entry_id == entry.id else "in",
            )
            for link, other in resolved_links
        ],
        attachments=[
            AttachmentOut(
                id=a.id,
                filename=a.filename,
                size=a.size,
                is_image=a.mime.startswith("image/"),
            )
            for a in resolved_attachments
        ],
        filed_by=filed_by,
        filing_state=getattr(entry, "filing_state", "done") or "done",
        similar=similar,
    )


def _to_out_bulk(session: Session, entries: list) -> list[EntryOut]:
    """`_to_out` for a whole list-endpoint page in a fixed number of queries
    instead of ~4 per entry (ROADMAP.md #0 priority, item 1)."""
    ids = [e.id for e in entries]
    category_names = manager.bulk_category_names(session, entries)
    dates_by_id = manager.entry_dates_bulk(session, ids)
    documents_by_id = manager.documents_for_entries_bulk(session, ids)
    links_by_id = manager.links_for_entries_bulk(session, ids)
    attachments_by_id = manager.attachments_for_entries_bulk(session, ids)
    return [
        _to_out(
            session,
            e,
            category_name=category_names.get(e.category_id, manager.UNCATEGORISED),
            dates=dates_by_id.get(e.id, []),
            documents=documents_by_id.get(e.id, []),
            links=links_by_id.get(e.id, []),
            attachments=attachments_by_id.get(e.id, []),
        )
        for e in entries
    ]


def _find_near_duplicate(session: Session, entry) -> SimilarOut | None:  # noqa: ANN001
    """Warn about a saved note that says almost the same thing.
    Purely informational: the save has already happened."""
    try:
        results = search_manager.semantic_search(
            session, entry.content, deps.get_embeddings(), limit=3
        )
    except Exception:
        return None
    for other, score in results or []:
        if other.id != entry.id and score >= 0.9:
            return SimilarOut(
                id=other.id, preview=_preview(other.content), similarity=round(score, 2)
            )
    return None


def _existing_entry(session: Session, entry_id: int):  # noqa: ANN202
    # `manager.get_entry` is `session.get(Entry, entry_id)` under the hood
    # (memorymap/entry/manager.py); going through `deps.get_or_404` directly
    # is equivalent and consolidates the 404.
    return deps.get_or_404(session, Entry, entry_id, "Entry not found")


def _process_committed_media(session: Session, plaintext_content: str) -> None:
    """Trigger OCR/captioning/vision-OCR for every `/media/…` upload this
    (plaintext, pre-encryption) note content references, see
    core/media_process.py's own docstring for why this fires here rather
    than on upload. Best-effort: an image reference to an upload that's
    already gone, or one already processed, is a fast no-op either way."""
    from memorymap.core import media_process

    media_process.process_referenced_uploads(
        session, deps.get_config().data_dir / "media", plaintext_content
    )


def _file_entry_now(session: Session, content: str) -> tuple[str, int, str]:
    """Ask the janitor where a note belongs. Whatever goes wrong in AI land,
    the note still gets saved (plan §4)."""
    try:
        return janitor.categorise(
            session,
            content,
            deps.get_embeddings(),
            deps.get_model_manager(),
            deps.get_ollama(),
        )
    except Exception:
        return manager.UNCATEGORISED, 0, "none"


def _file_entry_in_background(entry_id: int, workspace_id: str) -> None:
    """Decide a deferred note's category after its POST has already returned.

    Runs on its own daemon thread with its own session, the same shape
    `core/ocr.py`'s `extract_in_background` uses and for the same reason:
    the request this belongs to is finished, and the user is already typing
    the next note.

    Two things here are load-bearing and easy to get wrong:

    **The workspace has to be re-established by hand.** A fresh session from
    `deps.get_db()` carries no `workspace_id` in `session.info`, so the
    scoping hooks in `core/database.py` sit out entirely: which means the
    janitor would otherwise weigh *every space's* categories when deciding
    where a note from one space belongs, and could file it into a category
    that space cannot even see. `impersonate_workspace` puts the session
    back in the note's own space for the duration.

    **The note is never left saying "pending" forever.** Every exit path, 
    success, a janitor that raised, an entry deleted while the thread was
    still running: settles `filing_state`, because the composer's status
    chip and the poller in `app.js` both read it as "still working" and a
    stuck value would show a note filing itself for eternity.

    **Filing is not the only slow thing in a save**, and deferring it alone
    left the request at ~1s measured locally with no model running at all.
    Embedding the note and the near-duplicate search (itself a full semantic
    search, run only to *maybe* show an advisory toast) were the rest of it,
    and neither is anything the composer needs before the user can start
    typing again. They move here too. The duplicate warning comes back
    through `GET /entries/{id}/filing` instead of the create response, so a
    note that triggers one still gets its "you already wrote something like
    this", a moment later, in the same notification that says where it was
    filed.
    """
    from memorymap.core.deps import impersonate_workspace

    try:
        with deps.get_db().session() as session:
            with impersonate_workspace(session, workspace_id):
                entry = session.get(Entry, entry_id)
                if entry is None:
                    return  # deleted before filing finished, nothing to settle
                category, confidence, filed_by = _file_entry_now(
                    session, manager.readable_content(entry)
                )
                entry.category_id = manager.get_or_create_category(
                    session, category
                ).id
                entry.ai_confidence = confidence
                # Ordered deliberately: the vector has to exist before the
                # near-duplicate search has anything to compare against, and
                # both have to land before `filing_state` reads "done", that
                # flag is what the composer's poller stops on.
                deps.store_quietly(session, entry)
                duplicate = _find_near_duplicate(session, entry)
                if duplicate is not None:
                    entry.filing_similar_id = duplicate.id
                # `auto` rather than `done` when the AI is the one that
                # chose (Brief 13): it is the flag that makes a later move by
                # hand legible as a correction, and it is terminal for every
                # reader, the composer's poller stops on anything but
                # `pending`.
                entry.filing_state = (
                    manager.AUTO_FILED if janitor.is_ai_method(filed_by) else "done"
                )
                session.commit()
    except Exception:
        logger.warning("background filing failed for entry %s", entry_id, exc_info=True)
        try:
            with deps.get_db().session() as session:
                entry = session.get(Entry, entry_id)
                if entry is not None:
                    entry.filing_state = "failed"
                    session.commit()
        except Exception:
            logger.warning("couldn't mark entry %s as failed", entry_id, exc_info=True)


@router.post("", response_model=EntryOut, status_code=201)
def create_entry(body: EntryCreate, session: Session = Depends(get_session)) -> EntryOut:
    parent = None
    if body.parent_id is not None:
        parent = _existing_entry(session, body.parent_id)

    # Deferred only when nothing else already decides the category: with an
    # explicit `category` or a `parent_id` there is no model call to wait
    # for, so deferring would add a round trip and buy nothing.
    defer = body.defer_filing and not body.category and parent is None

    if body.category:
        # Guided mode: the user chose: the AI stays out of it entirely.
        category, confidence, filed_by = body.category, 100, "user"
    elif parent is not None:
        # Continuing a thread: a train of thought stays in its
        # parent's category: predictable beats clever here.
        category = manager.category_name_for(session, parent)
        confidence, filed_by = 75, "thread"
    elif defer:
        # Saved to disk now, filed a moment later, see
        # `_file_entry_in_background`. Uncategorised is a real, visible
        # holding place rather than a null, so a note whose filing thread
        # dies with the process is still exactly where a user can find it.
        category, confidence, filed_by = manager.UNCATEGORISED, 0, "pending"
    else:
        category, confidence, filed_by = _file_entry_now(session, body.content)

    entry = manager.create_entry(
        session,
        content=body.content,
        category_name=category,
        tags=body.tags,
        ai_confidence=confidence,
    )
    if parent is not None:
        entry.parent_id = parent.id
    if filed_by == "user":
        entry.user_filed = True
    if body.is_draft:
        entry.is_draft = True
    if body.source_url:
        entry.source_url = body.source_url
        entry.source_title = body.source_title
    if defer:
        entry.filing_state = "pending"
    elif janitor.is_ai_method(filed_by):
        entry.filing_state = manager.AUTO_FILED
    session.commit()

    # Best effort: a failed embedding only means this entry is invisible
    # to semantic search until re-indexed, never a failed save. It is logged
    # rather than swallowed, so a backend that has stopped working shows up in
    # Settings → Logs instead of quietly shrinking search.
    #
    # Skipped when filing is deferred: the same background thread does it,
    # right before the near-duplicate search that depends on it.
    if not defer:
        deps.store_quietly(session, entry)

    # [[wiki links]] become real links. Best effort for the same reason: a
    # link that can't be resolved must never cost someone their note.
    try:
        manager.sync_wiki_links(session, entry)
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("couldn't sync wiki links for entry %s", entry.id, exc_info=True)

    # Documents this note belongs with, attached as it is saved. A document
    # that has since been deleted is skipped rather than refused: the note is
    # the thing being saved, and losing it over a stale id would be absurd.
    for document_id in dict.fromkeys(body.document_ids):
        if session.get(Document, document_id) is not None:
            manager.link_document(session, document_id, entry.id)

    # A note is one of the three "committed" moments core/media_process.py
    # waits for (asked for directly: OCR/captioning/vision-OCR must not run
    # on a staged upload that never made it into a saved note). `body.content`
    # here, never `entry.content`, is deliberate: a private note's stored
    # content may already be encrypted at rest, and this is the plaintext
    # that was actually just submitted, before that happens.
    _process_committed_media(session, body.content)

    out = _to_out(
        session,
        entry,
        filed_by=filed_by,
        similar=None if defer else _find_near_duplicate(session, entry),
    )

    # Started last, on purpose: everything above still runs inside the
    # request, so the thread can never race the commit that makes this note
    # visible to its own session.
    if defer:
        threading.Thread(
            target=_file_entry_in_background,
            args=(entry.id, getattr(entry, "workspace_id", "default") or "default"),
            daemon=True,
            name=f"file-entry-{entry.id}",
        ).start()

    return out


@router.get("/{entry_id}/filing")
def filing_status(entry_id: int, session: Session = Depends(get_session)) -> dict:
    """Where a deferred note ended up, the one thing the composer polls.

    Deliberately not `GET /entries/{id}`: that serialises links, documents,
    dates and attachments through four more queries, and a poller running
    every second while a note settles would pay all of it to read three
    fields. This is the whole of what the "Filed under X" notification
    needs.
    """
    entry = _existing_entry(session, entry_id)
    similar = None
    duplicate_id = getattr(entry, "filing_similar_id", None)
    if duplicate_id is not None:
        other = session.get(Entry, duplicate_id)
        if other is not None:
            similar = {
                "id": other.id,
                "preview": _preview(manager.readable_content(other)),
            }
    return {
        "id": entry.id,
        "filing_state": getattr(entry, "filing_state", "done") or "done",
        "category": manager.category_name_for(session, entry),
        "ai_confidence": entry.ai_confidence,
        "similar": similar,
    }


class SuggestTagsBody(BaseModel):
    content: str
    tags: list[str] = Field(default_factory=list)


@router.post("/suggest-tags")
def suggest_tags_for_draft(body: SuggestTagsBody) -> dict:
    """Tag suggestions for a note that doesn't exist yet: the other half of
    a report that `/{entry_id}/reevaluate` only ever covered post-save:
    "the ai and application doesnt suggest tags either before creating a
    new note or after." "After" already had a path (buried in a kebab
    menu action, easy to never find); "before" had none at all. Reuses
    `librarian.suggest_tags` directly on the draft's own text: it only
    ever needed a string and the tags already on it, never a saved
    `Entry`, so the Capture form can offer suggestions while the user is
    still typing, before Save exists to be clicked.
    """
    content = body.content.strip()
    if not content:
        return {"suggested_tags": []}
    try:
        suggested = librarian.suggest_tags(
            content, body.tags, deps.get_model_manager(), deps.get_ollama()
        )
    except Exception:
        suggested = []
    return {"suggested_tags": suggested}


@router.post("/{entry_id}/context", response_model=EntryOut)
def add_context(
    entry_id: int, body: ContextBody, session: Session = Depends(get_session)
) -> EntryOut:
    """Append context to an existing note and let the janitor rethink the
    category with the fuller picture. If the user filed this
    entry themselves, the category is left alone, their call stands."""
    entry = _existing_entry(session, entry_id)
    entry.content = f"{entry.content}\n\n--- added context ---\n{body.text.strip()}"
    manager.log_action(session, "edited", "entry", entry.id, "context added")
    session.commit()

    # The old vector describes the old text, refresh it, best effort.
    try:
        session.execute(
            sa_delete(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry.id)
        )
        session.commit()
    except Exception:  # noqa: BLE001  # never fail the edit over the index
        logging.getLogger("memorymap.embeddings").warning(
            "couldn't clear the stale vector for entry %s", entry.id, exc_info=True
        )
        session.rollback()
    else:
        deps.store_quietly(session, entry)

    filed_by = None
    if not entry.user_filed:
        try:
            category, confidence, filed_by = janitor.categorise(
                session,
                entry.content,
                deps.get_embeddings(),
                deps.get_model_manager(),
                deps.get_ollama(),
                exclude_entry_id=entry.id,  # don't let it anchor to itself
            )
            if filed_by != "none":
                category_row = manager.get_or_create_category(session, category)
                if category_row.id != entry.category_id:
                    manager.log_action(
                        session, "edited", "entry", entry.id, f"recategorised -> {category}"
                    )
                entry.category_id = category_row.id
                entry.ai_confidence = confidence
                session.commit()
        except Exception:
            filed_by = None  # AI down, the note keeps its old category

    return _to_out(session, entry, filed_by=filed_by)


def _linked_entry_ids(session: Session, entry) -> set[int]:  # noqa: ANN001
    """Ids this note is already connected to, explicit links plus its
    thread parent/children: so re-evaluate never re-suggests them."""
    linked = {other.id for _link, other in manager.links_for_entry(session, entry)}
    if entry.parent_id is not None:
        linked.add(entry.parent_id)
    # Was `for child in manager.list_entries(session)`, loading and
    # ORM-hydrating every non-deleted note in the notebook (decrypting private
    # ones) just to find the handful whose parent_id matches. This entry has
    # at most a few children; the notebook can have thousands of notes.
    child_ids = session.scalars(
        select(Entry.id).where(Entry.parent_id == entry.id, Entry.is_deleted == False)  # noqa: E712
    )
    linked.update(child_ids)
    return linked


@router.post("/{entry_id}/reevaluate")
def reevaluate_entry(entry_id: int, session: Session = Depends(get_session)) -> dict:
    """Re-run the AI on one note (Wave: re-evaluate). Refreshes its
    confidence, and its category, unless the user filed it themselves , 
    and suggests tags and links for the user to apply. Tags and links are
    suggestion-only: nothing is tagged or linked without the user's click."""
    entry = _existing_entry(session, entry_id)

    # 1. Re-file: refresh confidence, and the category if the AI owns it.
    filed_by = None
    recategorised_to = None
    try:
        category, confidence, filed_by = janitor.categorise(
            session,
            entry.content,
            deps.get_embeddings(),
            deps.get_model_manager(),
            deps.get_ollama(),
            exclude_entry_id=entry.id,  # don't let the note anchor to itself
        )
        if filed_by != "none":
            entry.ai_confidence = confidence
            if not entry.user_filed:
                category_row = manager.get_or_create_category(session, category)
                if category_row.id != entry.category_id:
                    recategorised_to = category
                    manager.log_action(
                        session, "edited", "entry", entry.id, f"re-evaluated -> {category}"
                    )
                entry.category_id = category_row.id
            session.commit()
    except Exception:
        filed_by = None  # AI down, keep the note exactly as it was

    # 2. Suggest tags (best effort: never blocks the re-evaluation).
    suggested_tags: list[str] = []
    try:
        suggested_tags = librarian.suggest_tags(
            entry.content,
            manager.entry_tags(entry),
            deps.get_model_manager(),
            deps.get_ollama(),
        )
    except Exception:
        suggested_tags = []

    # 3. Suggest links: semantic neighbours that aren't connected yet.
    suggested_links: list[dict] = []
    try:
        already = _linked_entry_ids(session, entry)
        results = search_manager.semantic_search(
            session, entry.content, deps.get_embeddings(), limit=6
        )
        for other, score in results or []:
            if other.id == entry.id or other.id in already or score < 0.4:
                continue
            suggested_links.append(
                {"id": other.id, "preview": _preview(other.content), "similarity": round(score, 2)}
            )
            if len(suggested_links) >= 4:
                break
    except Exception:
        suggested_links = []

    return {
        "entry": _to_out(session, entry, filed_by=filed_by).model_dump(),
        "recategorised_to": recategorised_to,
        "suggested_tags": suggested_tags,
        "suggested_links": suggested_links,
    }


class ImproveBody(BaseModel):
    text: str
    mode: str = "proofread"  # proofread | rewrite | concise | custom
    # Only read when mode == "custom", the user's own instruction, in their
    # own words, instead of picking from the three presets. Length-capped to
    # match the input's own maxlength; this is one line of steering, not a
    # second prompt.
    custom_instruction: str | None = Field(default=None, max_length=200)


@router.post("/improve")
def improve_writing(body: ImproveBody) -> dict:
    """Return an AI-polished version of some note text without saving it, 
    the UI shows a before/after and the user decides. Never
    touches the note itself; the AI is a servant, not a gatekeeper."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="There's no text to improve.")
    custom_instruction = (body.custom_instruction or "").strip()
    if body.mode == "custom" and not custom_instruction:
        raise HTTPException(
            status_code=400, detail="Say what you want changed, then try again."
        )
    if not deps.get_ollama().is_running():
        raise HTTPException(
            status_code=503,
            detail="The AI isn't available right now (Ollama doesn't seem to be running).",
        )
    try:
        improved = librarian.improve_writing(
            text,
            body.mode,
            deps.get_model_manager(),
            deps.get_ollama(),
            custom_instruction=custom_instruction,
        )
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"original": text, "improved": improved, "mode": body.mode}


# Notes this similar are almost certainly worth connecting.
LINK_SUGGESTION_THRESHOLD = 0.55

#: How many of the twelve suggestions any one note may anchor. See
#: `link_suggestions` for the measurement that put this here: without a cap,
#: one note paired with six copies of itself filled half the list.
MAX_SUGGESTIONS_PER_NOTE = 2

#: How many concept matches `?semantic=true` returns. A search result is a
#: shortlist to read, not a second copy of the notebook.
SEMANTIC_LIST_LIMIT = 25


@router.get("/link-suggestions")
def link_suggestions(session: Session = Depends(get_session)) -> list[dict]:
    """Pairs of notes that mean similar things but aren't linked yet: 
    the auto-linker. Suggestion-only: it never links anything on
    its own, it hands the pairs to the UI to approve. Empty when the
    embedding backend is unavailable (semantic search off).

    Used to call `semantic_search` once *per entry*: a full embedding scan,
    for every entry, so O(entries) database round-trips each doing O(entries)
    work, and each one **re-embedding that entry's own content from scratch**
    on top of the scan. At any real notebook size that's the O(n^2) trap this
    file was checked for after §38.1's scale-test found two others: found by
    the same kind of sweep, not by profiling this one specifically, since a
    75k-note notebook running this by hand was not something worth actually
    waiting out. Rewritten to match `routes_graph._similarity_edges`'s
    already-correct shape: fetch every stored vector once, compare all
    pairs in memory: which turns O(n) queries plus O(n) re-embeddings into
    one query and zero re-embedding calls."""
    from memorymap.ai.embeddings import similar_pairs

    entries = manager.list_entries(session)
    entries_by_id = {e.id: e for e in entries if not e.is_private}
    already_linked: set[frozenset[int]] = set()
    for link in session.scalars(select(EntryLink)):
        already_linked.add(frozenset((link.source_entry_id, link.target_entry_id)))
    # Threads are already a connection, don't re-suggest parent/child.
    for entry in entries:
        if entry.parent_id is not None:
            already_linked.add(frozenset((entry.parent_id, entry.id)))
    # A pair the person has already said no to (WORLD_CLASS_PLAN I7). The same
    # set as the two above, because "you dismissed this" and "these are
    # already linked" are the same answer to this endpoint's only question:
    # is there anything left to suggest about these two. A suggestion that
    # comes back after being dismissed is the single most annoying thing a
    # suggester can do, and it is what this feature did until now: the
    # dismissal lived in the browser and died with the tab.
    for pair in learning.boosts(session, kind="links"):
        already_linked.add(frozenset(pair))

    embeddings = deps.get_embeddings()
    if not embeddings.is_ready():
        return []
    # From the engine's matrix (Brief 11), not a fresh `SELECT` of every
    # vector plus a `bytes_to_vector` per row: this process already holds the
    # array, and the pairs pass below wants exactly it.
    vectors = search_engine.vectors_by_id(session, only=set(entries_by_id))

    # `similar_pairs` hands these back best-first and blocks the matrix
    # multiply, so a big notebook costs one block of memory rather than an
    # N×N matrix. Stop at 12 rather than scoring every pair into a list first.
    #
    # **Two filters stand between "best-first" and "useful", and both were
    # added after measuring what this actually returned.** On a real 116-note
    # notebook every single one of the twelve suggestions was a pair of notes
    # with *identical* text, scoring 1.00, six of them the same stub note
    # paired with six copies of itself. The feature was working exactly as
    # written and surfacing nothing worth acting on, which is the measured
    # reason a notebook can sit at 16 linked notes out of 116 with the
    # auto-linker switched on the whole time.
    #
    #  1. A near-identical pair is a *duplicate*, not a connection. Linking
    #     two copies of one note records that a note resembles itself. This
    #     app already has a feature whose whole job is that case, so the pair
    #     belongs to it: `entry/duplicates.py`, same threshold, reusing its
    #     arithmetic word-overlap score rather than inventing a second notion
    #     of "the same". Cheap enough to run on the survivors of the vector
    #     pass, which is a handful of pairs, not the notebook.
    #  2. One note may anchor at most `MAX_SUGGESTIONS_PER_NOTE` of the
    #     twelve. Without this, the single most connectable note in a
    #     notebook takes every slot with its own neighbours (which is exactly
    #     what happened above), and the list stops being a survey of the
    #     notebook and becomes a survey of one note.
    suggestions = []
    appearances: dict[int, int] = {}
    for a, b, score in similar_pairs(vectors, LINK_SUGGESTION_THRESHOLD):
        if frozenset((a, b)) in already_linked:
            continue
        if (
            appearances.get(a, 0) >= MAX_SUGGESTIONS_PER_NOTE
            or appearances.get(b, 0) >= MAX_SUGGESTIONS_PER_NOTE
        ):
            continue
        if (
            duplicates.similarity(entries_by_id[a].content, entries_by_id[b].content)
            >= duplicates.DEFAULT_THRESHOLD
        ):
            continue
        appearances[a] = appearances.get(a, 0) + 1
        appearances[b] = appearances.get(b, 0) + 1
        suggestions.append({
            "source_id": a,
            "target_id": b,
            "source_preview": _preview(entries_by_id[a].content),
            "target_preview": _preview(entries_by_id[b].content),
            "similarity": round(score, 2),
            # Asked directly: a suggestion showed a bare percentage with no
            # sense of *why*, unlike an actual link (which gets a reason on
            # the graph edge and in Trace). `LINK_SUGGESTION_THRESHOLD`
            # equals `manager.AUTO_REASON_THRESHOLD` exactly, so every
            # suggestion here would clear the bar `create_link` uses to
            # deduce this same text, showing it before the link exists is
            # a preview of that outcome, not a separate guess.
            "reason": manager.AUTO_REASON_TEXT,
        })
        if len(suggestions) == 12:
            break
    return suggestions


#: Where dismissed tensions are remembered. A preference key rather than a new
#: table: this is a small list of pair keys, it belongs to the person rather
#: than to either note, and adding a migration for "I looked at this and it
#: was not a contradiction" would be a heavy answer to a light question.
TENSION_DISMISSED_KEY = "tensions_dismissed"

#: Tensions look at pairs the notebook already believes are about the same
#: thing (see `ai/tensions.py`, contradiction is only possible between notes
#: sharing a subject). A lower bar than `LINK_SUGGESTION_THRESHOLD` on
#: purpose: two notes that *disagree* often share less vocabulary than two
#: that agree, because the disagreement is exactly where their words differ.
TENSION_CANDIDATE_THRESHOLD = 0.45


def _tension_key(a: int, b: int) -> str:
    """A stable id for a pair, order-independent."""
    low, high = sorted((a, b))
    return f"{low}:{high}"


def _dismissed_tensions() -> set[str]:
    stored = deps.get_config().get_preference(TENSION_DISMISSED_KEY, []) or []
    return {str(key) for key in stored}


@router.get("/tensions")
def find_tensions(
    limit: int = Query(default=8, ge=1, le=20),
    session: Session = Depends(get_session),
) -> dict:
    """Places the notebook appears to disagree with itself.

    The feature `core/database.py`'s `LINK_TYPES` comment says the typed-link
    vocabulary was built for and that nothing ever produced, see
    `ai/tensions.py` for the full reasoning. Read-only and suggestion-only:
    finding a tension writes nothing, and `POST /entries/tensions/accept` is
    the only thing that creates the `contradicts` link.

    Returns `{"tensions": [...], "status": "..."}` rather than a bare list so
    an empty result can say *why* it is empty, "no model running" and "your
    notebook does not contradict itself" are completely different answers and
    a bare `[]` renders them identically, which is how a feature that never
    ran gets reported as a feature that found nothing.
    """
    from memorymap.ai.embeddings import similar_pairs
    from memorymap.ai import tensions as tensions_module

    ollama = deps.get_ollama()
    if not ollama.is_running():
        return {"tensions": [], "status": "no_model"}

    embeddings = deps.get_embeddings()
    if not embeddings.is_ready():
        return {"tensions": [], "status": "no_embeddings"}

    entries = manager.list_entries(session)
    by_id = {e.id: e for e in entries if not e.is_private and not e.is_board}
    if len(by_id) < 2:
        return {"tensions": [], "status": "too_few_notes"}

    vectors = search_engine.vectors_by_id(session, only=set(by_id))

    # A pair already marked as contradicting is a finding the person has
    # already accepted, not one to re-propose. Every other link type is left
    # alone deliberately: notes can be linked as "related" *and* disagree,
    # and that is one of the more interesting cases.
    known: set[str] = set(_dismissed_tensions())
    for link in session.scalars(select(EntryLink).where(EntryLink.link_type == "contradicts")):
        known.add(_tension_key(link.source_entry_id, link.target_entry_id))

    models = deps.get_model_manager()
    found: list[dict] = []
    checked = 0
    for a_id, b_id, score in similar_pairs(vectors, TENSION_CANDIDATE_THRESHOLD):
        if checked >= tensions_module.MAX_PAIRS_PER_PASS or len(found) >= limit:
            break
        if _tension_key(a_id, b_id) in known:
            continue
        ordered = tensions_module.order_by_time(by_id[a_id], by_id[b_id])
        if ordered is None:
            continue  # same few days, or undated, see MIN_GAP_DAYS
        checked += 1
        tension = tensions_module.compare_pair(ordered[0], ordered[1], models, ollama)
        if tension is None:
            continue
        found.append(
            {
                "key": _tension_key(tension.earlier_id, tension.later_id),
                "earlier_id": tension.earlier_id,
                "later_id": tension.later_id,
                "explanation": tension.explanation,
                "earlier_excerpt": tension.earlier_excerpt,
                "later_excerpt": tension.later_excerpt,
                "earlier_at": tension.earlier_at,
                "later_at": tension.later_at,
                "gap_days": tension.gap_days,
                "similarity": round(score, 2),
            }
        )
    status = "ok" if found else ("none_found" if checked else "no_candidates")
    return {"tensions": found, "status": status, "pairs_checked": checked}


class TensionPair(BaseModel):
    earlier_id: int
    later_id: int


@router.post("/tensions/accept")
def accept_tension(body: TensionPair, session: Session = Depends(get_session)) -> dict:
    """Record a tension as a real `contradicts` link between the two notes.

    Uses `manager.create_link` rather than inserting a row, so the link gets
    the same audit entry, the same self-link and duplicate guards, and the
    same graph/traversal treatment as one made by hand.
    """
    earlier = _existing_entry(session, body.earlier_id)
    later = _existing_entry(session, body.later_id)
    link = manager.create_link(
        session,
        earlier,
        later,
        reason="these disagree with each other",
        link_type="contradicts",
    )
    return {"created": link is not None}


@router.post("/tensions/dismiss")
def dismiss_tension(body: TensionPair) -> dict:
    """Stop offering this pair. Remembered across restarts.

    Capped, and oldest-first: without a cap this preference would grow
    without bound on a notebook where most candidates are rejected, and it
    is written to disk on every change (see `Config.set_preference`).
    """
    config = deps.get_config()
    stored = list(config.get_preference(TENSION_DISMISSED_KEY, []) or [])
    key = _tension_key(body.earlier_id, body.later_id)
    if key not in stored:
        stored.append(key)
    del stored[:-500]
    config.set_preference(TENSION_DISMISSED_KEY, stored)
    return {"dismissed": key}


class LinkSuggestionReasonPair(BaseModel):
    source_id: int
    target_id: int


class LinkSuggestionReasonsBody(BaseModel):
    pairs: list[LinkSuggestionReasonPair]


@router.post("/link-suggestions/reasons")
def link_suggestion_reasons(
    body: LinkSuggestionReasonsBody, session: Session = Depends(get_session)
) -> dict:
    """Reasons for *pending* suggestions, not yet real links, the gap
    `/links/backfill-reasons` (below) deliberately doesn't cover, since that
    one only ever touches links that already exist. Asked for directly: the
    suggestions panel's own "Why?" boxes had no way to get an AI guess
    without linking first, editing, and re-linking. Best-effort per pair: 
    one bad or private pair doesn't sink the rest, and the whole call
    degrades to an empty list rather than an error the moment the model is
    down, so the caller can tell "nothing generated" from "everything
    genuinely had one already" without a special-cased response shape."""
    reasons = []
    ai_unavailable = False
    for pair in body.pairs[:12]:  # same cap link_suggestions() itself uses
        source = session.get(Entry, pair.source_id)
        target = session.get(Entry, pair.target_id)
        if not source or not target or source.is_private or target.is_private:
            continue
        try:
            reason = librarian.generate_link_reason(
                manager.readable_content(source),
                manager.readable_content(target),
                deps.get_model_manager(),
                deps.get_ollama(),
            )
        except Exception as exc:  # model offline, or no model configured
            logger.info("link suggestion reason skipped: %s", exc)
            ai_unavailable = True
            continue
        reasons.append(
            {"source_id": pair.source_id, "target_id": pair.target_id, "reason": reason}
        )
    result = {"reasons": reasons}
    if ai_unavailable:
        result["ai_unavailable"] = True
    return result


class BackfillReasonsBody(BaseModel):
    """`ai=False` runs only the cheap embedding pass, useful when the model
    is known to be down and you just want the links marked."""

    ai: bool = True
    limit: int = Field(default=100, ge=1, le=500)


@router.post("/links/backfill-reasons")
def backfill_link_reasons(
    body: BackfillReasonsBody | None = None, session: Session = Depends(get_session)
) -> dict:
    """"None of my notes have a linked reason yet, is there an easy way to
    give them all a reason?" There wasn't: `_deduce_reason` only ever ran at
    the moment a link was *made*, so every link from before that shipped, or
    made while the embedding backend was off, stays mute forever with
    nothing to revisit it. One pass over every reason-less link, same rule
    as a fresh one, a link that still can't be deduced is left alone rather
    than given a manufactured answer.

    **Two passes, not one, and the second is the one the user actually
    wanted.** The first (embeddings) can only ever write the literal string
    "similar in meaning", it compares two vectors and has no words for what
    it found. So a notebook that ran this ended up with every link reading
    *"similar in meaning"*, which is what was reported: the button appeared to
    work and the reasons it produced said nothing.

    The second pass hands those to the model and asks it to name the actual
    connection. It is best-effort: if the model is down, the embedding pass
    has still marked the links and the audit can be re-run later, which is
    why a failure here is reported in the result rather than raised.
    """
    options = body or BackfillReasonsBody()
    result = manager.backfill_link_reasons(session)

    result["rewritten"] = 0
    if not options.ai:
        return result
    try:
        result["rewritten"] = links.audit_vague_links(
            session, deps.get_model_manager(), deps.get_ollama(), limit=options.limit
        )
    except Exception as exc:  # model offline, or no model configured
        # Not an error the caller should see as a failure: the cheap pass
        # succeeded and its work is committed.
        logger.info("link reason audit skipped: %s", exc)
        result["ai_unavailable"] = True
    return result


#: How alike two notes have to be before one is offered as "see also".
#: Unchanged from the number this route already used inline; named now that
#: the scoring moved into the engine, so the threshold and the engine's own
#: `MIN_SIMILARITY` are visibly two different decisions rather than one
#: number copied twice.
RELATED_MIN_SIMILARITY = 0.3


@router.get("/{entry_id}/related", response_model=list[EntryOut])
def related_entries(entry_id: int, session: Session = Depends(get_session)) -> list[EntryOut]:
    """Semantic neighbours of one entry ("see also")."""
    entry = _existing_entry(session, entry_id)
    # The engine's matrix rather than a scan of every stored vector per note
    # opened (Brief 11). `warm_vectors` is idempotent: it builds once per
    # process and per notebook, and returns immediately after that, so this
    # is not per-request work. `related()` itself never builds, which is what
    # the spec pins.
    try:
        search_engine.warm_vectors(session)
        neighbours = search_engine.related(session, entry.id, k=8)
    except Exception:  # noqa: BLE001  # a "see also" panel never fails a note
        neighbours = []
    wanted = [other_id for other_id, score in neighbours if score >= RELATED_MIN_SIMILARITY]
    if not wanted:
        return []
    found = {
        other.id: other
        for other in session.scalars(
            select(Entry).where(Entry.id.in_(wanted), Entry.is_deleted == False)  # noqa: E712
        )
        if not other.is_private
    }
    ordered = [found[other_id] for other_id in wanted if other_id in found]
    return [_to_out(session, e) for e in ordered[:3]]


class AttachBookmarkBody(BaseModel):
    bookmark_id: int


@router.get("/{entry_id}/bookmarks")
def entry_bookmarks(entry_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """Bookmarks attached to this note, its References, alongside the
    [[wiki links]] `links` already carries. Its own endpoint rather than a
    field on EntryOut, matching `/related` right above: only the editor
    needs this, and `_to_out_bulk`'s per-list-page bulk fetch shouldn't grow
    a query for something most renders of a note never show."""
    _existing_entry(session, entry_id)
    rows = (
        session.query(Bookmark)
        .join(EntryBookmark, EntryBookmark.bookmark_id == Bookmark.id)
        .filter(EntryBookmark.entry_id == entry_id)
        .order_by(EntryBookmark.created_at)
        .all()
    )
    return [
        {"id": b.id, "url": b.url, "title": b.title, "group_name": b.group_name}
        for b in rows
    ]


@router.post("/{entry_id}/bookmarks", status_code=201)
def attach_bookmark(
    entry_id: int, body: AttachBookmarkBody, session: Session = Depends(get_session)
) -> dict:
    _existing_entry(session, entry_id)
    deps.get_or_404(session, Bookmark, body.bookmark_id, "Bookmark not found")
    already = (
        session.query(EntryBookmark)
        .filter_by(entry_id=entry_id, bookmark_id=body.bookmark_id)
        .first()
    )
    if not already:
        session.add(EntryBookmark(entry_id=entry_id, bookmark_id=body.bookmark_id))
        session.commit()
    return {"attached": True}


@router.delete("/{entry_id}/bookmarks/{bookmark_id}")
def detach_bookmark(
    entry_id: int, bookmark_id: int, session: Session = Depends(get_session)
) -> dict:
    _existing_entry(session, entry_id)
    session.query(EntryBookmark).filter_by(
        entry_id=entry_id, bookmark_id=bookmark_id
    ).delete()
    session.commit()
    return {"detached": True}


#: A page of the plain list, not a hard ceiling on notebook size, the
#: frontend fetches pages in a loop until X-Total-Count says it has
#: everything (loadEntries in app.js). Bounds each individual request so a
#: notebook that has grown for years can't make one response unbounded; the
#: max just stops a client from asking for one absurdly large page.
ENTRIES_PAGE_SIZE = 1000
ENTRIES_PAGE_SIZE_MAX = 5000


@router.get("", response_model=list[EntryOut])
def list_entries(
    response: Response,
    deleted: bool = False,
    archived: bool = False,
    semantic: bool = False,
    q: str = "",
    limit: int = Query(default=ENTRIES_PAGE_SIZE, ge=1, le=ENTRIES_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    # **This list is the notes list, so boards are not in it by default.**
    #
    # Reported: "I made a mindmap naming it test and I think it came up as a
    # new note??", it did, on every surface built on this response. A board
    # (and a mind map, which is a board with `type: "map"`) is an `Entry`, so
    # it came back here with everything else; measured on a notebook with
    # nine maps, ten of the Notes list's twelve rows were maps.
    #
    # The default is the fix, rather than a filter in each of the four
    # surfaces that draw notes, because "the same object drawn five ways" is
    # this app's recurring failure and four client-side filters is that shape
    # exactly. `boards=only` is how the two callers that genuinely want boards
    # (the `[[wiki]]` resolver and the editor's `@` picker) ask for them, and
    # `boards=include` restores the old response for anything wanting both.
    boards: str = Query(default=manager.BOARDS_EXCLUDE),
    session: Session = Depends(get_session),
) -> list[EntryOut]:
    """Normal list, the recycle bin when ?deleted=true, the archive when
    ?archived=true, or a concept search. `deleted` and `archived` are
    mutually exclusive views (each its own held-back set), not filters
    that combine: same as `deleted` already worked before `archived`
    existed.

    `?semantic=true&q=…` is the one case the browser cannot do for itself: the
    notes list is filtered client-side by keyword, but cosine distance needs
    the vectors, which only live here.

    `limit`/`offset` page the plain list; `X-Total-Count` on the response
    says the real size regardless of the page, so a caller knows when it has
    everything. Was genuinely unbounded before, every note, every load, no
    matter the notebook's size: which is real risk for a "just works" local
    app that's supposed to degrade gracefully rather than time out or OOM.
    """
    if boards not in manager.BOARD_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"boards must be one of {', '.join(manager.BOARD_MODES)}",
        )
    if semantic and q:
        from memorymap.core import deps

        # The *complete* id set, deliberately not paginated: `allowed` below
        # decides which semantic hits are even in scope for this view (bin,
        # archive, or live), and paginating this fetch would silently drop
        # legitimate matches that happen to live past the first page. Ids
        # only, no row bodies, cheap even at real notebook scale, and the
        # thing the original unbounded-response risk was actually about was
        # sending full rows over HTTP, not counting ids in-process.
        scope_ids = manager.entry_id_scope(
            session, deleted=deleted, archived=archived, boards=boards
        )

        # Ranked, and returned ranked. The first version rebuilt the result as
        # `[e for e in entries if e.id in found_ids]`, which is the *notebook's*
        # order: so the best match could land anywhere in the list and the
        # feature looked like it was picking notes at random.
        results = search_manager.semantic_search(
            session, q, deps.get_embeddings(), limit=SEMANTIC_LIST_LIMIT
        )
        if results is None:
            # No embedding backend ready. Saying so beats silently handing back
            # the entire notebook as though it were the search result, the
            # caller can fall back to its own keyword filter.
            raise HTTPException(
                status_code=503,
                detail="Semantic search isn't ready yet: the embedding model is still loading.",
            )
        # `semantic_search` already drops anything under MIN_SIMILARITY; a
        # second threshold here was a different number for the same job.
        matched = [e for e, _score in results if e.id in scope_ids]
        response.headers["X-Total-Count"] = str(len(matched))
        return _to_out_bulk(session, matched)

    if deleted:
        entries = manager.list_deleted_entries(session, limit=limit, offset=offset)
        total = manager.count_deleted_entries(session)
    elif archived:
        entries = manager.list_archived_entries(session, limit=limit, offset=offset)
        total = manager.count_archived_entries(session)
    else:
        entries = manager.list_entries(session, limit=limit, offset=offset, boards=boards)
        total = manager.count_entries(session, boards=boards)
    response.headers["X-Total-Count"] = str(total)
    return _to_out_bulk(session, entries)


# Declared before /{entry_id} so "most-accessed" isn't parsed as an id.
@router.get("/most-accessed", response_model=list[EntryOut])
def most_accessed(session: Session = Depends(get_session)) -> list[EntryOut]:
    """Top entries by how often they've been opened or matched a
    question: the quick-access dashboard."""
    entries = manager.most_accessed_entries(session, limit=5)
    return _to_out_bulk(session, entries)


# Onboarding's own "is this notebook empty" check: deliberately just a
# number (never the full /entries payload) so the first-run tour can decide
# whether to offer example notes without pulling a real notebook's worth of
# content over the wire just to find out it isn't empty.
@router.get("/count")
def count_entries(session: Session = Depends(get_session)) -> dict:
    return {"count": session.scalar(select(func.count(Entry.id))) or 0}


@router.post("/seed-examples")
def seed_example_entries(session: Session = Depends(get_session)) -> dict:
    """The onboarding tour's "add example notes" offer (ROADMAP.md's
    onboarding item). Refuses on any notebook that already has a note, 
    see `manager.seed_example_notes`'s own guard."""
    created = manager.seed_example_notes(session)
    return {"created": created}


@router.get("/{entry_id}", response_model=EntryOut)
def get_entry(
    entry_id: int, deleted: bool = False, session: Session = Depends(get_session)
) -> EntryOut:
    """One entry. `?deleted=true` also reaches into the bin.

    The bin used to be a panel that listed every deleted note with its full
    text, so "read a binned note before deciding whether to restore it" came
    free. The Library shows a preview instead, which is right for a grid of
    mixed things and wrong as the *only* way to see a note you are about to
    delete for good: so the reader needs a way to fetch one binned note.

    Two things stay different from a live read, and both are deliberate:
    a deleted note is only reachable when the caller says so (a stale link to
    a binned note should still 404 rather than quietly resurrect it), and
    reading one does **not** count as using it. `access_count` feeds
    "most accessed", and a note in the bin climbing that list because you
    looked at it on the way to deleting it is the counter lying.
    """
    entry = _existing_entry(session, entry_id)
    if entry.is_deleted and not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not entry.is_deleted:
        entry.access_count += 1  # opening an entry counts as using it
        # And *when*, which is the half the dashboard's Continue pill needs:
        # a count cannot answer "the note I was last in", and `updated_at`
        # only moves when the text changes, so reading an old note left the
        # pill pointing at whatever was newest. Same guard as the count: a
        # note read on its way out of the bin has not been come back to.
        entry.last_opened_at = utcnow()
        # A private note has no audit trail at all otherwise, encrypted at
        # rest and invisible to the AI is the whole promise, but nothing
        # recorded *when* one was actually opened and decrypted for
        # reading, which is the one thing that would tell you if that
        # promise had ever been tested. Scoped to private notes only: every
        # other note already has plenty of activity logged elsewhere (see
        # the Library's own "activity is 93%+ of a real notebook" note) and
        # doesn't need a second entry for the same open.
        # Only when the vault is actually open, readable_content() returns
        # a placeholder ("Private note: unlock to read it.") rather than
        # the real text when it's locked, and logging "decrypted" for a
        # request that decrypted nothing is worse than not logging at all:
        # a trail meant to build confidence that lies about what happened
        # is the one bug this feature cannot afford.
        if bool(getattr(entry, "is_private", False)) and vault.key() is not None:
            manager.log_action(session, "decrypted", "entry", entry.id)
        session.commit()
    return _to_out(session, entry)


def _safe_filename(title: str, extension: str) -> str:
    """A title is user text; it must not steer where the file lands.

    Same rule `routes_documents.py`'s own `_safe_filename` already enforces
    for a document: not shared, because the two files don't otherwise
    import from each other and a title-to-filename sanitiser is small
    enough that a shared module for it would be the premature abstraction.
    """
    cleaned = re.sub(r"[^\w\s-]", "", title).strip() or "note"
    cleaned = re.sub(r"[\s_]+", "-", cleaned)[:60]
    return f"{cleaned}.{extension}"


@router.get("/{entry_id}/export.md")
def export_entry(entry_id: int, session: Session = Depends(get_session)) -> Response:
    """One note's own text, as a download, BACKLOG.md §95 item D.14: "Full
    export exists. There is no way to hand one note to someone."

    Mirrors `routes_documents.py`'s `export_markdown` (same route shape,
    same `Content-Disposition` filename sanitising) rather than reusing it
    directly: a note has no `file_type` the way a document does, so there
    is no second branch to share, and the two routes would only be coupled
    by the part that's already this short.

    `readable_content` is the same call `get_entry` and every other reader
    already goes through: a locked private note downloads its own "unlock
    to read it" placeholder rather than erroring or exposing ciphertext,
    identical to what viewing one already does.
    """
    entry = _existing_entry(session, entry_id)
    if entry.is_deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    content = manager.readable_content(entry)
    title = manager.extract_title(content) or content.strip()[:60] or "Untitled note"
    body = content if manager.extract_title(content) else f"# {title}\n\n{content}"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(title, "md")}"'
        },
    )


@router.put("/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: int, body: EntryUpdate, session: Session = Depends(get_session)
) -> EntryOut:
    """Manual override: the user can correct anything the AI decided
    (plan §4: the AI is a servant, not a gatekeeper)."""
    entry = _existing_entry(session, entry_id)
    content_changed = body.content is not None and body.content != entry.content
    tags_changed = body.tags is not None and body.tags != manager.entry_tags(entry)
    # Snapshot BEFORE the change, so the newest revision is always the version
    # being replaced rather than the one replacing it.
    if content_changed or tags_changed:
        manager.record_revision(session, entry)
    manager.update_entry(
        session,
        entry,
        content=body.content,
        category_name=body.category,
        tags=body.tags,
    )
    if body.pinned is not None and body.pinned != entry.pinned:
        entry.pinned = body.pinned
        manager.log_action(
            session, "edited", "entry", entry.id, "pinned" if body.pinned else "unpinned"
        )
        session.commit()
    if body.is_draft is not None and body.is_draft != entry.is_draft:
        entry.is_draft = body.is_draft
        session.commit()
    if content_changed:
        # The old vector describes the old text, refresh it, best effort.
        try:
            session.execute(
                sa_delete(EmbeddingRecord).where(EmbeddingRecord.entry_id == entry.id)
            )
            session.commit()
        except Exception:  # noqa: BLE001  # never fail the edit over the index
            logging.getLogger("memorymap.embeddings").warning(
                "couldn't clear the stale vector for entry %s", entry.id, exc_info=True
            )
            session.rollback()
        else:
            deps.store_quietly(session, entry)
        # Editing a note can introduce new [[links]]; resolve those too.
        try:
            manager.sync_wiki_links(session, entry)
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("couldn't sync wiki links for entry %s", entry.id, exc_info=True)
        # Same "committed" trigger point as create_entry, an edit can be
        # the first time an image the note already referenced actually
        # gets saved (a staged upload attached, then the note edited to
        # include it, rather than created with it already there).
        _process_committed_media(session, body.content)
    return _to_out(session, entry)


@router.delete("/{entry_id}", response_model=EntryOut)
def delete_entry(entry_id: int, session: Session = Depends(get_session)) -> EntryOut:
    """Soft delete → recycle bin. Restorable until purged."""
    entry = _existing_entry(session, entry_id)
    if not entry.is_deleted:
        manager.soft_delete_entry(session, entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/restore", response_model=EntryOut)
def restore_entry(entry_id: int, session: Session = Depends(get_session)) -> EntryOut:
    entry = _existing_entry(session, entry_id)
    if entry.is_deleted:
        manager.restore_entry(session, entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/archive", response_model=EntryOut)
def archive_entry(entry_id: int, session: Session = Depends(get_session)) -> EntryOut:
    """Kept, but out of the way (BACKLOG §30b): distinct from the recycle
    bin: never auto-cleared, never purgeable, no confirmation needed since
    nothing is at risk of being lost."""
    entry = _existing_entry(session, entry_id)
    if not entry.archived_at:
        manager.archive_entry(session, entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/unarchive", response_model=EntryOut)
def unarchive_entry(entry_id: int, session: Session = Depends(get_session)) -> EntryOut:
    entry = _existing_entry(session, entry_id)
    if entry.archived_at:
        manager.unarchive_entry(session, entry)
    return _to_out(session, entry)


@router.delete("/{entry_id}/purge")
def purge_entry(entry_id: int, session: Session = Depends(get_session)) -> dict:
    """Permanently delete ONE note from the recycle bin. Asked for directly.

    Emptying the whole bin was all-or-nothing, so getting rid of a single note
    for good meant destroying everything else in there too, which is why
    people leave the bin full instead, and then the bin is not a bin.

    **Only a binned note can be purged.** A note still in the notebook has to
    go through `DELETE /entries/{id}` first, so there is always the soft-delete
    step between an ordinary click and permanent loss. Enforced here rather
    than trusted to the UI: this is the one route in the app that destroys
    something with no undo.
    """
    entry = _existing_entry(session, entry_id)
    if not entry.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="Only notes in the recycle bin can be permanently deleted",
        )
    removed = manager.purge_entries(
        session, [entry], uploads_dir=deps.get_config().uploads_dir
    )
    return {"purged": removed, "id": entry_id}


class LinkBody(BaseModel):
    target_id: int
    # Optional: "why are these connected?" A shared tag or a reply thread
    # says why on its own; a manual link often doesn't.
    reason: str | None = Field(default=None, max_length=200)
    # What kind of connection, from core.database.LINK_TYPES. Optional, and an
    # unrecognised value is stored as null rather than rejected, see
    # manager.create_link on why a typo should not cost you the link.
    link_type: str | None = Field(default=None, max_length=24)


class LinkReasonBody(BaseModel):
    # None (or omitted/blank) clears the reason, this is also how a link
    # that got an auto-deduced reason it disagrees with is corrected back
    # to nothing, same as it would have started with.
    reason: str | None = Field(default=None, max_length=200)


class PrivacyBody(BaseModel):
    private: bool


#: How many events one request of a note's history returns. A note edited
#: every day for a year has a history worth paging through rather than
#: sending whole to a sheet that shows a dozen rows at a time.
HISTORY_PAGE = 50


def _readable(content: str) -> str:
    """Decrypt stored content for display, the same way a note itself is.

    `manager.readable_content` reads one attribute, so an event's stored
    content can borrow it without a row to hang it on.
    """
    return manager.readable_content(SimpleNamespace(content=content or ""))


@router.get("/{entry_id}/history")
def entry_history(
    entry_id: int,
    before: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> dict:
    """This note's history, as events and as past versions.

    Two lists because they answer two questions and Brief 7 deliberately
    kept both. `items` is the event log (Brief 7, WORLD_CLASS_PLAN B1):
    everything that ever happened to this note, who did it, and the state
    it left the note in, which is what the History sheet renders and what
    `POST /entries/{id}/restore/{event_id}` replays. `revisions` is the
    older per-edit snapshot list (`EntryRevision`, capped at
    `manager.MAX_REVISIONS`), still written, still restorable through its
    own route, and still the only thing that holds a version of a note
    whose events predate the log.

    `before` pages backwards through the events by id, newest first.
    """
    entry = _existing_entry(session, entry_id)

    rows = events.events_for(
        session,
        "entry",
        entry.id,
        newest_first=True,
        limit=HISTORY_PAGE + 1,
        before_id=before,
        # The bookkeeping events (a version snapshotted, the dates
        # re-resolved) always accompany the edit that caused them and say the
        # same thing twice in a list a person reads. They are still in the
        # log, still in /audit, and still replayed: hidden here, not dropped.
        skip_actions=events.QUIET_ACTIONS,
    )
    more = len(rows) > HISTORY_PAGE
    rows = rows[:HISTORY_PAGE]
    # What the note said after each row on *this page*, folded in one
    # ascending pass (`events.states_at`). It was every event of the note
    # hydrated into an ORM object with a whole copy of the note's text kept
    # for each, whichever page was asked for. Measured on this sandbox, on a
    # note with 4,000 events: the newest page 109 ms before against 36 ms
    # after, the oldest page 104 ms against 2.9 ms.
    rebuilt = events.states_at(session, "entry", entry.id, [row.id for row in rows])
    items = []
    for row in rows:
        at_the_time = rebuilt.get(row.id, {})
        items.append(
            {
                "id": row.id,
                "action": row.action,
                "actor": row.actor or events.ACTOR_USER,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
                # Decrypted for display exactly like the note itself, so a
                # private note's history is readable while unlocked and not
                # otherwise.
                "content": _readable(at_the_time.get("content") or ""),
                "tags": at_the_time.get("tags") or [],
                # Whether this event's values were dropped by the compactor
                # (`events.compact`), so the sheet can say "the text from this
                # change is no longer kept" rather than render a row with no
                # text and no reason for it.
                "compacted": events.is_compacted(row),
            }
        )

    return {
        "items": items,
        "next_cursor": rows[-1].id if (more and rows) else None,
        "revisions": [
            {
                "id": revision.id,
                "content": manager.readable_content(revision),
                "tags": json.loads(revision.tags or "[]"),
                "created_at": revision.created_at.isoformat(),
            }
            for revision in manager.revisions_for(session, entry)
        ],
    }


@router.post("/{entry_id}/restore/{event_id}", response_model=EntryOut)
def restore_event(
    entry_id: int, event_id: int, session: Session = Depends(get_session)
) -> EntryOut:
    """Put this note back the way one of its events left it.

    Replay rather than a stored copy: the state after an event is every
    `after` payload up to and including it, applied in order, which is the
    same definition the History sheet shows and the same one a note rebuilt
    from scratch would get. Restoring is itself an edit, so the current text
    is snapshotted first and the restore records its own event: undoing an
    undo has to work, or this is a trap rather than a safety net.
    """
    entry = _existing_entry(session, entry_id)
    row = session.get(AuditLog, event_id)
    if row is None or row.entity_type != "entry" or row.entity_id != entry.id:
        raise HTTPException(status_code=404, detail="That version no longer exists")

    if events.is_compacted(row):
        # Not "did not change the note" and not "does not exist": this event
        # happened, and its text was deliberately dropped to stop the log
        # growing by a copy of the note on every edit (`events.compact`).
        # Gone rather than a bad request, which is what 410 is for.
        raise HTTPException(
            status_code=410,
            detail=(
                "That version is no longer kept: changes older than the "
                "history window keep the record of what happened, not the text"
            ),
        )

    state = events.replay(session, "entry", entry.id, upto_event_id=event_id)
    if "content" not in state and "tags" not in state:
        raise HTTPException(
            status_code=400, detail="That event did not change the note's text"
        )

    manager.record_revision(session, entry)
    if "content" in state:
        entry.content = state["content"]
    if "tags" in state:
        entry.tags = json.dumps(state["tags"])
    manager.log_action(
        session,
        "restored",
        "entry",
        entry.id,
        f"back to event {event_id}",
        payload={
            "from_event": event_id,
            "after": {
                "content": entry.content,
                "tags": manager.tags_from_json(entry.tags),
            },
        },
    )
    session.commit()
    session.refresh(entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/history/{revision_id}/restore", response_model=EntryOut)
def restore_revision(
    entry_id: int, revision_id: int, session: Session = Depends(get_session)
) -> EntryOut:
    """Put a past version back.

    Restoring is itself an edit, so the current text is saved first, undoing
    an undo has to work, or this is a trap rather than a safety net.
    """
    entry = _existing_entry(session, entry_id)
    revision = session.get(EntryRevision, revision_id)
    if revision is None or revision.entry_id != entry.id:
        raise HTTPException(status_code=404, detail="That version no longer exists")

    manager.record_revision(session, entry)
    entry.content = revision.content
    entry.tags = revision.tags
    manager.log_action(session, "edited", "entry", entry.id, "restored an earlier version")
    session.commit()
    session.refresh(entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/privacy", response_model=EntryOut)
def set_entry_privacy(
    entry_id: int, body: PrivacyBody, session: Session = Depends(get_session)
) -> EntryOut:
    """Encrypt this note at rest, or decrypt it again.

    Needs the vault open, which means the app must be unlocked, the data key
    only exists in memory while it is.
    """
    entry = _existing_entry(session, entry_id)
    if not manager.set_private(session, entry, body.private):
        raise HTTPException(
            status_code=409,
            detail="Unlock the app first, the encryption key isn't loaded.",
        )
    session.commit()
    session.refresh(entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/generate-title", response_model=EntryOut)
def generate_entry_title(
    entry_id: int, session: Session = Depends(get_session)
) -> EntryOut:
    """Write a title for this note with AI, on request.

    Recognising a title the user already wrote (`manager.extract_title`) is
    free; writing one is a real model call, so this is its own opt-in
    action rather than something that runs on every save. Replaces an
    existing title rather than stacking a second heading on top of it.
    """
    entry = _existing_entry(session, entry_id)
    # `readable_content` decrypts a private note for reading; writing that
    # decrypted text straight back to `entry.content` (below) would silently
    # replace the ciphertext with plaintext, the note would stop being
    # private as a side effect of titling it. Refused outright rather than
    # risked: unlike a plain edit, there's no form here the user reviewed
    # before it reached the server.
    if entry.is_private:
        raise HTTPException(
            status_code=400, detail="Make this note readable first, private notes can't be re-titled here."
        )
    content = manager.readable_content(entry)
    if not content.strip():
        raise HTTPException(status_code=400, detail="There's no text to title yet.")
    if not deps.get_ollama().is_running():
        raise HTTPException(
            status_code=503,
            detail="The AI isn't available right now (Ollama doesn't seem to be running).",
        )
    try:
        title = librarian.generate_title(content, deps.get_model_manager(), deps.get_ollama())
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not title:
        raise HTTPException(status_code=502, detail="The AI didn't return a usable title.")

    manager.record_revision(session, entry)
    entry.content = manager.apply_title(content, title)
    manager.log_action(session, "edited", "entry", entry.id, f"generated title: {title}")
    session.commit()
    session.refresh(entry)
    return _to_out(session, entry)


@router.post("/{entry_id}/remove-title", response_model=EntryOut)
def remove_entry_title(entry_id: int, session: Session = Depends(get_session)) -> EntryOut:
    """Take a note's title back out, asked for directly. Just the leading
    heading line; a note with no title is returned unchanged rather than
    treated as an error, since the client only offers this action when
    `entry.title` is already set and a stale menu shouldn't 400."""
    entry = _existing_entry(session, entry_id)
    # Same reason as generate-title: writing decrypted text back to
    # `entry.content` would un-encrypt the note as a side effect.
    if entry.is_private:
        raise HTTPException(
            status_code=400, detail="Make this note readable first, private notes can't be edited here."
        )
    content = manager.readable_content(entry)
    stripped = manager.remove_title(content)
    if stripped != content:
        manager.record_revision(session, entry)
        entry.content = stripped
        manager.log_action(session, "edited", "entry", entry.id, "removed the title")
        session.commit()
        session.refresh(entry)
    return _to_out(session, entry)


@router.get("/{entry_id}/connections")
def entry_connections(entry_id: int, session: Session = Depends(get_session)) -> dict:
    """Everything this note is joined to, in one place and grouped by kind.

    Asked for by way of Kortex's Connections block: *"I should be able to
    seamlessly utilise, flick, link, manage, create and search between
    multiple features"*. Every one of these joins already existed in the
    database: `EntryLink` both ways, `DocumentLink`, `WhiteboardNode`,
    `/media/<name>` references in the body, but each was surfaced (if at
    all) somewhere different: links as chips on the card, documents as a
    separate list, boards nowhere at all. A note could be on three boards
    and referenced by two documents and show none of it.

    Direction is kept, not merged. "This note points at that one" and "that
    one points at this" are different facts, and a merged list can state
    neither.
    """
    entry = _existing_entry(session, entry_id)
    outgoing: list[dict] = []
    incoming: list[dict] = []
    for link, other in manager.links_for_entry(session, entry):
        if other.is_deleted:
            continue
        row = {
            "link_id": link.id,
            "id": other.id,
            # A private note's text never leaves the vault for a list like
            # this: the *fact* of the connection is not secret, its content
            # is. Same rule as the Library's own file-usage chips.
            "preview": (
                "Private note" if other.is_private else _connection_label(other)
            ),
            "is_private": bool(other.is_private),
            "reason": link.reason,
            "reason_confidence": link.reason_confidence,
        }
        (outgoing if link.source_entry_id == entry.id else incoming).append(row)

    documents = [
        {"id": doc.id, "title": doc.title, "file_type": doc.file_type}
        for doc in session.scalars(
            select(Document)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .where(DocumentLink.entry_id == entry.id)
            .order_by(Document.title)
        )
    ]

    # A board is itself a note (`WhiteboardNode.board_id` points at an
    # entry), and `board_id IS NULL` is the unnamed scratch board every
    # notebook starts with: so the title has to be resolved per row rather
    # than joined, and NULL is a real board, not a missing one.
    boards: list[dict] = []
    seen_boards: set[int | None] = set()
    for node in session.scalars(
        select(WhiteboardNode).where(WhiteboardNode.entry_id == entry.id)
    ):
        if node.board_id in seen_boards:
            continue
        seen_boards.add(node.board_id)
        title = "Whiteboard"
        if node.board_id is not None:
            board = session.get(Entry, node.board_id)
            if board is None:
                continue
            title = manager.extract_title(manager.readable_content(board)) or "Untitled board"
        boards.append({"id": node.board_id, "title": title, "node_id": node.id})

    files = _connected_files(session, manager.readable_content(entry))

    return {
        "outgoing": outgoing,
        "incoming": incoming,
        "documents": documents,
        "boards": boards,
        "files": files,
        "total": len(outgoing) + len(incoming) + len(documents) + len(boards) + len(files),
    }


def _connection_label(entry) -> str:  # noqa: ANN001
    """What one note is called on another note's Connections list.

    A note's own leading `# Heading` is what it calls itself, so that is the
    label when it wrote one, `_preview` alone hands back "# Connections probe
    B\noven temperatures", which renders on a single-line row as the hash, the
    title and the first line of the body run together.
    """
    text = manager.readable_content(entry)
    return manager.extract_title(text) or _preview(text, 80)


def _connected_files(session: Session, text: str) -> list[dict]:
    """The uploads a body of markdown actually references, as cards.

    `referenced_names` is the same parse the media garbage collector uses to
    decide what is *not* an orphan, so a file listed here and a file the GC
    spares are guaranteed to be the same set, there is no second regex to
    drift out of step with it.
    """
    from memorymap.core.media_gc import referenced_names

    names = referenced_names(text)
    if not names:
        return []
    rows = session.scalars(select(MediaUpload).where(MediaUpload.filename.in_(names)))
    return [
        {
            "name": media.filename,
            "original_name": media.original_name,
            "url": f"/media/{media.filename}",
            "caption": media.caption or "",
        }
        for media in rows
    ]


@router.post("/{entry_id}/links", response_model=EntryOut)
def create_link(
    entry_id: int, body: LinkBody, session: Session = Depends(get_session)
) -> EntryOut:
    source = _existing_entry(session, entry_id)
    target = _existing_entry(session, body.target_id)
    link = manager.create_link(
        session, source, target, reason=body.reason, link_type=body.link_type
    )
    if link is None:
        # Three refusals share one return value, so the message names the one
        # that actually applies: "already linked" on a draft/note pair would
        # send someone hunting for a link that was never allowed to exist.
        if bool(source.is_draft) != bool(target.is_draft):
            raise HTTPException(
                status_code=400,
                detail="A draft can't be linked to a saved note. Save the draft first.",
            )
        raise HTTPException(
            status_code=400, detail="Already linked (or tried to link an entry to itself)"
        )
    return _to_out(session, source)


@router.delete("/{entry_id}/links/{link_id}", response_model=EntryOut)
def delete_link(
    entry_id: int, link_id: int, session: Session = Depends(get_session)
) -> EntryOut:
    entry = _existing_entry(session, entry_id)
    link = session.get(EntryLink, link_id)
    if link is None or entry.id not in (link.source_entry_id, link.target_entry_id):
        raise HTTPException(status_code=404, detail="Link not found")
    manager.delete_link(session, link)
    return _to_out(session, entry)


@router.put("/{entry_id}/links/{link_id}/reason", response_model=EntryOut)
def update_link_reason(
    entry_id: int, link_id: int, body: LinkReasonBody, session: Session = Depends(get_session)
) -> EntryOut:
    """Add, edit, or clear a link's reason by hand, whether it started
    with none, one somebody typed, or one `create_link` deduced on its own.
    """
    entry = _existing_entry(session, entry_id)
    link = session.get(EntryLink, link_id)
    if link is None or entry.id not in (link.source_entry_id, link.target_entry_id):
        raise HTTPException(status_code=404, detail="Link not found")
    try:
        manager.set_link_reason(session, link, body.reason)
        return _to_out(session, entry)
    except Exception:
        # The exception text can carry paths or content; only the log gets it
        # (see test_removing_a_model_never_returns_the_filesystem_path).
        logger.error("Failed to update link reason", exc_info=True)
        raise HTTPException(status_code=500, detail="Couldn't save that reason.") from None


@router.post("/{entry_id}/links/{link_id}/generate-reason")
def generate_link_reason_endpoint(
    entry_id: int, link_id: int, session: Session = Depends(get_session)
) -> dict:
    """Ask the model to generate a specific reason why these two notes are connected."""
    entry = _existing_entry(session, entry_id)
    link = session.get(EntryLink, link_id)
    if link is None or entry.id not in (link.source_entry_id, link.target_entry_id):
        raise HTTPException(status_code=404, detail="Link not found")

    source = session.get(Entry, link.source_entry_id)
    target = session.get(Entry, link.target_entry_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Notes not found")
    # Same boundary generate-title and remove-title enforce: a private note's
    # decrypted text must never reach the model. Every other AI-facing read
    # path in this codebase (search, embeddings, janitor, chat linking...)
    # excludes is_private notes for the same reason.
    if source.is_private or target.is_private:
        raise HTTPException(
            status_code=400, detail="Make both notes readable first, private notes can't be sent to the AI."
        )

    try:
        reason = librarian.generate_link_reason(
            manager.readable_content(source),
            manager.readable_content(target),
            deps.get_model_manager(),
            deps.get_ollama(),
        )
        return {"reason": reason}
    except Exception:
        logger.error("Failed to generate link reason", exc_info=True)
        raise HTTPException(status_code=500, detail="Couldn't generate a reason right now.") from None


# --- extract notes (BACKLOG.md §62) ------------------------------------------
# Select a block of writing, the Writing Room's draft, a Document's body, or
# several notes' content selected on the whiteboard, and turn it into one or
# several AI-drafted notes, auto-linked with real reasons. Preview first,
# matching `generate_diagram`'s own preview-before-commit convention (see
# `ai.extractor`'s module docstring): nothing is written here until
# `/extract/commit` is called with what the preview actually showed.


class ExtractPreviewBody(BaseModel):
    text: str = Field(min_length=1, max_length=extractor.EXTRACT_MAX_CHARS)
    # A Graph/whiteboard selection's notes-in-context: existing notes this
    # extraction should try to link every new note back to, regardless of
    # how similar the wording is, the user already said they're connected
    # by selecting them together.
    source_entry_ids: list[int] = Field(default_factory=list)


@router.post("/extract/preview")
def extract_preview(body: ExtractPreviewBody, session: Session = Depends(get_session)) -> dict:
    """Propose one or more notes from `body.text`, with the links they'd get
    and why: nothing saved yet. See `ai.extractor.build_extraction`."""
    try:
        return extractor.build_extraction(
            session,
            body.text,
            deps.get_embeddings(),
            deps.get_model_manager(),
            deps.get_ollama(),
            source_entry_ids=body.source_entry_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class ExtractNoteIn(BaseModel):
    """One note from a preview, as the user reviewed it, possibly edited,
    possibly dropped (the caller just omits it) before commit."""

    ref: str = Field(min_length=1, max_length=40)
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=extractor.EXTRACT_MAX_CHARS)
    category: str = Field(default=manager.UNCATEGORISED, max_length=100)
    tags: list[str] = Field(default_factory=list)


class ExtractLinkIn(BaseModel):
    """One proposed link, as shown in the preview. `source_ref`/`target_ref`
    are either `nN` (one of this batch's own notes) or `existing:<id>` (a
    note already in the notebook)."""

    source_ref: str = Field(min_length=1, max_length=48)
    target_ref: str = Field(min_length=1, max_length=48)
    reason: str = Field(min_length=1, max_length=200)


class ExtractCommitBody(BaseModel):
    notes: list[ExtractNoteIn] = Field(min_length=1, max_length=extractor.MAX_EXTRACT_NOTES)
    links: list[ExtractLinkIn] = Field(default_factory=list)
    # When extracting from a Document's body, attach every note created here
    # to it: the same connection `POST /documents/{id}/notes` makes by hand.
    source_document_id: int | None = None


@router.post("/extract/commit", status_code=201)
def extract_commit(body: ExtractCommitBody, session: Session = Depends(get_session)) -> dict:
    """Write exactly what a preview showed (possibly edited, possibly
    trimmed) to the notebook: the notes, then the links between them, 
    `manager.create_link`'s own `reason=` bypasses the generic
    `AUTO_REASON_TEXT` guess entirely, so every link gets the specific
    reason the preview generated for it.
    """
    by_ref: dict[str, Entry] = {}
    created = []
    for note in body.notes:
        if note.ref in by_ref:
            raise HTTPException(status_code=400, detail=f"'{note.ref}' is used by more than one note")
        entry = manager.create_entry(
            session,
            content=note.content,
            category_name=note.category or manager.UNCATEGORISED,
            tags=note.tags,
            # Reviewed (and possibly edited) by the person before it was
            # ever asked to save, the same confidence level a user-filed
            # category gets in `create_entry` above, not the AI's own guess
            # from the preview (which was about the SPLIT, not the filing).
            ai_confidence=100,
        )
        by_ref[note.ref] = entry
        deps.store_quietly(session, entry)
        created.append(entry)

    if body.source_document_id is not None:
        document = session.get(Document, body.source_document_id)
        # A document deleted between preview and commit is skipped rather
        # than refused: the notes are the thing being saved, same reasoning
        # `create_entry`'s own `document_ids` handling already uses.
        if document is not None:
            for entry in created:
                manager.link_document(session, document.id, entry.id)

    links_created = 0
    for link in body.links:
        source = by_ref.get(link.source_ref)
        if source is None:
            continue  # a ref that isn't among the notes just created, ignore rather than fail the whole save
        if link.target_ref.startswith("existing:"):
            try:
                target_id = int(link.target_ref.removeprefix("existing:"))
            except ValueError:
                continue
            target = manager.get_entry(session, target_id)
            if target is None or target.is_deleted:
                continue  # deleted between preview and commit
        else:
            target = by_ref.get(link.target_ref)
            if target is None:
                continue
        if manager.create_link(session, source, target, reason=link.reason) is not None:
            links_created += 1

    return {
        "notes": _to_out_bulk(session, created),
        "links_created": links_created,
    }
