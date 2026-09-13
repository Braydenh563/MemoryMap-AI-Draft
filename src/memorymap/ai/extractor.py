"""Split free text into one or more AI-filed notes (BACKLOG.md §62).

Asked for directly, alongside "Draft with AI": select a block of writing, 
the Writing Room's draft, a Document's body, or the combined content of
several notes selected on the whiteboard, and turn it into one refined note
or several, each auto-linked to where it came from and to what it relates,
with a real reason on every link.

Deliberately not a new subsystem. Every judgment call here reuses machinery
that already exists elsewhere for the same decision, rather than inventing a
second version of it:

- **One note or several?** The model proposes a split (it has to: nothing
  else in this codebase reads free text and finds topic boundaries), but the
  proposal is then run past the exact bar `janitor.categorise` already
  trusts to decide "the same thing" without asking further:
  `CONFIDENT_MATCH` on the content's own embeddings. A split the model made
  between two near-identical passages is folded back together rather than
  shown as two separate notes, see `merge_near_duplicates`.
- **What category does each note get?** `janitor.categorise`, the same
  centroid/kNN/LLM cascade a normal save goes through (`_create_note` in
  `ai.tools`), not a second filing decision for extracted notes specifically.
- **Why is a link there?** `librarian.generate_link_reason`, the same call
  the background link-reason audit (`ai.links`) makes: never
  `manager.AUTO_REASON_TEXT`'s guessed "similar in meaning". A candidate the
  model can't give a specific reason for (offline, or a reply that comes
  back empty or still vague) is left out of the proposal entirely, using
  `ai.links`' own vagueness/cleanup checks: the same "no reason is more
  honest than a bad one" rule the audit already lives by.

Everything here only *proposes*, see `routes_entries.py`'s
`/entries/extract/preview` and `/entries/extract/commit`. Nothing in this
module writes to the database; `build_extraction` is read-only against the
session it's given, the same way `janitor.categorise` and
`librarian.generate_link_reason` already are.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from memorymap.ai import janitor, librarian
from memorymap.ai.embeddings import EmbeddingService, cosine_similarity
from memorymap.ai.links import _clean_reason, _is_vague_reason
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError
from memorymap.entry import manager
from memorymap.search import search_manager

logger = logging.getLogger("memorymap.ai.extractor")

# A generous amount of free writing, but bounded so a runaway paste doesn't
# turn into an open-ended chain of LLM calls (see the call-count comment on
# `build_extraction` below).
EXTRACT_MAX_CHARS = 20_000

# "Several distinct topics" in one sitting of writing is realistically a
# handful, not dozens: and every extra note here costs more LLM calls
# (categorising it, finding what it relates to, linking it to its siblings),
# so this both matches how the feature is actually used and keeps a single
# preview request from taking minutes on a small local model.
MAX_EXTRACT_NOTES = 4

# How many existing notes the caller already selected as "source" (a Graph/
# whiteboard selection's notes-in-context) this will try to link every new
# note back to. Bounded for the same reason as MAX_EXTRACT_NOTES, a
# generous selection is still a selection, not "link to the whole notebook".
MAX_SOURCE_IDS = 3

# Existing notes (beyond the explicit sources) worth surfacing as "related"
# per new note. A short shortlist to read, matching the spirit of
# `SEMANTIC_LIST_LIMIT` elsewhere: this is a preview to review, not a second
# copy of link-suggestions.
RELATED_PER_NOTE = 2

# The same bar `link-suggestions` ranks by and `_deduce_reason` requires
# before a link earns even the generic guess, reused rather than inventing
# a second "related enough to surface here" threshold.
RELATED_THRESHOLD = manager.AUTO_REASON_THRESHOLD

SPLIT_SYSTEM_PROMPT = (
    "You are splitting a piece of free writing into one or more focused "
    "notes for a personal notebook. If the text is really about ONE topic, "
    "return exactly one note that lightly cleans it up. If it clearly "
    "covers SEVERAL distinct topics, split it into one note per topic, "
    "never split something that is really one idea just to produce more "
    "notes.\n\n"
    "Use only the writer's own facts: never invent details, examples, or "
    "numbers that are not in the text. Keep their voice.\n\n"
    f"Return at most {MAX_EXTRACT_NOTES} notes.\n\n"
    'Reply with ONLY JSON: {"notes": [{"title": "2-8 words", "content": '
    '"the note text"}, ...]}'
)

OFFLINE_MESSAGE = (
    "The AI isn't running, so this couldn't be split or linked, it's shown "
    "as one plain note below. Start Ollama and try again for a real split."
)

SPLIT_FAILED_MESSAGE = (
    "The AI couldn't split this cleanly, so it's shown as one note, edit "
    "it below, or save it as is."
)


@dataclass
class ExtractedNote:
    title: str
    content: str


def _extract_json_object(text: str) -> dict:
    """Small models often wrap JSON in chatter, grab the {...} part.
    Same approach as `janitor._extract_json`, duplicated rather than
    imported since that helper is private to a module about a different
    decision (categorising, not splitting)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in reply: {text!r}")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("reply JSON is not an object")
    return parsed


