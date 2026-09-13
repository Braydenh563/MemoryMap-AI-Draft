"""Saved chats.

The frontend streams answers via /chat/stream, then records the finished
turn here: keeping the streaming path simple and the history durable.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from memorymap.core import deps
from memorymap.core.database import LIKE_ESCAPE, Conversation, like_escape, utcnow
from memorymap.core.deps import get_session
from memorymap.entry.manager import log_action

router = APIRouter(prefix="/conversations", tags=["conversations"])


class TurnBody(BaseModel):
    question: str = Field(min_length=1)
    answer: str
    thinking: str | None = None
    # Tool-activity chips shown in the bubble, persisted so they
    # survive a reload instead of vanishing. Each item is {label, ok}.
    tools: list[dict] | None = None
    # The agent's work in the order it happened: thinking, tool calls and
    # prose interleaved, so reopening a chat shows the same step-by-step run
    # the user watched live rather than a flattened summary of it. Kept
    # alongside `answer`/`tools` rather than replacing them, so an older saved
    # chat (and any other client) still renders.
    steps: list[dict] | None = Field(default=None, max_length=200)
    # What this answer cost, as the model reported it. Stored per turn so a
    # conversation can show its running total: "how much context am I
    # carrying?" is only answerable per-message today, which is the wrong
    # granularity: the total is what decides whether to start a new chat.
    tokens: int | None = None
    # The whole metadata line, not just its total: which model answered, how
    # long it took, prompt→output counts, how full the window got, whether
    # those counts were measured or estimated.
    #
    # Reported in IDEAS.md as "chat message metadata disappears on reload".
    # `tokens` above is a sum, which is the right shape for the conversation
    # total and the wrong one for the per-message line, you cannot rebuild
    # "3.9k of 8k, 12 tok/s, llama3.2" from a single integer, so on reload the
    # line simply vanished and the chat looked like it had been answered by
    # nothing in particular.
    #
    # A free-form dict rather than a model with fields: it is written by the
    # provider and read by one function in `app.js`, and pinning its shape here
    # would mean a third place to edit every time a provider learns to report
    # something new. Bounded instead by only ever storing what the client sends
    # back from a `stats` event.
    stats: dict | None = None
    # Wall-clock for the whole turn, measured by the client because it is the
    # only thing that saw all of it: the server reports per-round timings, and
    # an agent turn is several rounds plus the tool calls between them.
    elapsed_ms: int | None = None
    # The "N matching notes" disclosure's own data: the same shape the
    # `/chat/stream` "meta" event already carries. Reported: "semantic
    # search results in chat messages keep disappearing and don't persist" -
    # true on every reload, since none of this was ever saved here at all;
    # it only ever existed for the duration of the live stream render.
    raw_results: list[dict] | None = None
    search_mode: str | None = None
    match_info: dict | None = None
    connected_ids: list[int] | None = None
    # The "Grounded in" chips' own data (ai/grounding.py's per-sentence
    # note_id/sentence pairs). Same unfixed-until-now gap as raw_results
    # above, reported separately: reopening a chat, or just leaving the
    # tab, dropped the sources line because nothing here ever stored it.
    sentence_grounding: list[dict] | None = None
    # Which MediaUpload ids this turn actually attached, asked for
    # directly, and load-bearing beyond just redisplaying them on reopen:
    # media_gc.py's orphan scan can only see `/media/…` references inside
    # note, document and whiteboard content, so a sent chat image had no
    # record anywhere that anything still used it. Persisted here so
    # media_gc._referenced_filenames can look conversations up too, instead
    # of "Clean orphaned media" silently deleting a real, sent attachment.
    image_media_ids: list[int] | None = None
    #: Documents this turn attached, a file dropped on the chat that was not
    #: an image is imported into Documents (`POST /documents/import`) rather
    #: than sent as pixels, and until now the message kept no record that it
    #: had happened. Reported as attachments that "arent rendered with the
    #: chat messages… and they arent previewable or quick navigatable to
    #: their stored location in the library or documents": with nothing
    #: stored, there was nothing to render and nowhere to navigate to.
    document_ids: list[int] | None = None
    #: Library files this turn attached, an Attachment row, not a Document
    #: and not a MediaUpload, so it needs its own list for the same reason
    #: `document_ids` does. Without it a reopened conversation showed the
    #: images and documents a question was given and silently dropped the
    #: files, which is the shape this field's two neighbours were both added
    #: to fix.
    file_ids: list[int] | None = None
    #: Notes clipped to this question with the paperclip. Reported: *"if the
    #: user attaches a note to a chat message how does it show that that note
    #: is attached to that message??"*, it did not, anywhere. The ids were
    #: sent to `/chat/stream`, used to build that one prompt, and thrown away:
    #: the bubble showed plain text, and reopening the conversation showed the
    #: same plain text, so the answer's whole basis was invisible after the
    #: fact. Same fix as images and documents above, one release later.
    note_ids: list[int] | None = None
    #: Which mode actually answered this turn, Ask (read-only) or Request
    #: (tools allowed). Reported directly: a conversation can span mode
    #: switches, and each past message should say what answered it, not what
    #: the live #chat-mode-seg toggle happens to show now (ROADMAP §89.4).
    used_tools: bool | None = None


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class PinBody(BaseModel):
    pinned: bool


def _turn_messages(turn: TurnBody) -> list[dict]:
    assistant = {"role": "assistant", "content": turn.answer, "thinking": turn.thinking}
    if turn.tools:
        assistant["tools"] = turn.tools
    if turn.steps:
        assistant["steps"] = turn.steps
    if turn.tokens:
        assistant["tokens"] = turn.tokens
    if turn.stats:
        assistant["stats"] = turn.stats
    if turn.elapsed_ms is not None:
        assistant["elapsed_ms"] = turn.elapsed_ms
    if turn.raw_results:
        assistant["raw_results"] = turn.raw_results
        assistant["search_mode"] = turn.search_mode
        assistant["match_info"] = turn.match_info or {}
        assistant["connected_ids"] = turn.connected_ids or []
    if turn.sentence_grounding:
        assistant["sentence_grounding"] = turn.sentence_grounding
    if turn.used_tools is not None:
        assistant["used_tools"] = turn.used_tools
    user: dict = {"role": "user", "content": turn.question}
    if turn.image_media_ids:
        user["image_media_ids"] = turn.image_media_ids
    if turn.document_ids:
        user["document_ids"] = turn.document_ids
    if turn.file_ids:
        user["file_ids"] = turn.file_ids
    if turn.note_ids:
        user["note_ids"] = turn.note_ids
    return [user, assistant]


def _summary(conversation: Conversation) -> dict:
    messages = json.loads(conversation.messages)
    first_question = next(
        (m.get("content", "") for m in messages if m.get("role") == "user"), ""
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at.isoformat(),
        "turns": len(messages) // 2,
        "pinned": bool(conversation.pinned),
        # A line of the first question, so the list says what a chat was
        # about when its title doesn't.
        "preview": first_question[:120],
        "tokens": sum(int(m.get("tokens") or 0) for m in messages),
        "archived_at": conversation.archived_at.isoformat() if conversation.archived_at else None,
    }


def _existing(session: Session, conversation_id: int) -> Conversation:
    return deps.get_or_404(session, Conversation, conversation_id, "Conversation not found")


def _process_committed_media(session: Session, turn: TurnBody) -> None:
    """A sent chat message is one of the three "committed" moments
    core/media_process.py waits for (asked for directly): an image
    attached to the composer and never sent must not trigger OCR/
    captioning/vision-OCR just for having been uploaded. Keyed off
    `image_media_ids` directly (a conversation's own content is a question
    string, not markdown with an inline `/media/…` reference)."""
    from memorymap.core import media_process

    media_process.process_committed_upload_ids(
        session, deps.get_config().data_dir / "media", turn.image_media_ids or []
    )


def conversation_matches(conversation: Conversation, term: str) -> bool:
    """Does this chat actually mention `term`?

    Not a LIKE against the `messages` column. That column holds JSON, so its
    own keys are searchable text: "tent" is a substring of "content", which
    made every single conversation match. The decoded message text is the
    only thing a user means by "what was said".
    """
    lowered = term.lower()
    if lowered in conversation.title.lower():
        return True
    try:
        messages = json.loads(conversation.messages)
    except ValueError:
        return False
    return any(lowered in str(m.get("content", "")).lower() for m in messages)


#: A page of the chat list, not a ceiling on how many chats a notebook may
#: hold. 200 matches `GET /documents` and `GET /entries`, which are read the
#: same way: a caller that wants all of them asks for the next page until
#: `X-Total-Count` is satisfied (`apiPagedList` in documents.js).
CONVERSATIONS_PAGE_SIZE = 200
MAX_CONVERSATIONS_PAGE = 1000

#: How deep a *search* reads before it answers. The SQL filter over-matches
#: (the messages column is JSON, so its keys are text too), so the real
#: matching happens in Python over what SQL returns, and that is a scan: this
#: is the ceiling on it. High enough that a notebook with a few thousand chats
#: searches all of them, low enough that one request cannot read a table of
#: any size into memory.
SEARCH_SCAN_CAP = 5000


@router.get("")
def list_conversations(
    response: Response,
    q: str = "",
    limit: int = Query(default=CONVERSATIONS_PAGE_SIZE, ge=1, le=MAX_CONVERSATIONS_PAGE),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Pinned first, then most recently used, one page at a time.

    `q` searches titles *and* message text: you remember what you asked
    about far more often than what the chat ended up being called, and
    title-only search can't find that.

    **The cap this replaces made old chats unreachable.** It was a flat
    `.limit(200)` with no offset, so the 201st chat could not be opened from
    the sidebar, and could not be found by searching either, because the
    search filtered *after* the limit: the post-filter ran over the 200 most
    recent rows and everything else was never looked at. Same finding as
    INBOX 117 on documents, reminders and media, one list later.

    The id is a tiebreaker in the ordering for the same reason it is there:
    two chats sharing an `updated_at` could otherwise swap places between two
    pages and hide one of them.
    """
    term = (q or "").strip()
    # Archived chats are kept, but out of the way, same shape as an
    # archived note dropping out of the Notes tab. Reachable via the
    # Library's Shelved filter (routes_library._shelved), not this list.
    live = Conversation.archived_at.is_(None)
    order = (
        Conversation.pinned.desc(),
        Conversation.updated_at.desc(),
        Conversation.id.desc(),
    )

    if not term:
        total = session.scalar(select(func.count(Conversation.id)).where(live)) or 0
        rows = list(
            session.scalars(
                select(Conversation).where(live).order_by(*order).limit(limit).offset(offset)
            )
        )
        response.headers["X-Total-Count"] = str(total)
        return [_summary(c) for c in rows]

    # A cheap SQL prefilter, which over-matches (JSON keys count as text), so
    # everything it returns is then checked properly in Python. The page is
    # taken *after* that check, never before: slicing first is what made the
    # old version answer "nothing found" for a chat it had simply not read.
    like = f"%{like_escape(term)}%"
    candidates = session.scalars(
        select(Conversation)
        .where(
            live,
            Conversation.title.ilike(like, escape=LIKE_ESCAPE)
            | Conversation.messages.ilike(like, escape=LIKE_ESCAPE),
        )
        .order_by(*order)
        .limit(SEARCH_SCAN_CAP)
    )
    matched = [c for c in candidates if conversation_matches(c, term)]
    response.headers["X-Total-Count"] = str(len(matched))
    return [_summary(c) for c in matched[offset : offset + limit]]


