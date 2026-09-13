"""Turn loose thoughts into a written note, and keep revising it.

The shape of the interaction matters more than the prompt here. You write
whatever is in your head, the model turns it into a draft, and then it's a
conversation: you edit the draft directly, or add more thoughts, and the model
folds the new material in *without* undoing your edits.

That last part is the whole trick. A naive implementation regenerates from the
thoughts each time, which silently throws away every correction the user made
- so the draft the model is revising is always sent back to it, and it's told
in as many words that the user's wording wins.
"""

from __future__ import annotations

import re

from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError

OFFLINE_MESSAGE = (
    "The AI isn't running, so it can't draft this yet. Start Ollama and try "
    "again: nothing you've typed is lost."
)

FIRST_DRAFT = (
    "The user has written down some loose thoughts. Turn them into one "
    "well-organised note.\n"
    "- Write the note itself and nothing else: no preamble, no sign-off, no "
    "'here is your note'.\n"
    "- Use their facts only. Do not invent details, examples, or numbers.\n"
    "- Keep their voice. If they wrote casually, stay casual.\n"
    "- Structure it the way the content suggests, a short heading and "
    "paragraphs, or bullets for a list. Markdown is fine.\n"
    "- Be comprehensive about what they said, without padding it out."
)

REVISION = (
    "You are revising a note that already exists. The user has added more "
    "thoughts, and may have edited the draft themselves since you last saw "
    "it.\n"
    "- The CURRENT DRAFT below is the source of truth. The user's own wording "
    "and edits must be preserved, do not rewrite passages they have already "
    "settled on.\n"
    "- Fold the new thoughts into it: add, extend, or correct as they imply.\n"
    "- If the new thoughts contradict something in the draft, the new thoughts "
    "win.\n"
    "- Return the complete revised note and nothing else. No commentary about "
    "what you changed."
)

TITLE_PROMPT = (
    "Give this note a short title, 2 to 6 words. Reply with the title only: "
    "no quotes, no trailing punctuation, no explanation."
)


def build_messages(thoughts: str, draft: str | None, instruction: str = "") -> list[dict]:
    """Prompt for a first draft, or for a revision when a draft exists."""
    system = REVISION if (draft or "").strip() else FIRST_DRAFT
    if instruction.strip():
        # A one-off steer ("make it shorter", "add a conclusion") applies to
        # this pass only, and outranks the generic guidance above.
        system = f"{system}\n\nThe user also asks, for this revision: {instruction.strip()}"

    if (draft or "").strip():
        content = (
            f"CURRENT DRAFT:\n{draft.strip()}\n\n"
            f"NEW THOUGHTS TO FOLD IN:\n{thoughts.strip()}"
        )
    else:
        content = f"MY THOUGHTS:\n{thoughts.strip()}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def compose(
    thoughts: str,
    draft: str | None,
    model_manager: ModelManager,
    ollama: OllamaClient,
    instruction: str = "",
) -> tuple[str, str | None]:
    """(draft text, model's thinking or None).

    Raises nothing: a model that's down returns the existing draft untouched
    alongside an explanation, because losing a draft to an outage would be far
    worse than not improving it.
    """
    if not (thoughts or "").strip() and not (draft or "").strip():
        return "", None
    if not ollama.is_running():
        return (draft or ""), OFFLINE_MESSAGE

    try:
        reply = ollama.chat(
            model_manager.chat_model(),
            build_messages(thoughts, draft, instruction),
        )
    except OllamaError:
        return (draft or ""), OFFLINE_MESSAGE

    text = (reply.get("content") or "").strip()
    if not text:
        # An empty reply must not wipe the draft the user already has.
        return (draft or ""), reply.get("thinking")
    return text, reply.get("thinking")


#: "write" produces a standalone new passage, not a rewrite of anything
#: that already exists: the opposite instinct from REVISION above, which
#: exists specifically to preserve settled wording. Told explicitly not to
#: restate the surrounding document, since a model asked to "add a
#: conclusion" will otherwise happily re-summarise the whole thing first.
DOCUMENT_WRITE_PROMPT = (
    "You are writing a new passage to insert into an existing document, "
    "based on the user's instruction below. Write ONLY the new passage, "
    "no preamble, no restating what the document already says, no "
    "sign-off. It will be inserted exactly as you return it, so it should "
    "read naturally at the point described."
)

#: "remove" is the one verb where "leave everything else untouched" is the
#: entire job: a model asked to remove one sentence will otherwise often
#: also tidy phrasing nearby, which is a second, unrequested edit hiding
#: inside a deletion.
DOCUMENT_REMOVE_PROMPT = (
    "You are removing specific content from a document, based on the "
    "user's instruction below. Return the complete text with only the "
    "requested content removed: every other word must stay exactly as "
    "written. Do not rephrase, reformat, or add anything of your own. No "
    "commentary, just the resulting text."
)


