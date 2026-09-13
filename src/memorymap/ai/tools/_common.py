"""Shared plumbing for every tool module in this package: the error type,
the tool-spec shape, and the context-budget/lookup helpers every domain
module needs (`_require_note`, `_visible`, `_note_summary`, ...).

Split out of what used to be one 4,240-line `ai/tools.py` (ROADMAP.md §0/§4)
- every handler used to live in one file with these helpers at the top;
they're the one piece every domain module below depends on, so they had to
land somewhere with no dependency back on any of them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core import deps
from memorymap.core.database import EmbeddingRecord, Entry
from memorymap.entry import manager

__all__ = [
    "ToolError",
    "ToolSpec",
    "PREVIEW_CHARS",
    "FULL_NOTE_CHARS",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "DEFAULT_CONTEXT_TOKENS",
    "SEARCH_CONTEXT_SHARE",
    "SUMMARY_NOTE_LIMIT",
    "DOCUMENT_CHARS",
    "_clip",
    "_visible",
    "_readable",
    "_note_summary",
    "_undo_edit",
    "_require_note",
    "_READ_MORE",
    "_limit_arg",
    "_category_clause",
    "_since_days",
    "_refresh_embedding",
    "_keyword_context",
]


class ToolError(ValueError):
    """A failure a tool means to explain, in words written for a reader.

    Every handler below raises this for the cases it anticipates, "there's no
    note with that id", "that tag is already in use". Those strings are safe to
    hand to the model and to show in the UI, because somebody wrote them for
    exactly that.

    A bare `ValueError` from somewhere inside a handler is the opposite: it is
    whatever `int("abc")` or a SQLAlchemy coercion happened to say, and its text
    is an internal detail. `execute_tool` distinguishes the two, which a single
    `except ValueError` could not. Subclassing `ValueError` keeps every existing
    caller that catches the base class working unchanged.
    """


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema for the arguments
    handler: Callable[[Session, dict], dict]
    destructive: bool = False
    #: This tool's whole effect is to stop and wait for the user, so the agent
    #: loop ends the turn on it rather than feeding a result back and carrying
    #: on. `ask_user`, `run_skill`, `make_plan` and `compress_chat` all set
    #: this, and the flag exists rather than a name check so the loop reads
    #: as "why" instead of "which" (§33).
    ends_turn: bool = False


# --- context budget -------------------------------------------------------------
# A local model's window is small and a notebook is not. These caps are the
# whole reason the reading tools below are safe to hand to a model: without
# them, one `list_notes` on a 5,000-note notebook would push everything else, 
# the question included: out of the window.
#
# The rule: list calls return *previews* and say when they were capped, so the
# model pages deliberately instead of silently seeing a truncated notebook.
# Full text costs a `get_note` call, one note at a time.

PREVIEW_CHARS = 200
FULL_NOTE_CHARS = 4_000
DEFAULT_LIST_LIMIT = 10
MAX_LIST_LIMIT = 25

#: What `search_notes` assumes when the caller could not report a real window.
DEFAULT_CONTEXT_TOKENS = 4_096

#: The share of the model's window one search may fill by default. Only the
#: default scales with the window, `MAX_LIST_LIMIT` still caps the result.
SEARCH_CONTEXT_SHARE = 0.15
SUMMARY_NOTE_LIMIT = 40
# Documents are long-form by definition, so they get a larger ceiling than a
# note: but still a ceiling: one document must not fill the whole window.
DOCUMENT_CHARS = 12_000


def _clip(text: str, length: int = 300) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


#: How much text either side of a keyword hit travels with it. Enough that a
#: sentence has room either side of the word that matched; the selection
#: toolbar's own "how much travels with the selection" note (documents.js)
#: uses the same reasoning for the same reason, a hit with no surroundings
#: answers "is the word here" and not "what does it say here".
_KEYWORD_CONTEXT_RADIUS = 200

#: How many separate hits one call surfaces. A word that appears fifty times
#: in a long document is not usefully described by fifty snippets; three
#: locations is enough to show the model the shape of where it appears and
#: cheap enough that a caller can always ask read_document/read_file again
#: with a narrower query for one of them specifically.
_KEYWORD_CONTEXT_MAX_HITS = 3


def _keyword_context(
    text: str,
    needle: str,
    *,
    radius: int = _KEYWORD_CONTEXT_RADIUS,
    max_hits: int = _KEYWORD_CONTEXT_MAX_HITS,
    length: int = 0,
) -> str:
    """The text *around* where `needle` actually appears, not the start of
    the document: asked for directly, and a real gap rather than a
    misunderstanding of one that already existed: *"if the ai is searching
    for something, might keywords be flagged in certain pages of a file
    document in the actual document and/or extracted text, then it can use
    a tool or smth simpler to get the full text from those areas."*

    Before this, every search-result preview and every plain (no-embeddings)
    document/file read clipped from the *start* of the text, `_clip(text,
    N)`, regardless of where a match actually was. `_matches`/`ILIKE`
    correctly finds a document because the word is in it somewhere; the
    preview it hands the model is the document's opening paragraph, which,
    fifty pages away from the actual hit, may share nothing with it at all.
    `read_file`'s own full-text cap (`FILE_TEXT_CHARS = 2000`) makes this
    concrete: a vision-OCR'd multi-page scan easily runs past that from page
    two onward, so a keyword on page five was never reachable through this
    tool at all, however precisely `search_files` had already located it.

    Case-insensitive, matches merged when their windows overlap (a phrase
    that recurs two sentences apart reads as one passage, not two identical
    fragments with a gap between). Falls back to a plain head-of-text clip
    - `_clip`'s existing behaviour: when there is no needle or no match, so
    every caller can pass a query unconditionally and a document with none
    of the words in it still returns something rather than nothing.
    """
    cap = length or radius * (2 * max_hits + 1)
    plain = (needle or "").strip()
    if not plain:
        return _clip(text, cap)
    hay = text.lower()
    term = plain.lower()
    spans: list[tuple[int, int]] = []
    start = 0
    while len(spans) < max_hits:
        at = hay.find(term, start)
        if at == -1:
            break
        spans.append((max(0, at - radius), min(len(text), at + len(term) + radius)))
        start = at + len(term)
    if not spans:
        return _clip(text, cap)
    # Merge windows that overlap or sit back-to-back, so a term that recurs
    # close together reads as one continuous passage rather than two
    # snippets duplicating their middle.
    spans.sort()
    merged: list[list[int]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    parts = []
    for lo, hi in merged:
        piece = text[lo:hi].strip()
        prefix = "…" if lo > 0 else ""
        suffix = "…" if hi < len(text) else ""
        parts.append(f"{prefix}{piece}{suffix}")
    return "\n\n".join(parts)


def _visible(*extra):
    """The where-clause every reading tool starts from.

    Private notes are excluded here, once, rather than in each handler, 
    the same reasoning as `manager.readable_content`: a rule applied in one
    place can't be forgotten in the next path someone adds. A private note is
    kept out of retrieval (`search_manager._without_private`), so it must be
    kept out of the tools too, or the model reaches around the front door.
    """
    return (
        Entry.is_deleted == False,  # noqa: E712
        Entry.is_private == False,  # noqa: E712
        *extra,
    )


def _readable(entry: Entry) -> str:
    """Non-private notes are stored in the clear, but go through the manager
    anyway so this can never be the path that hands back ciphertext."""
    return manager.readable_content(entry)


def _note_summary(
    session: Session, entry: Entry, chars: int = PREVIEW_CHARS, dates: list | None = None
) -> dict:
    """What the model gets back about a note, enough to talk about it
    and to reference it in follow-up tool calls.

    `dates` lets a caller looping over many rows (`list_notes`,
    `_summarize_notes`) pass in a pre-fetched, batched lookup instead of
    paying one `entry_dates` query per row: the N+1 ROADMAP.md Tier 1 item
    8 named. Left `None` for the single-note callers, which still fetch it
    themselves below.
    """
    text = _readable(entry)
    clipped = _clip(text, chars)
    summary = {
        "id": entry.id,
        "content": clipped,
        "truncated": len(clipped) < len(text),
        "category": manager.category_name_for(session, entry),
        "tags": manager.entry_tags(entry),
        "pinned": entry.pinned,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }
    # What the note's own "tomorrow" meant on the day it was written (§10A).
    # Without this the model reads "the deadline is next Friday" in a note
    # from March and answers about the Friday coming up.
    if dates is None:
        dates = manager.entry_dates(session, entry)
    if dates:
        summary["dates"] = [
            {"phrase": d.phrase, "meant": d.at.date().isoformat()} for d in dates
        ]
    return summary


def _undo_edit(session: Session, entry: Entry) -> dict:
    """The call that would put this note back the way it is right now.

    Captured *before* a write, and expressed as a tool call rather than a
    special-case endpoint: the UI hands it straight back to
    `POST /chat/tools/execute`, which is the same path the confirm button
    already uses. Roadmap §21 asks a skill to end in "a list the user can
    undo, rather than prose claiming something happened", this is the half
    that makes the list actionable.
    """
    return {
        "tool": "edit_note",
        "arguments": {
            "note_id": entry.id,
            "content": entry.content,
            "category": manager.category_name_for(session, entry),
            "tags": manager.entry_tags(entry),
        },
    }


def _require_note(session: Session, args: dict, field: str = "note_id") -> Entry:
    entry = manager.get_entry(session, int(args[field]))
    if entry is None or entry.is_deleted:
        raise ToolError(f"No note with id {args.get(field)}")
    if entry.is_private:
        # Deliberately the same wording as a missing note in spirit, but
        # honest about why: the model should tell the user it can't see it,
        # not invent contents for it.
        raise ToolError(
            f"Note #{entry.id} is private, so it isn't available to the AI"
        )
    return entry


# Said on every list result. The model has no other way to know that what it
# is looking at is an excerpt, and a model that doesn't know will answer from
# half a note without hedging.
_READ_MORE = (
    f"These are previews, clipped to about {PREVIEW_CHARS} characters. "
    "Call get_note with a note's id to read it in full before quoting it."
)


def _limit_arg(args: dict, default: int, max_limit: int = MAX_LIST_LIMIT) -> int:
    """Clamp whatever the model asked for into the budget. A model that asks
    for 500 notes gets max_limit and is told so by `has_more`."""
    try:
        wanted = int(args.get("limit") or default)
    except (TypeError, ValueError):
        wanted = default
    return max(1, min(wanted, max_limit))


def _category_clause(session: Session, name: str):
    """Match a category by name, case-insensitively, without a join.

    An unknown name deliberately matches nothing rather than everything: the
    honest answer to "notes in Recipes" when there is no Recipes is zero.
    """
    from memorymap.core.database import Category

    category_id = session.scalar(
        select(Category.id).where(func.lower(Category.name) == name.lower())
    )
    if category_id is None:
        if name == manager.UNCATEGORISED:
            return Entry.category_id.is_(None)
        return Entry.id.is_(None)  # matches nothing
    return Entry.category_id == category_id


def _since_days(value) -> int | None:
    """`since` accepts a number of days ("7") or an ISO date ("2026-07-01").

    Models are inconsistent about which they send, and a tool that rejects one
    of them just burns a round. Anything unparseable means "no time filter"
    rather than an error, the same call, wider, beats no answer.
    """
    if value in (None, ""):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        pass
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    days = (datetime.now(tz=when.tzinfo) - when).days
    return max(0, days)


def _refresh_embedding(session: Session, entry: Entry) -> None:
    """Content changed → the old vector is stale. Best effort, exactly
    like the entries routes: a failed embed never fails the change, 
    but it does get logged, so a backend that has stopped working is
    visible in Settings → Logs instead of silently degrading search."""
    try:
        session.execute(
            EmbeddingRecord.__table__.delete().where(
                EmbeddingRecord.entry_id == entry.id
            )
        )
        session.commit()
    except Exception as e:
        # Avoid catching BaseException (KeyboardInterrupt, SystemExit).
        # We catch Exception here because the embedding refresh touches both
        # DB (SQLAlchemyError) and potentially file/network (depending on backend).
        logging.getLogger("memorymap.embeddings").warning(
            "couldn't clear the stale vector for entry %s: %s", entry.id, e, exc_info=True
        )
        session.rollback()
        return
    deps.store_quietly(session, entry)