@router.put("/{conversation_id}/pin")
def pin_conversation(
    conversation_id: int, body: PinBody, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    # updated_at carries `onupdate=utcnow`, which fires on *any* write to the
    # row: so the obvious `conversation.pinned = …; commit()` also marks the
    # chat as just-used, and unpinning would leave it at the top of the list
    # it was meant to drop back down. Passing the current value explicitly is
    # what suppresses the default: pinning is organising, not using.
    session.execute(
        update(Conversation)
        .where(Conversation.id == conversation.id)
        .values(pinned=body.pinned, updated_at=conversation.updated_at)
    )
    session.commit()
    session.refresh(conversation)
    return _summary(conversation)


@router.put("/{conversation_id}/archive")
def archive_conversation(
    conversation_id: int, session: Session = Depends(get_session)
) -> dict:
    """Kept, but out of the way (BACKLOG §30b's named remaining scope), 
    same shape as `routes_entries.archive_entry`: never deleted, never
    auto-cleared, drops out of the sidebar list and out of the way, still
    reachable from the Library's Shelved filter."""
    conversation = _existing(session, conversation_id)
    if not conversation.archived_at:
        # Same suppression as pinning above: archiving is organising, not
        # using, so `updated_at` must not jump to now.
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(archived_at=utcnow(), updated_at=conversation.updated_at)
        )
        log_action(session, "archived", "conversation", conversation.id)
        session.commit()
        session.refresh(conversation)
    return _summary(conversation)