def compose_document_edit(
    content: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
    instruction: str,
    verb: str,
    context: str = "",
) -> tuple[str, str | None]:
    """The "write" and "remove" halves of the document editor's AI panel
    (routes_documents.ai_edit): a sibling of compose() above, not a
    wrapper around it. compose() is shaped around the notes
    thoughts-into-draft workflow (FIRST_DRAFT vs. REVISION), which already
    fits plain rewriting ("edit") well enough that ai_edit keeps calling it
    directly; folding these two very differently-shaped prompts into
    build_messages would have made every branch there conditional on a
    caller only this one route has.

    `verb="write"`: `content` is ignored for the prompt itself (only
    `context`, the passage to insert after, if any, and `instruction`
    matter) and a failed/offline/empty attempt returns "", there is
    nothing sensible to insert, and returning `content` back would insert
    the entire existing document into itself. `verb="remove"`: mirrors
    compose()'s own contract exactly, `content` is the full text being
    edited, and a failed/offline/empty attempt returns it unchanged, since
    losing it would be worse than not removing anything.
    """
    empty_fallback = "" if verb == "write" else content
    if not ollama.is_running():
        return empty_fallback, OFFLINE_MESSAGE

    if verb == "write":
        system = DOCUMENT_WRITE_PROMPT
        user = f"INSTRUCTION: {instruction.strip()}\n\n"
        user += (
            f"INSERT DIRECTLY AFTER THIS EXISTING PASSAGE:\n{context.strip()}"
            if context.strip()
            else f"FOR CONTEXT, THE DOCUMENT SO FAR:\n{(content.strip() or '(empty document)')}"
        )
    else:
        system = DOCUMENT_REMOVE_PROMPT
        user = f"INSTRUCTION: {instruction.strip()}\n\nTEXT:\n{content.strip()}"

    try:
        reply = ollama.chat(
            model_manager.chat_model(),
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except OllamaError:
        return empty_fallback, OFFLINE_MESSAGE

    text = (reply.get("content") or "").strip()
    if not text:
        return empty_fallback, reply.get("thinking")
    return text, reply.get("thinking")


def suggest_title(draft: str, model_manager: ModelManager, ollama: OllamaClient) -> str:
    """A short title for a finished draft, or "" if the model can't help."""
    if not (draft or "").strip() or not ollama.is_running():
        return ""
    try:
        reply = ollama.chat(
            model_manager.utility_model(),
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": draft.strip()[:2000]},
            ],
        )
    except OllamaError:
        return ""
    title = (reply.get("content") or "").strip().splitlines()
    if not title:
        return ""
    cleaned = title[0].strip().strip("\"'`*#").rstrip(".!,;:").strip()
    if not cleaned or len(cleaned) > 80 or len(cleaned.split()) > 10:
        return ""
    return cleaned[0].upper() + cleaned[1:]

#: How many rewordings to ask for. Three is the number Word offers and the
#: number a person can hold in their head at once; a list of eight is a second
#: decision rather than an answer to the first.
REPHRASE_COUNT = 3

REPHRASE_PROMPT = (
    "You rewrite a short passage. Give exactly {count} alternatives, one per "
    "line, numbered 1. 2. 3.: nothing else, no preamble, no explanation. "
    "Keep the author's voice and meaning; fix only what the note below says is "
    "wrong. Each alternative must be a drop-in replacement for the passage: no "
    "quotation marks around it, no trailing full stop unless the original had "
    "one."
)


def rephrase(
    passage: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
    note: str = "",
    count: int = REPHRASE_COUNT,
) -> list[str]:
    """Alternative wordings for one passage, best-effort.

    Asked for directly: *"the listed errors in suggestions have no way to have
    the ai write a suggested replacement or multiple for the user to choose."*
    The app's own checks catch spelling, spacing and sentence length and can
    offer a fix for the first two; for "this sentence is hard to follow" there
    is no mechanical answer, and until now the panel simply said so. A local
    model *can* answer it, the honest way to use one is to offer several
    wordings and let the writer pick, which is what Word does and what nobody
    can mistake for the app having rewritten their document.

    Returns `[]` rather than raising on every failure path, offline, an error,
    an unusable reply. The caller shows what it gets; an empty list is "no
    suggestions", which is a true statement and not an error the writer caused.
    """
    text = (passage or "").strip()
    if not text or not ollama.is_running():
        return []
    ask = f"Passage:\n{text[:1200]}"
    if note.strip():
        ask = f"What is wrong with it: {note.strip()[:200]}\n\n{ask}"
    try:
        reply = ollama.chat(
            model_manager.utility_model(),
            [
                {"role": "system", "content": REPHRASE_PROMPT.format(count=count)},
                {"role": "user", "content": ask},
            ],
        )
    except OllamaError:
        return []
    return _parse_rephrasings((reply.get("content") or ""), text, count)


def _parse_rephrasings(reply: str, original: str, count: int) -> list[str]:
    """Pull the numbered lines out of a model's reply.

    Deliberately forgiving about the shape and strict about the content: small
    local models number with "1.", "1)", "-" or nothing at all, and wrap
    answers in quotes about half the time. What it will not do is return the
    original unchanged, an empty line, or a duplicate, each of those is a
    "suggestion" that costs a click and changes nothing.
    """
    out: list[str] = []
    for raw in (reply or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # "1." / "1)" / "- " / "* ", the numbering, not the words.
        line = re.sub(r"^\s*(?:\d+\s*[.):-]|[-*\u2022])\s*", "", line).strip()
        line = line.strip("\"'`")
        if not line or line == original:
            continue
        if line.lower() in {existing.lower() for existing in out}:
            continue
        out.append(line)
        if len(out) >= count:
            break
    return out

