"""The link-reason audit: rewrites vague link reasons into specific ones.

`entry.manager.create_link` only ever gives a fresh link the generic
`AUTO_REASON_TEXT` ("similar in meaning"), deliberately, so creating a link
never stalls on a chat round-trip (see `manager._deduce_reason`). This module
is the other half: a background pass, run from `ai.autonomous` and offered as
the `audit_link_reasons` tool (`ai.tools`), that goes back over those links
and asks the model to name the *specific* thing connecting the two notes, 
"both mention the Denver move", not "similar in meaning" again.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from memorymap.ai import librarian, model_manager, ollama_client
from memorymap.core.database import Entry, EntryLink
from memorymap.entry import manager

logger = logging.getLogger("memorymap.ai.links")

# A reason this vague is exactly the complaint being fixed, it names no
# concrete project, person, place, tool, decision or date, just asserts that
# a connection exists. `librarian.generate_link_reason`'s prompt already asks
# the model not to write these, but a small/rushed model sometimes does
# anyway, so a reply containing one of these is rejected here rather than
# trusted. Substring match on purpose: it catches "they are both related to
# each other" as readily as the bare phrase, without needing every possible
# wording spelled out.
VAGUE_PHRASES = (
    "similar in meaning",
    "related to each other",
    "they are related",
    "they relate",
    "same topic",
    "related topics",
    "conceptually related",
    "conceptually linked",
    "connected to each other",
    "share a topic",
    "share similar",
    "similar topics",
    "similar content",
)
# Deliberately NOT here: "both mention"/"both discuss"/"both about" on their
# own. Those prefixes are how a genuinely specific reason often starts, 
# `librarian.generate_link_reason`'s own "good" examples are "both about the
# Denver move" and "both mention Sarah", so banning the prefix would reject
# the shape of answer the prompt is asking for. What made the *old* prompt's
# examples vague was the generic object after the prefix ("studying
# techniques"), not the prefix itself, and there is no reliable way to
# denylist "too generic a noun phrase" the way a fixed phrase can be.

#: A reason longer than this reads as a sentence, not a label, capped so a
#: model that ignores the "3 to 8 words" instruction can't turn a link's
#: tooltip into a paragraph.
MAX_REASON_CHARS = 80

#: How many times a link may fail (raise, or come back empty/vague) in this
#: process's lifetime before the audit stops retrying it. Without this, a
#: link that fails for a structural reason, a note whose content trips the
#: model every time, say, matches `audit_vague_links`'s own WHERE clause
#: forever (nothing about a failed attempt changes `reason` or
#: `reason_confidence`), so every future pass would ask the model about it
#: again. `autonomous.py` runs this every few hours for as long as the
#: server is up, so "every pass" is not hypothetical.
#:
#: Tracked in memory rather than as a DB column: this is a small, local
#: safety valve, not a fact worth a migration, and a process restart is
#: already a reasonable place to let a link have another go.
MAX_ATTEMPTS_PER_PROCESS = 3

#: link id -> attempts made this process that did not produce a usable
#: reason (an exception, an empty reply, or a reply rejected as vague).
_failed_attempts: dict[int, int] = {}


def _is_vague_reason(reason: str) -> bool:
    """Would storing this reason just replace one vague phrasing with
    another?"""
    lowered = reason.strip().lower()
    if not lowered:
        return True
    return any(phrase in lowered for phrase in VAGUE_PHRASES)


def _clean_reason(raw: str) -> str:
    """A model's reply, trimmed to something safe to store: no wrapping
    quotes, no trailing punctuation, capped at `MAX_REASON_CHARS`."""
    reason = raw.strip().strip("\"'“”‘’").strip()
    reason = reason.rstrip(" .,;:!-")
    return reason[:MAX_REASON_CHARS].strip()


def audit_vague_links(
    session, model: model_manager.ModelManager, ollama: ollama_client.OllamaClient, limit: int = 50
) -> int:
    """Rewrite up to `limit` vague-or-guessed link reasons with a specific
    one, using the AI. Returns how many were actually rewritten.

    Finds links whose reason is still the literal `manager.AUTO_REASON_TEXT`
    or whose `reason_confidence` is set (meaning it was guessed from
    embedding similarity, never put into words), the two shapes
    `manager._deduce_reason` can leave behind. For each, asks the model to
    name the specific connection; a reply that fails, comes back empty, or is
    itself vague leaves the link exactly as it was rather than writing junk
    over it (see `_is_vague_reason`), "still a guess" is a more honest state
    than a confident-looking sentence that says nothing.

    A single commit and a single audit-log row cover the whole batch, see
    `manager.apply_audited_reason` for why a per-link commit and log row
    (what `manager.set_link_reason` does, correctly, for a human editing one
    link by hand) would be wrong here.
    """
    stmt = (
        select(EntryLink)
        .where(
            (EntryLink.reason == manager.AUTO_REASON_TEXT)
            | (EntryLink.reason_confidence.is_not(None))
        )
        .limit(limit)
    )
    links = session.scalars(stmt).all()
    if not links:
        return 0

    updated_count = 0

    for link in links:
        if _failed_attempts.get(link.id, 0) >= MAX_ATTEMPTS_PER_PROCESS:
            continue

        source = session.get(Entry, link.source_entry_id)
        target = session.get(Entry, link.target_entry_id)
        if not source or not target:
            continue
        # A note can be marked private *after* it was linked to another one, 
        # `manager.set_private` drops the note's embedding and resolved dates
        # for exactly this reason, but leaves the link itself in place, so
        # this WHERE clause can still hand back a link touching a private
        # note. `source.content`/`target.content` below is ciphertext at rest
        # for a private note, and sending it to the model would be the same
        # leak `_link_notes`'s own guard exists to prevent on the write side.
        # Skipped rather than retried: nothing about the note becoming
        # private again is fixable by asking the model again later, so this
        # does not count against `_failed_attempts`, the same "never retry
        # a hopeless case" idea, without the process-lifetime bookkeeping,
        # since going private is rare enough that it isn't worth spending it.
        if source.is_private or target.is_private:
            continue

        try:
            reply = librarian.generate_link_reason(source.content, target.content, model, ollama)
        except Exception as exc:
            _failed_attempts[link.id] = _failed_attempts.get(link.id, 0) + 1
            logger.warning("Failed to audit link reason for link %s: %s", link.id, exc)
            continue

        reason = _clean_reason(reply)
        if not reason or _is_vague_reason(reason):
            _failed_attempts[link.id] = _failed_attempts.get(link.id, 0) + 1
            logger.info(
                "link %s: model reply was empty or vague (%r), leaving unchanged",
                link.id,
                reply,
            )
            continue

        manager.apply_audited_reason(link, reason)
        updated_count += 1
        # A link that got a usable reason no longer matches the WHERE clause
        # above (its reason_confidence is cleared and its reason is no
        # longer AUTO_REASON_TEXT), so it will never be reconsidered, no
        # need to keep its entry in `_failed_attempts` either.
        _failed_attempts.pop(link.id, None)

    if updated_count:
        manager.log_action(
            session, "audited", "entry", detail=f"audited {updated_count} link reason(s)"
        )
        session.commit()

    return updated_count