@router.put("/{conversation_id}/unarchive")
def unarchive_conversation(
    conversation_id: int, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    if conversation.archived_at:
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(archived_at=None, updated_at=conversation.updated_at)
        )
        log_action(session, "unarchived", "conversation", conversation.id)
        session.commit()
        session.refresh(conversation)
    return _summary(conversation)


@router.post("", status_code=201)
def create_conversation(body: TurnBody, session: Session = Depends(get_session)) -> dict:
    """First turn of a new chat, the question becomes the title."""
    title = body.question if len(body.question) <= 60 else body.question[:59] + "…"
    conversation = Conversation(
        title=title, messages=json.dumps(_turn_messages(body))
    )
    session.add(conversation)
    session.flush()
    log_action(session, "created", "conversation", conversation.id)
    session.commit()
    _process_committed_media(session, body)
    return _summary(conversation)


def _hydrate_attachments(session: Session, messages: list[dict]) -> None:
    """Turn the stored id lists into something renderable, in place.

    A message stores ids because ids are what survives a rename and what
    `media_gc` needs. A *bubble* needs a thumbnail, a name, and the caption
    and transcription the app already holds for that picture, so the read
    path resolves them here, once for the whole conversation, rather than
    leaving the browser to fire one request per attachment per reopen.

    **Missing is normal and is not an error.** An attachment can be deleted
    from the Library long after the message that carried it; the id then
    resolves to nothing and the bubble simply shows one fewer thumbnail,
    which is what happened before this existed. Nothing here 404s.
    """
    from memorymap.core.database import Attachment, Document, Entry, MediaUpload

    media_ids = {i for m in messages for i in (m.get("image_media_ids") or [])}
    doc_ids = {i for m in messages for i in (m.get("document_ids") or [])}
    note_ids = {i for m in messages for i in (m.get("note_ids") or [])}
    file_ids = {i for m in messages for i in (m.get("file_ids") or [])}
    if not media_ids and not doc_ids and not note_ids and not file_ids:
        return

    media = {}
    if media_ids:
        for upload in session.query(MediaUpload).filter(MediaUpload.id.in_(media_ids)).all():
            media[upload.id] = {
                "id": upload.id,
                "kind": "image",
                "url": f"/media/{upload.filename}",
                "name": upload.original_name,
                # The two readings the Library tile shows, so the same
                # picture reads the same way wherever it appears.
                "caption": upload.caption or "",
                "text": (upload.vision_ocr_text or upload.ocr_text or "").strip(),
            }
    documents = {}
    if doc_ids:
        for document in session.query(Document).filter(Document.id.in_(doc_ids)).all():
            documents[document.id] = {
                "id": document.id,
                "kind": "document",
                "name": document.title,
            }

    files = {}
    if file_ids:
        for attachment in session.query(Attachment).filter(Attachment.id.in_(file_ids)).all():
            files[attachment.id] = {
                "id": attachment.id,
                "kind": "file",
                "name": attachment.filename,
            }

    notes = {}
    if note_ids:
        for entry in session.query(Entry).filter(Entry.id.in_(note_ids)).all():
            # A binned or private note is treated exactly like a deleted
            # upload: the chip disappears. Listing a private note's first line
            # in a conversation would put it back on screen in the one place
            # the private-notebook rule cannot reach.
            if entry.is_deleted or entry.is_private:
                continue
            first_line = (entry.content or "").strip().splitlines()
            notes[entry.id] = {
                "id": entry.id,
                "kind": "note",
                # Notes have no title of their own, so the chip says what the
                # note says: the same first-line preview the picker uses, for
                # the same reason: it is how the user recognises it.
                "name": (first_line[0][:60] if first_line else f"Note #{entry.id}"),
            }

    for message in messages:
        attachments = [
            media[i] for i in (message.get("image_media_ids") or []) if i in media
        ] + [
            documents[i] for i in (message.get("document_ids") or []) if i in documents
        ] + [
            files[i] for i in (message.get("file_ids") or []) if i in files
        ] + [
            notes[i] for i in (message.get("note_ids") or []) if i in notes
        ]
        if attachments:
            message["attachments"] = attachments


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: int, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    _hydrate_attachments(session, messages)
    return {**_summary(conversation), "messages": messages}