def propose_split(
    text: str, model_manager: ModelManager, ollama: OllamaClient
) -> list[ExtractedNote]:
    """Ask the model to split `text` into one or more notes.

    Raises `OllamaError` if the model is down, `ValueError` if its reply
    can't be turned into usable notes, both are the caller's cue
    (`build_extraction`) to fall back to one plain note rather than lose
    the writing.
    """
    reply = ollama.chat(
        model_manager.chat_model(),
        [
            {"role": "system", "content": SPLIT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    data = _extract_json_object(reply["content"])
    raw_notes = data.get("notes")
    if not isinstance(raw_notes, list) or not raw_notes:
        raise ValueError("reply had no notes")
    notes = []
    for raw in raw_notes[:MAX_EXTRACT_NOTES]:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "").strip()
        if not content:
            continue
        title = str(raw.get("title") or "").strip()
        notes.append(ExtractedNote(title=title, content=content))
    if not notes:
        raise ValueError("no usable notes in reply")
    return notes


def merge_near_duplicates(
    notes: list[ExtractedNote], embeddings: EmbeddingService
) -> list[ExtractedNote]:
    """Fold together any two proposed notes whose content embeddings are as
    close as janitor's own `CONFIDENT_MATCH` bar: the "trust the
    embedding, no need to ask further" threshold `janitor.categorise` uses
    to decide a category with no LLM call, reused here for the one-vs-
    several decision instead of inventing a second threshold. A split the
    model made between two near-identical passages is undone rather than
    shown as two separate notes.

    Best-effort: a note whose embedding can't be computed (embeddings
    backend off) is left un-merged with anything, the same way
    `_best_centroid_match` skips a note it has no vector for.
    """
    if len(notes) < 2:
        return notes
    vectors = [embeddings.embed_text(n.content) for n in notes]
    merged: list[ExtractedNote] = []
    used = [False] * len(notes)
    for i, note in enumerate(notes):
        if used[i]:
            continue
        used[i] = True
        group_content = [note.content]
        if vectors[i] is not None:
            for j in range(i + 1, len(notes)):
                if used[j] or vectors[j] is None:
                    continue
                if cosine_similarity(vectors[i], vectors[j]) >= janitor.CONFIDENT_MATCH:
                    group_content.append(notes[j].content)
                    used[j] = True
        merged.append(ExtractedNote(title=note.title, content="\n\n".join(group_content)))
    return merged


def _short_preview(text: str, length: int = 120) -> str:
    plain = manager.WIKI_LINK.sub(r"\1", text or "")
    return plain if len(plain) <= length else plain[: length - 1] + "…"


def _reason_for(
    content: str, other_content: str, model_manager: ModelManager, ollama: OllamaClient
) -> str | None:
    """A real, specific reason for linking `content` to `other_content`, or
    None when the model is down or can only offer a vague one, see the
    module docstring: never `manager.AUTO_REASON_TEXT`, and never a link
    with nothing honest to say about it."""
    try:
        reply = librarian.generate_link_reason(content, other_content, model_manager, ollama)
    except OllamaError:
        return None
    reason = _clean_reason(reply)
    if not reason or _is_vague_reason(reason):
        return None
    return reason


def find_related(
    session: Session,
    content: str,
    embeddings: EmbeddingService,
    model_manager: ModelManager,
    ollama: OllamaClient,
    exclude_ids: set[int],
    limit: int = RELATED_PER_NOTE,
) -> list[dict]:
    """Existing notes (other than the explicit sources) worth linking this
    new one to, each with a real reason. Semantic search first; a keyword
    fallback when the embedding backend is off, same as search elsewhere
    falling back for the same reason."""
    candidates = []
    results = search_manager.semantic_search(session, content, embeddings, limit=limit + len(exclude_ids) + 3)
    if results is not None:
        for entry, score in results:
            if entry.id in exclude_ids or entry.is_private or score < RELATED_THRESHOLD:
                continue
            candidates.append(entry)
    else:
        for entry in search_manager.keyword_search(session, content, limit=limit + len(exclude_ids) + 3):
            if entry.id in exclude_ids or entry.is_private:
                continue
            candidates.append(entry)

    related = []
    for entry in candidates:
        if len(related) >= limit:
            break
        reason = _reason_for(content, entry.content, model_manager, ollama)
        if reason is None:
            continue
        related.append({"entry_id": entry.id, "preview": _short_preview(entry.content), "reason": reason})
    return related


def build_extraction(
    session: Session,
    text: str,
    embeddings: EmbeddingService,
    model_manager: ModelManager,
    ollama: OllamaClient,
    source_entry_ids: list[int] | None = None,
) -> dict:
    """The whole preview: proposed note(s), filed by the janitor, linked to
    their sources and to each other and to whatever else in the notebook
    they relate to: every link carrying a real reason or not existing at
    all. Nothing is written to `session`; see the module docstring.

    Raises `ValueError` for bad input (empty text, too much text), the
    caller's cue for a 400, not a 500.

    LLM call count is bounded on purpose: at most
    `MAX_SOURCE_IDS * MAX_EXTRACT_NOTES` source-link calls,
    `RELATED_PER_NOTE * MAX_EXTRACT_NOTES` related-link calls, and
    `MAX_EXTRACT_NOTES - 1` sibling-link calls, plus one split call, a
    genuinely large extraction still costs low double digits of calls, not
    an unbounded one.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("There's no text to extract notes from.")
    if len(text) > EXTRACT_MAX_CHARS:
        raise ValueError(
            f"That's too much text to extract from at once ({len(text)} "
            f"characters: {EXTRACT_MAX_CHARS} is the most)."
        )

    source_ids = list(dict.fromkeys(source_entry_ids or []))[:MAX_SOURCE_IDS]
    source_entries = []
    for sid in source_ids:
        entry = manager.get_entry(session, sid)
        if entry is not None and not entry.is_deleted and not entry.is_private:
            source_entries.append(entry)

    ollama_running = ollama.is_running()
    message = ""
    if not ollama_running:
        notes = [ExtractedNote(title="", content=text)]
        message = OFFLINE_MESSAGE
    else:
        try:
            notes = propose_split(text, model_manager, ollama)
            notes = merge_near_duplicates(notes, embeddings)
        except (OllamaError, ValueError) as exc:
            logger.info("extraction split failed, falling back to one note: %s", exc)
            notes = [ExtractedNote(title="", content=text)]
            message = SPLIT_FAILED_MESSAGE

    proposals = []
    for i, note in enumerate(notes):
        category, confidence, filed_by = janitor.categorise(
            session, note.content, embeddings, model_manager, ollama
        )
        proposals.append({
            "ref": f"n{i}",
            "title": note.title,
            "content": note.content,
            "category": category,
            "tags": [],
            "confidence": confidence,
            "filed_by": filed_by,
        })

    links: list[dict] = []
    if ollama_running:
        exclude_ids = {e.id for e in source_entries}
        for i, note in enumerate(notes):
            ref = f"n{i}"
            for entry in source_entries:
                reason = _reason_for(note.content, entry.content, model_manager, ollama)
                if reason is None:
                    continue
                links.append({
                    "source_ref": ref,
                    "target_ref": f"existing:{entry.id}",
                    "target_preview": _short_preview(entry.content),
                    "reason": reason,
                    "kind": "source",
                })
            for related in find_related(
                session, note.content, embeddings, model_manager, ollama, exclude_ids
            ):
                links.append({
                    "source_ref": ref,
                    "target_ref": f"existing:{related['entry_id']}",
                    "target_preview": related["preview"],
                    "reason": related["reason"],
                    "kind": "related",
                })
        for i in range(len(notes) - 1):
            reason = _reason_for(notes[i].content, notes[i + 1].content, model_manager, ollama)
            if reason is None:
                continue
            links.append({
                "source_ref": f"n{i}",
                "target_ref": f"n{i + 1}",
                "target_preview": "",
                "reason": reason,
                "kind": "sibling",
            })

    return {
        "notes": proposals,
        "links": links,
        "ollama_running": ollama_running,
        "message": message,
    }
