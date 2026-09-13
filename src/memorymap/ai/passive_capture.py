"""Turn an offhand mention in ordinary chat into a note you can review.

**The one real feature gap the odysseus read found** (ANALYSIS.md §60 item 2,
and its own one-line answer to "any features overlooked?"): *"nothing in this
app turns an offhand mention in ordinary chat into a filed note"*. MemoryMap
files a note on an explicit instruction or an explicit tool call and never
otherwise: which is a strange gap for an app whose pitch is "a local AI files
your notes". Odysseus's `services/memory/memory_extractor.py` sends the last
few turns to the model after each reply and asks it what is worth remembering.

Three decisions here are deliberate and are what make this safe to run with
nobody watching. They are worth reading before changing anything:

**1. It writes drafts, never finished notes.** ANALYSIS.md's own caution:
*"a background job that mis-files something nobody asked to capture is a worse
failure than one that misses something"*. A draft is kept out of the notes list
(`app.js` filters `!e.is_draft` throughout), out of the Library's main view
(`routes_library.py`) and off the graph (`routes_graph.py`), so the worst case
is a list of suggestions to dismiss rather than a notebook quietly filling with
things the model inferred.

Checked rather than assumed while writing this, and worth recording because
the first draft of the Settings copy claimed more than was true: a draft is
**not** currently excluded from `search_manager` or from the AI's retrieved
context. Only the graph, the Library list and the notes list filter it. That
is a pre-existing property of drafts generally (the text-selection popup makes
them too), not something this job introduced, but the wording next to the
toggle promises only what actually holds.

**2. A fingerprint short-circuit, before anything else.** Odysseus learned this
the expensive way: their own comment records 30–120s per call before they
added one: and the shape here is the same: a SHA-256 of exactly the turns
about to be considered. An unchanged conversation costs one hash and no model
call at all, which matters because this runs on every interval for as long as
the app is open.

**3. It reads the user's own words, not the assistant's.** An answer the model
wrote is not something the user said, and capturing it would mean the notebook
slowly filling with the model quoting itself back. Only the question side of
each turn is offered.
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient
from memorymap.core.database import Conversation

logger = logging.getLogger("memorymap.ai.passive_capture")

#: How many recent turns of one conversation are offered to the model. Enough
#: for "the dentist, Thursday" to still have "book the dentist" above it;
#: short enough that the whole prompt fits a small local model's window
#: alongside its instructions.
TURN_WINDOW = 6

#: The most notes one pass may create, across all conversations. A cap rather
#: than a rate: the failure this guards against is a single long conversation
#: producing thirty drafts at once, which is a list nobody reads.
MAX_CAPTURES_PER_PASS = 5

#: The tag every capture carries, so they can be found, filtered and deleted
#: as a group by someone who tries this and decides against it.
CAPTURE_TAG = "auto-captured"

#: Where the per-conversation fingerprints live. A preference key rather than
#: a new table: it is one small dict, nothing ever queries it, and a migration
#: for it would cost more than it is worth. (`UserPreference` is *not* this: 
#: that table is the agent's memory stream, a list of sentences the model has
#: learned, with no key column at all.)
FINGERPRINT_KEY = "auto_capture_fingerprints"

_SYSTEM = (
    "You read a few turns of someone talking to their notebook and pick out "
    "facts about THEM worth keeping, a decision they made, a preference, a "
    "commitment, a detail about their life or work. Reply with a JSON array of "
    "short strings, one fact per string, written in the third person. Reply "
    "with [] if there is nothing worth keeping, which is the common case. "
    "Never include a question, an instruction to you, or anything you said "
    "yourself."
)


def _fingerprints(config) -> dict[str, str]:  # noqa: ANN001  # core.config.Config
    stored = config.get_preference(FINGERPRINT_KEY, None)
    # Unreadable or absent storage costs the short-circuit, not the pass, 
    # every conversation simply looks new once, and the next write repairs it.
    return dict(stored) if isinstance(stored, dict) else {}


def _save_fingerprints(config, prints: dict[str, str]) -> None:  # noqa: ANN001
    # Trimmed before writing: this grows by one entry per conversation ever
    # held, and it is read on every pass. Ten is the same window
    # `capture_pass` looks at, so nothing still in scope is ever dropped.
    if len(prints) > 40:
        prints = dict(list(prints.items())[-40:])
    config.set_preference(FINGERPRINT_KEY, prints)


def recent_questions(conversation: Conversation, limit: int = TURN_WINDOW) -> list[str]:
    """The user's own last few messages from a stored conversation.

    `Conversation.messages` is a JSON array of `{role, content}`; anything
    that is not a readable user message is skipped rather than raised on,
    because one malformed row must not stop the pass for every other
    conversation.
    """
    try:
        messages = json.loads(conversation.messages or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(messages, list):
        return []
    said = [
        str(m.get("content") or "").strip()
        for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    return [text for text in said if text][-limit:]


def _fingerprint(questions: list[str]) -> str:
    return hashlib.sha256("\n".join(questions).encode("utf-8")).hexdigest()


def _parse_facts(reply: str) -> list[str]:
    """The model's answer, as a list of short strings.

    A local model asked for JSON will sometimes wrap it in prose or a fence,
    so the array is located rather than assumed to be the whole reply. Nothing
    is salvaged beyond that: a reply this cannot read yields no captures,
    which is the right failure for a job that writes to the notebook.
    """
    text = (reply or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        loaded = json.loads(text[start : end + 1])
    except ValueError:
        return []
    if not isinstance(loaded, list):
        return []
    facts = []
    for item in loaded:
        fact = str(item).strip()
        # A one-word "fact" is noise, and a paragraph is the model ignoring
        # the instruction and summarising the conversation instead.
        if 8 <= len(fact) <= 300:
            facts.append(fact)
    return facts


def capture_pass(
    session: Session,
    model_manager: ModelManager,
    ollama: OllamaClient,
    config,  # noqa: ANN001  # core.config.Config, holds the fingerprints
    limit: int = MAX_CAPTURES_PER_PASS,
) -> int:
    """One pass over recent conversations. Returns how many drafts it wrote."""
    from memorymap.entry import manager as entry_manager

    prints = _fingerprints(config)
    created = 0
    changed = False

    conversations = session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(10)
    ).all()

    for conversation in conversations:
        if created >= limit:
            break
        questions = recent_questions(conversation)
        if not questions:
            continue
        stamp = _fingerprint(questions)
        if prints.get(str(conversation.id)) == stamp:
            continue
        # Written *before* the model call, not after. A crash or a stop
        # between the two would otherwise re-offer the same turns on the next
        # pass, which is precisely the repeated expensive call the
        # fingerprint exists to prevent.
        prints[str(conversation.id)] = stamp
        changed = True

        try:
            reply = ollama.chat(
                model_manager.utility_model(),
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": "\n".join(f"- {q}" for q in questions)},
                ],
            )
        except Exception as exc:  # noqa: BLE001  # a backend failure skips, never stops
            logger.info("passive capture skipped a conversation: %s", exc)
            continue

        for fact in _parse_facts(reply.get("content", "")):
            if created >= limit:
                break
            entry = entry_manager.create_entry(
                session,
                fact,
                tags=[CAPTURE_TAG],
            )
            # A draft, not a note. See this module's docstring: it is what
            # keeps a mis-capture a suggestion to dismiss rather than
            # something in your notebook you did not write.
            entry.is_draft = True
            session.commit()
            created += 1

    if changed:
        _save_fingerprints(config, prints)
    return created