@router.post("/{conversation_id}/turns")
def append_turn(
    conversation_id: int, body: TurnBody, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    messages.extend(_turn_messages(body))
    conversation.messages = json.dumps(messages)
    conversation.updated_at = utcnow()
    session.commit()
    _process_committed_media(session, body)
    return _summary(conversation)


TITLE_PROMPT = (
    "Write a very short title (2 to 5 words) for this conversation. Reply with "
    "the title only: no quotes, no punctuation at the end, no explanation."
)


def _clean_title(raw: str) -> str | None:
    text = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    text = text.strip().strip("\"'`*#").rstrip(".!,;:").strip()
    if not text or len(text) > 60 or len(text.split()) > 8:
        return None
    # Models frequently reply in lowercase, a title should start capitalised.
    return text[0].upper() + text[1:]


@router.post("/{conversation_id}/retitle")
def retitle_conversation(
    conversation_id: int, session: Session = Depends(get_session)
) -> dict:
    """Name a chat with the local model, falling back to the first question.

    Best-effort by design: if the model is down or answers with something
    unusable, the conversation simply keeps a sensible non-AI title.
    """
    from memorymap.ai import librarian
    from memorymap.core import deps

    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    first_question = next(
        (m["content"] for m in messages if m.get("role") == "user"), ""
    )
    fallback = first_question if len(first_question) <= 60 else first_question[:59] + "…"

    title = None
    ollama = deps.get_ollama()
    if ollama.is_running():
        # A short transcript is plenty to name the thread.
        transcript = "\n".join(
            f"{m.get('role')}: {str(m.get('content'))[:400]}" for m in messages[:4]
        )
        # Name it in the active persona's voice, so titles match the
        # assistant the user actually chose.
        persona = librarian.resolve_persona_prompt(None, deps.get_config())
        system = f"{persona.strip()} {TITLE_PROMPT}" if persona else TITLE_PROMPT
        try:
            reply = ollama.chat(
                deps.get_model_manager().utility_model(),
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": transcript},
                ],
            )
            title = _clean_title(reply.get("content", "") if isinstance(reply, dict) else "")
        except Exception:  # noqa: BLE001  # a failed rename is never fatal
            title = None

    conversation.title = title or fallback or conversation.title
    conversation.updated_at = utcnow()
    session.commit()
    return {**_summary(conversation), "ai_named": bool(title)}


@router.put("/{conversation_id}/turns/last")
def replace_last_turn(
    conversation_id: int, body: TurnBody, session: Session = Depends(get_session)
) -> dict:
    """Regenerate: swap the most recent Q&A pair for a fresh answer, in
    place, instead of appending a duplicate below it (user request)."""
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    if len(messages) >= 2:
        messages = messages[:-2]  # drop the last user+assistant pair
    messages.extend(_turn_messages(body))
    conversation.messages = json.dumps(messages)
    conversation.updated_at = utcnow()
    session.commit()
    _process_committed_media(session, body)
    return _summary(conversation)


@router.delete("/{conversation_id}/turns/{index}")
def delete_turn(
    conversation_id: int, index: int, session: Session = Depends(get_session)
) -> dict:
    """Remove a single question/answer exchange (a turn) from a saved chat.

    Messages are stored as flat user/assistant pairs, so turn `index` maps to
    messages[2*index : 2*index+2]. Deleting the last remaining turn removes the
    conversation itself, since an empty chat is only clutter.
    """
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    start = index * 2
    if index < 0 or start >= len(messages):
        raise HTTPException(status_code=404, detail="Turn not found")
    del messages[start : start + 2]
    if not messages:
        log_action(session, "deleted", "conversation", conversation.id)
        session.delete(conversation)
        session.commit()
        return {"deleted": True, "conversation_deleted": True, "turns": 0}
    conversation.messages = json.dumps(messages)
    conversation.updated_at = utcnow()
    session.commit()
    return {**_summary(conversation), "deleted": True, "conversation_deleted": False}


class TruncateBody(BaseModel):
    """Drop this turn and everything after it."""

    from_turn: int = Field(ge=0)


@router.post("/{conversation_id}/truncate")
def truncate_conversation(
    conversation_id: int, body: TruncateBody, session: Session = Depends(get_session)
) -> dict:
    """Cut the conversation back to just before `from_turn`.

    This is what editing a question needs: the answers that followed it were
    replies to the old wording, so leaving them would make the thread read as
    though the assistant answered a question nobody asked.
    """
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    keep = messages[: body.from_turn * 2]
    if len(keep) == len(messages):
        return {**_summary(conversation), "removed": 0}

    removed = (len(messages) - len(keep)) // 2
    if not keep:
        log_action(session, "deleted", "conversation", conversation.id)
        session.delete(conversation)
        session.commit()
        return {"removed": removed, "conversation_deleted": True, "turns": 0}

    conversation.messages = json.dumps(keep)
    conversation.updated_at = utcnow()
    session.commit()
    return {**_summary(conversation), "removed": removed, "conversation_deleted": False}


class ForkBody(BaseModel):
    """Where to cut the copy. Omitted means the whole conversation."""

    #: The turn to keep *up to and including*. Same indexing `truncate` uses: 
    #: one turn is a user message and its answer, so the message slice is
    #: `(up_to + 1) * 2`. `None` means "all of it", which is the plain
    #: duplicate case.
    up_to: int | None = None
    title: str | None = Field(default=None, max_length=120)


@router.post("/{conversation_id}/fork", status_code=201)
def fork_conversation(
    conversation_id: int, body: ForkBody, session: Session = Depends(get_session)
) -> dict:
    """Copy a conversation, optionally only as far as one turn.

    Asked for directly: *"ability to fork conversations"*. The need is the one
    every chat interface eventually grows: a thread reaches a good state and
    you want to try a different direction **without losing the one you have**.
    Today the only way is to keep asking and then delete what you did not
    want, which is destructive and cannot be undone.

    A copy rather than a branch pointer, deliberately. Conversations here are
    one JSON blob per row (see `Conversation`'s own docstring on why that is
    the right size for a single-user app), and a real branch would mean
    turning that into a tree with shared ancestry, a merge story and a
    migration: an enormous amount of machinery so that two threads can share
    the bytes of the first three messages. Copying is O(one chat) of disk and
    behaves exactly as a reader expects: the fork is a normal conversation
    from the moment it exists, and editing it cannot reach back into its
    parent.
    """
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    if body.up_to is not None:
        #: `max(0, …)` rather than refusing a negative: a fork with nothing in
        #: it is a new chat, which is a reasonable thing to have asked for and
        #: a silly thing to return an error about.
        messages = messages[: max(0, (body.up_to + 1) * 2)]
    #: The name says where it came from, because a Library listing two
    #: identically-named chats is the thing that makes forking unusable.
    title = (body.title or "").strip() or f"{conversation.title} (fork)"
    fork = Conversation(
        title=title[:120],
        messages=json.dumps(messages),
        workspace_id=conversation.workspace_id,
    )
    session.add(fork)
    session.commit()
    log_action(session, "created", "conversation", fork.id)
    return _summary(fork)


class FollowupsBody(BaseModel):
    """The "what to ask next" chips a finished turn produced."""

    #: Bounded on both axes: these are one row of buttons under an answer, and
    #: a body that arrives with two hundred of them is a bug or an attack, not
    #: a longer list of good questions.
    followups: list[str] = Field(default_factory=list, max_length=6)


@router.put("/{conversation_id}/turns/{index}/followups")
def set_turn_followups(
    conversation_id: int,
    index: int,
    body: FollowupsBody,
    session: Session = Depends(get_session),
) -> dict:
    """Remember the follow-up chips for one turn.

    Reported directly: "suggested repsponse continuation prompts in chat doesnt
    persist and disappears once I switch chat sessions or quit the app." They
    did not persist because nothing ever stored them, they were generated by
    a second model call after the turn was already saved, appended to a live
    DOM node, and that was the whole of their existence.

    Its own endpoint rather than a field on the turn body, because of *when*
    it happens: the turn is written the moment the answer finishes, and the
    suggestions arrive after that, deliberately (they are a second model call
    and must never delay the answer). A turn that has since been deleted is a
    204-shaped no-op, not an error, the reader moved on, which is fine.
    """
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    position = index * 2 + 1  # the assistant half of the pair
    if position >= len(messages) or messages[position].get("role") != "assistant":
        return {"saved": False}

    cleaned = [text.strip()[:200] for text in body.followups if text.strip()]
    if cleaned:
        messages[position]["followups"] = cleaned
    else:
        messages[position].pop("followups", None)
    # `updated_at` is deliberately held where it was, and holding it takes an
    # explicit assignment, because the column carries `onupdate=utcnow` and
    # would otherwise move on any UPDATE at all. A suggestion the user has not
    # read is not activity: bumping it would reshuffle the chat list under
    # them seconds after they stopped reading, which is exactly the kind of
    # thing that makes a sidebar feel unstable for no reason anyone can see.
    # A Core UPDATE naming both columns, not `conversation.messages = …`.
    # Assigning the same `updated_at` back through the ORM does nothing: it is
    # not a change, so the column is left out of the SET clause and `onupdate`
    # fills it in: which is the behaviour being avoided. `values()` puts it in
    # the statement explicitly, and an explicit value beats `onupdate`.
    session.execute(
        update(Conversation)
        .where(Conversation.id == conversation.id)
        .values(messages=json.dumps(messages), updated_at=conversation.updated_at)
    )
    session.commit()
    return {"saved": True, "followups": cleaned}


class AnswerBody(BaseModel):
    content: str = Field(min_length=1)


def _rewrite_answer_steps(steps: list[dict] | None, content: str) -> list[dict] | None:
    """Point a saved step timeline at an edited answer.

    `steps` carries its own copy of the prose, and it is the copy the client
    actually renders when reopening a chat, `content` is only used for the
    copy button. So editing `content` alone left the edit invisible the moment
    the chat was reopened: replay redrew the model's original wording and the
    correction looked like it had never been saved.

    The reasoning and tool steps are deliberately left alone. They record what
    the model actually did, which the user's correction doesn't change. Only
    the prose is theirs to rewrite, so the answer steps collapse into the one
    block they typed: the same shape the frontend produces when it edits a
    timeline in place.
    """
    if not steps:
        return steps
    out: list[dict] = []
    written = False
    for step in steps:
        if step.get("kind") != "answer":
            out.append(step)
            continue
        if written:
            continue  # a second prose block would duplicate the correction
        out.append({**step, "text": content})
        written = True
    if not written:
        # A turn whose timeline held only reasoning and tools still needs the
        # edited prose, or replay would render no answer at all.
        out.append({"kind": "answer", "text": content})
    return out


@router.put("/{conversation_id}/turns/{index}/answer")
def edit_answer(
    conversation_id: int,
    index: int,
    body: AnswerBody,
    session: Session = Depends(get_session),
) -> dict:
    """Edit the assistant's text of one turn, keeping everything else.

    Questions have been editable for a while; answers weren't, so the only
    way to fix a model's near-miss was to regenerate and hope. An edited
    answer is marked so the transcript never passes your words off as the
    model's: that distinction is the whole point of keeping a transcript.
    """
    conversation = _existing(session, conversation_id)
    messages = json.loads(conversation.messages)
    position = index * 2 + 1  # user, assistant, user, assistant, …
    if index < 0 or position >= len(messages):
        raise HTTPException(status_code=404, detail="Turn not found")
    messages[position]["content"] = body.content
    messages[position]["edited"] = True
    steps = _rewrite_answer_steps(messages[position].get("steps"), body.content)
    if steps:
        messages[position]["steps"] = steps
    conversation.messages = json.dumps(messages)
    conversation.updated_at = utcnow()
    session.commit()
    return {**_summary(conversation), "edited_turn": index}


@router.put("/{conversation_id}")
def rename_conversation(
    conversation_id: int, body: RenameBody, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    conversation.title = body.title
    session.commit()
    return _summary(conversation)


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int, session: Session = Depends(get_session)
) -> dict:
    conversation = _existing(session, conversation_id)
    log_action(session, "deleted", "conversation", conversation.id)
    session.delete(conversation)
    session.commit()
    return {"deleted": True}
