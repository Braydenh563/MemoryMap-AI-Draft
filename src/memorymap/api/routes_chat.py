"""Ask a question, get back BOTH a conversational answer and the raw
matching entries: the two-result design from the original idea doc.

Two flavours:
- POST /chat: one blocking JSON response (simple, used by tests/API)
- POST /chat/stream: NDJSON: metadata + raw results first, then the
  model's thinking and answer as live token deltas (what the UI uses)

Plain `def` so the blocking LLM call runs in FastAPI's threadpool.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from collections.abc import Iterator
from itertools import chain

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from memorymap.ai import budget as run_budget
from memorymap.ai import (
    agent,
    captioning,
    context,
    followups,
    intent,
    librarian,
    memory,
    notebook_stats,
    presets,
    skill_runner,
    skills,
    tools,
    vision_ocr,
)
from memorymap.ai.grounding import ground_answer_sentences
from memorymap.ai.ollama_client import OllamaError
from memorymap.api.schemas import EntryOut
from memorymap.core import deps, docview
from memorymap.core.database import (
    LIKE_ESCAPE,
    Attachment,
    AskTurn,
    AuditLog,
    Category,
    Conversation,
    Document,
    Entry,
    MediaUpload,
    Reminder,
    like_escape,
)
from memorymap.core.deps import get_session
from memorymap.core.logbuffer import safe_value
from memorymap.entry import manager
from memorymap.entry.manager import UNCATEGORISED
from memorymap.search import search_manager
from sqlalchemy import func

#: `/media/<filename>` as it appears inside note and document content, 
#: the only record a note keeps of a picture it holds.
_MEDIA_REF = re.compile(r"/media/([A-Za-z0-9._-]{1,200})")

router = APIRouter(prefix="/chat", tags=["chat"])


#: **Asking and requesting are logged apart, and this is why.** Reported
#: directly: "tasks that I have put in the agent show in the 'ask' again
#: section, the things that I will ask the agent are different to what I would
#: ask if searching in my notebook."
#:
#: Every turn through this module used to write one `queried`/`chat` audit row,
#: so "Ask again", which reads that log, offered back "tag everything about
#: the trip" and "delete the draft" as though they were questions about the
#: notebook. They are instructions, they have already been carried out, and
#: running one a second time from a chip is at best pointless and at worst a
#: repeat of an action the user did not mean to repeat.
#:
#: The rule the user gave, in their words: "if I was in the chat and using the
#: 'ask' mode, then those queries should count, but only those, and my previous
#: requests in the 'ask' subtab in notes should be registered." So the two
#: reading surfaces: the Notes tab's Ask box (`notes_only`) and the Chat tab
#: in Ask mode (tools off): write `chat`; Request mode and the Ctrl+Shift+A
#: palette, both of which act, write `agent`. Both stay in the audit log, which
#: is a record of what happened and should not lose the requests; only the
#: chip row narrows.
ASK_SURFACE = "chat"
AGENT_SURFACE = "agent"


def _recent_questions(session: Session, limit: int = 5) -> list[str]:
    """The last `limit` distinct questions asked at the Ask box, newest first.
    Read straight from the audit log, no extra bookkeeping.

    Scoped to `ASK_SURFACE`, so an instruction given to the agent is never
    offered back as something to ask again."""
    rows = session.scalars(
        select(AuditLog)
        .where(AuditLog.action == "queried", AuditLog.entity_type == ASK_SURFACE)
        .order_by(AuditLog.id.desc())
        .limit(50)
    )
    questions: list[str] = []
    for row in rows:
        if row.detail and row.detail not in questions:
            questions.append(row.detail)
        if len(questions) == limit:
            break
    return questions


@router.get("/recent", response_model=list[str])
def recent_questions(session: Session = Depends(get_session)) -> list[str]:
    """The last 5 distinct questions, newest first (quick access)."""
    return _recent_questions(session)


def _asked_key(question: str) -> str:
    """One spelling of a question, for comparing the two suggestion rows.

    Only case and surrounding space: a chip is clicked verbatim, so a repeat
    is character-for-character the same string, and anything cleverer here
    (dropping the question mark, stemming) would start deciding that two
    *different* questions are the same one."""
    return " ".join(question.split()).casefold()


#: **The two suggestion rows do not show each other's chips.** Reported (INBOX
#: 120, the owner): "the try asking and ask again suggestions are nearly
#: identical", with "Try asking:" above "Ask again:" and two of the five chips
#: below repeating the row above word for word. The rows answer different
#: questions, what you could ask and what you already asked, so neither should
#: be showing the other's answer.
#:
#: The rule, decided with the report: the history row wins a duplicate, because
#: it is a fact about this notebook rather than something generated, and the
#: generated row fills the gap with its next candidate. Which is why this is
#: settled here, on the server that builds both rows, rather than in the two
#: independent `loadSuggestions`/`loadRecentQuestions` calls in the client,
#: where it would depend on which request came back first.
SUGGESTIONS_SHOWN = 4


def _fill(candidates: list[str], asked: set[str]) -> list[str]:
    """The first `SUGGESTIONS_SHOWN` candidates that are neither a repeat of
    each other nor already offered by "Ask again"."""
    picks: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _asked_key(candidate)
        if key in seen or key in asked:
            continue
        seen.add(key)
        picks.append(candidate)
        if len(picks) == SUGGESTIONS_SHOWN:
            break
    return picks


# Shown when the chat is empty, to teach the feature (Round 1).
STARTER_SUGGESTIONS = [
    "What have I saved so far?",
    "Summarise my notes.",
    "What are my most common topics?",
]


@router.get("/suggestions", response_model=list[str])
def suggestions(session: Session = Depends(get_session)) -> list[str]:
    """Recommended questions: content-aware ones built from the user's own
    categories, falling back to generic starters for an empty notebook."""
    rows = session.execute(
        select(Category.name, func.count(Entry.id))
        .join(Entry, Entry.category_id == Category.id)
        .where(Entry.is_deleted == False)  # noqa: E712
        .group_by(Category.name)
        .order_by(func.count(Entry.id).desc())
    ).all()
    categories = [name for name, _count in rows if name != UNCATEGORISED]

    asked = {_asked_key(question) for question in _recent_questions(session)}

    if not categories:
        return _fill(STARTER_SUGGESTIONS, asked)

    # The first four are what this endpoint has always offered, in the order it
    # offered them. The rest are reserves, reached only when one of the four is
    # dropped for being in "Ask again" already, so the row keeps its length
    # instead of losing a chip to the row below it.
    candidates = [f"What have I saved about {name.lower()}?" for name in categories[:2]]
    candidates.append(f"Summarise my {categories[0].lower()}.")
    candidates.append("What have I saved recently?")
    candidates += [f"What have I saved about {name.lower()}?" for name in categories[2:6]]
    candidates += [f"Summarise my {name.lower()}." for name in categories[1:3]]
    candidates.append("What are my most common topics?")
    return _fill(candidates, asked)


class FollowupBody(BaseModel):
    """One answered turn, sent back to ask what to offer next.

    Bounded here rather than only inside `followups` because this arrives over
    HTTP: the client is echoing back a turn the server just produced, but
    nothing makes that true of a hand-made request, and both fields end up in a
    model prompt.
    """

    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=20000)


@router.post("/followups", response_model=list[str])
def chat_followups(body: FollowupBody) -> list[str]:
    """Two or three questions to offer under an answer, or [].

    Its own request rather than part of the turn on purpose: this is a second
    model call, and the answer must not wait on it. The UI fires this after the
    turn is on screen and simply renders nothing if it comes back empty, which
    it does on every failure path, including the AI not running at all.
    """
    return followups.suggest_followups(
        body.question,
        body.answer,
        deps.get_model_manager(),
        deps.get_ollama(),
    )


class ChatTurn(BaseModel):
    question: str
    answer: str


class PlanRun(BaseModel):
    """A plan the model made for one request, sent back to be worked through.

    Bounded here as well as in `tools.validate_make_plan`, because this arrives
    over HTTP: the client is echoing back what the server just produced, but
    nothing makes that true of a hand-made request, and the run it starts
    writes to the notebook.
    """

    goal: str = Field(min_length=1, max_length=skills.MAX_GOAL)
    steps: list[str] = Field(min_length=1, max_length=skills.MAX_STEPS)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    # Prior turns for follow-up context (Round 1); the server clips this.
    history: list[ChatTurn] = Field(default_factory=list)
    # Persona name; None → the active persona preference.
    persona: str | None = None
    # Agent mode: may the model call tools to change things?
    # None → the saved "tools_enabled" preference (default on).
    use_tools: bool | None = None
    # How much effort this turn is worth (§11): "quick", "normal" or
    # "detailed". None → the saved "response_mode" preference. Carries the
    # reply cap, the temperature, the thinking toggle and a length hint, so
    # one picker moves all four together rather than four settings that have
    # to be kept consistent by hand.
    mode: str | None = None
    # Notes the user attached by hand. These are always given to the model,
    # ahead of anything retrieval finds, "this note, specifically" is a
    # stronger signal than any similarity score.
    note_ids: list[int] = Field(default_factory=list, max_length=20)
    # Documents attached by hand (§89.2): same idea as note_ids, a separate
    # field because Document is a separate table from Entry (see its own
    # docstring in core/database.py for why). The frontend has sent this
    # since the composer's staging UI shipped; nothing here ever read it, 
    # an attached document showed as a chip on the message and the model
    # never saw its content, which is worse than not offering the feature at
    # all, since it looks like it worked. Capped at 4, matching the
    # composer's own `attachedDocuments.length >= 4` limit.
    document_ids: list[int] = Field(default_factory=list, max_length=4)
    # Files from the Library, attached by hand. Asked for directly: "I want to
    # be able to attach not just existing notes to a chat for context, but also
    # already uploaded files, documents, and images." A PDF, a spreadsheet or a
    # source file is an Attachment row, not a Document and not an Entry, so it
    # needs a field of its own for the same reason document_ids does. Its text
    # is extracted at request time by the same `core.docview` the file viewer
    # uses, so what the model reads is what the Files tab shows.
    file_ids: list[int] = Field(default_factory=list, max_length=4)
    # Mind maps attached by hand (MINDMAP_PLAN.md §5 item 11: "a map can be
    # attached to a note, a document and a chat message, exactly as a file can
    # today: routes_chat.py's `file_ids` is the pattern to copy"). A map is a
    # board, which is an Entry, so this *could* have gone through `note_ids`, 
    # and that is exactly what must not happen: a board's `content` is the
    # single line `# My map`, so attaching one that way sends the model a
    # heading and calls it a map. What reaches the model instead is the
    # outline `read_mindmap` builds, which is the form the plan chose for a
    # small model to act on. Capped at 4, matching `document_ids`/`file_ids`
    # and the composer's own ceiling.
    board_ids: list[int] = Field(default_factory=list, max_length=4)
    # Vision-capable models (ROADMAP.md's largest open item): ids from the
    # existing `/media/upload` (the same endpoint the document/note editors
    # already use for drag-and-drop images), not a second upload path. Small
    # cap: a local model paying attention to four images at once is already
    # optimistic, and each one inflates the request by ~33% once base64'd.
    image_media_ids: list[int] = Field(default_factory=list, max_length=4)
    # Running a saved skill (§21). The name of one, built-in or the user's
    # own: plus values for whatever inputs it declares. The server builds the
    # instruction, so what a skill *is* lives in one place rather than being
    # assembled in `app.js` and hoped for here.
    skill: str | None = Field(default=None, max_length=skills.MAX_NAME)
    skill_inputs: dict[str, str] | None = None
    # Resuming a run that stopped part-way (reported: *"it cuts out half way
    # through and has to restart"*). Steps before this index are marked as done
    # in an earlier run and are not repeated, which matters because most of
    # them write to the notebook, so "restart" meant tagging and linking the
    # same notes a second time.
    skill_from_step: int = Field(default=0, ge=0, le=skills.MAX_STEPS)
    # Manual (step-through) mode, asked for directly: a pause after every
    # completed step with a Continue button and a text box, rather than a
    # skill running straight through unattended. `skill_manual_note` is what
    # was typed in at that pause, folded into the very next step's own
    # instruction, not stored anywhere.
    skill_manual: bool = False
    skill_manual_note: str | None = Field(default=None, max_length=skills.MAX_MANUAL_NOTE)
    # A plan the model drew for this request and handed back to be worked
    # through (§35K). Same shape as a skill run and the same runner, the
    # difference is only that nobody saved it. Sent by the client rather than
    # parked on the server, exactly as `ask_user` and `run_skill` are: nothing
    # to expire, nothing lost on a reload, and the plan is visible in the saved
    # conversation like any other message.
    plan: PlanRun | None = None
    # Notes-only: this turn is an interrogation of the notebook and nothing
    # else (§35A). Set by the Notes tab's Ask box, never by the Chat tab.
    #
    # Reported directly: *"the ask tab should be for reviewing, revisiting, and
    # searching up/asking about your notes, the chatbot can be for the chat
    # tab"*. Saying "hey" there was answered like a chatbot, because both
    # surfaces share this endpoint and `intent.classify` correctly routes
    # small talk away from retrieval.
    #
    # The fix is deliberately NOT a better classifier. The classifier is right;
    # what was missing is that one of the two callers does not *want* the
    # conversational path to exist. A flag on the request cannot misfire, costs
    # no model round, and leaves the Chat tab exactly as it was.
    notes_only: bool = False
    # The reverse problem (Tier 1 §4): the agent's own `ask_user` question
    # gets a one-word reply, "yes", "ok", "sure", all real answers a person
    # gives: and `intent.classify` correctly calls a bare "yes" small talk.
    # Routed as small talk it lands in the conversational path, which has no
    # tools at all, so the answer to the agent's own question could not be
    # acted on even if the model understood it perfectly. `TOOLS_GUIDE` tells
    # the model several turns are normal; the classifier was quietly cutting
    # this one off after the first. Same fix as `notes_only`: a flag the
    # client sets when it already knows the context, not a smarter
    # classifier trying to guess it from three letters.
    answering_agent: bool = False
    # A deliberately closed set of notes, e.g. Trace's "Generate story from
    # path", where retrieval finding *more* is pollution, not help. Without
    # this, attaching notes still ran the normal retrieval search on the
    # turn's own text alongside them (`_attached_notes` only ever added to
    # what search found, never replaced it), so a generic instruction like
    # "weave these into a narrative", no real subject to search for, still
    # keyword/semantic-matched against the whole notebook and appended
    # whatever it found after the notes the user actually chose. Reported as
    # the feature "needing to mainly use the notes within the trace", it
    # was already doing that, plus however many unrelated notes the
    # instruction text itself happened to match.
    attached_notes_only: bool = False


def _resolve_mode(requested: str | None) -> str:
    """The response preset for this turn (§11).

    A request may name one; otherwise the saved preference decides, and an
    unrecognised name in either place falls through to `normal` rather than
    raising: `presets.resolve` does that last part, so a hand-edited
    preferences file costs the setting and not the chat.
    """
    if requested:
        return requested
    return str(
        deps.get_config().get_preference("response_mode", presets.DEFAULT_MODE)
        or presets.DEFAULT_MODE
    )


def _resolve_persona(name: str | None, session: Session | None = None) -> str | None:
    """Persona name → its system prompt (shared with greetings and titles).

    With a session, the user's standing preferences ride along, see
    `ai/memory.py`. **They used to reach only the agent path**, so a rule
    typed into Settings → "What it remembers" was obeyed in Request mode and
    silently ignored in Ask, which is where most questions are asked. Passed
    optionally because the two callers that build a *greeting* or a chat
    *title* genuinely do not want them: neither is answering the user, and a
    title prefixed with someone's writing-style rules is nonsense.
    """
    prompt = librarian.resolve_persona_prompt(name, deps.get_config())
    if session is None:
        return prompt
    return memory.persona_with_memory(session, prompt)


# Base64 inflates size by ~33%; a generous per-image cap keeps one photo
# straight off a phone (often 5-10MB) from making a single turn bigger than
# what most local models' num_ctx could hold in the first place.
MAX_CHAT_IMAGE_BYTES = 8 * 1024 * 1024


def _resolve_chat_images(session: Session, media_ids: list[int]) -> list[tuple[MediaUpload, str]]:
    """Attached-by-id media uploads → (upload row, data URI) pairs.

    `media_ids` come from the same `/media/upload` the note/document editors
    already use for drag-and-drop images, this reuses that upload, rather
    than adding a second upload path for the composer alone. A data URI
    (not bare base64) is the app's neutral shape: `ollama_client` strips the
    prefix for Ollama's wire format, `openai_client` hands the URI straight
    to `image_url.url` unchanged (see both modules' `_to_*_messages`). The
    upload row travels alongside it so `_image_caption_context` below can
    read or generate a caption for it without a second query.

    An id that doesn't resolve, isn't readable, is too large, or isn't
    actually an image (the same upload endpoint also accepts PDFs) is
    silently dropped rather than 500ing the whole turn, the UI already
    confirmed each upload succeeded before sending its id here, so a miss
    means the file moved or was deleted after that, not a bad request.
    """
    if not media_ids:
        return []
    media_dir = deps.get_config().data_dir / "media"
    images = []
    for media_id in media_ids:
        upload = session.get(MediaUpload, media_id)
        if upload is None:
            continue
        try:
            data = (media_dir / upload.filename).read_bytes()
        except OSError:
            continue
        if len(data) > MAX_CHAT_IMAGE_BYTES:
            continue
        mime = mimetypes.guess_type(upload.filename)[0] or ""
        if not mime.startswith("image/"):
            continue
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        images.append((upload, uri))
    return images


def _chat_model_sees_images(model_manager, ollama) -> bool:
    """Whether the model this turn would otherwise use can take an image
    directly. Only a definite "yes" counts: an unknown answer (`None`, the
    same three-way `supports()` itself returns for anything it cannot
    report on) falls back to the caption path in `_image_caption_context`
    rather than gambling a real photo on a model that might silently
    ignore it."""
    supports = getattr(ollama, "supports", None)
    if not callable(supports):
        return False
    return supports(model_manager.chat_model(), "vision") is True


def _image_caption_context(
    images: list[tuple[MediaUpload, str]], model_manager, ollama
) -> str:
    """What a chat model with no vision of its own gets instead of the raw
    image bytes: a vision model's own caption, folded into the question
    text by `librarian.answer`/`converse`/`agent.run_agent`'s own
    `image_context` parameter.

    Asked for directly: "if I am using a chat model with no vision
    capabilities, it will use the vision model to caption the image, then
    the chat model will take that caption and use it for its response", 
    replacing the earlier behaviour of silently swapping the whole turn to
    a different model the user did not choose as their chat model.

    Runs synchronously, in-request: unlike the background trigger on
    upload (routes_files.py's own POST /media/upload), this turn's answer
    depends on having the caption before the chat model is asked anything.
    `caption_and_store` is the same write-once-unless-forced helper that
    trigger uses, so an image already captioned by either path is never
    captioned twice.
    """
    if not images:
        return ""
    media_dir = deps.get_config().data_dir / "media"
    lines = []
    for upload, _uri in images:
        caption = upload.caption or captioning.caption_and_store(
            upload.id, media_dir / upload.filename
        )
        if caption:
            lines.append(f"- {caption}")
    if not lines:
        return ""
    plural = "image" if len(lines) == 1 else "images"
    return (
        f"[{len(lines)} attached {plural}, described by a vision model since "
        "the chat model can't see them directly:\n" + "\n".join(lines) + "]"
    )


def _small_model_mode() -> bool | None:
    """Whether this run gets the small-model treatment: one tool per step and
    a worked example of the call.

    Three states, and the third is the useful one. "auto" returns **None**,
    which is the runner's own "decide from the model", deliberately not
    resolved here, because the run is the thing that knows which model it is
    about to use. `on`/`off` are the override for the two cases a name-based
    guess cannot get right: a 30B that still can't hold five schemas, and a 4B
    that copes fine and would rather have the whole toolbox.
    """
    setting = str(
        deps.get_config().get_preference("small_model_mode", "auto") or "auto"
    ).lower()
    if setting in ("on", "true", "always"):
        return True
    if setting in ("off", "false", "never"):
        return False
    return None


def _resolve_skill(body: ChatRequest) -> dict | None:
    """Turn "run this skill" into the request the model actually receives.

    404 for a skill that isn't there and 422 for one missing a required input:
    a skill that quietly ran with a blank `{{topic}}` would search the whole
    notebook for nothing and read as the model ignoring the user.
    """
    if not body.skill:
        return None
    found = skills.find(deps.get_config(), body.skill, set(tools.TOOLS))
    if found is None:
        raise HTTPException(status_code=404, detail=f"No skill called “{body.skill}”")
    missing = skills.missing_inputs(found, body.skill_inputs or {})
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"“{found['name']}” needs {', '.join(missing)} before it can run",
        )
    return {
        "skill": found,
        "question": skills.run_instruction(found, body.skill_inputs or {}),
        "tools": found["tools"] or None,
        "acts": skills.is_action(found),
    }


def _resolve_plan(body: ChatRequest) -> dict | None:
    """Turn "work through this plan" into a run, in the same shape as a skill.

    Re-validated through `tools.validate_make_plan` rather than trusted, so a
    plan that arrives with one step, twenty steps or its own numbering is
    refused (or tidied) by the same rules that produced it. 422 rather than a
    silent trim: a plan that quietly loses its last two steps is exactly the
    "did the first part and stopped" failure this whole mechanism exists to
    prevent, arriving from the other end.
    """
    if body.plan is None:
        return None
    try:
        checked = tools.validate_make_plan(
            {"goal": body.plan.goal, "steps": body.plan.steps}
        )
    except tools.ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    plan = skills.ad_hoc_plan(checked["goal"], checked["steps"])
    return {
        "skill": plan,
        "question": skills.run_instruction(plan, {}),
        # No allowlist: see `skills.ad_hoc_plan`. Each step is focused on its
        # own text instead of on a guess made from one sentence.
        "tools": None,
        "acts": True,
    }


class ChatResponse(BaseModel):
    ai_response: str
    # A thinking model's reasoning, when it produced any.
    ai_thinking: str | None = None
    raw_results: list[EntryOut]
    # 'hybrid', 'semantic', 'keyword', 'dated' or 'recent', how they were found.
    search_mode: str
    # Which of raw_results are here by connection rather than by matching.
    connected_ids: list[int] = []
    # Why each result showed up, keyed by str(entry id): {"type": "semantic",
    # "score": 0.81} etc. (JSON object keys are always strings; the client
    # converts back). Not every id in raw_results has an entry here: dated/
    # recent/attached results are already explained by search_mode itself.
    match_info: dict[str, dict] = {}
    # Which chat model wrote the answer, or None when it didn't answer.
    answered_by: str | None = None
    # Whether Ollama is reachable, lets the UI distinguish "offline"
    # from "nothing to answer" honestly.
    ollama_running: bool = False
    # The time phrase the search narrowed on ("last week", "recently"), or "".
    # An empty dated result has two facts to report and only saying the first
    #, "no matching records", is what makes a working narrow search look
    # like a broken one. The client needs the phrase to say the second.
    when_phrase: str = ""
    # ROADMAP.md item 36: which retrieved note backs which sentence of the
    # answer, direct-Q&A path only (this endpoint, not /chat/stream's
    # conversational/agentic modes). Omitted, not wrong, for a sentence with
    # no note clearing the overlap threshold, see ai/grounding.py.
    sentence_grounding: list[dict] = []


def _grounding_candidates(
    session: Session, notes: list[dict], touched_note_ids: list[int]
) -> list[dict]:
    """The retrieval set plus every note a tool read this turn, as
    `{id, content}` rows for `ground_answer_sentences`.

    Same refusals as `_attached_notes`: a binned or private note never
    becomes a citation, whatever a tool result said. A tool reads a note
    through `_require_note`, which already refuses both, so this is the
    guard kept where the shape is kept (CLAUDE.md section 6, shape 3) rather
    than a second opinion. Documents are left out on purpose: a document id
    and a note id share a number space in the citation UI, which opens the
    *note* with that id.
    """
    rows = [note for note in notes if note.get("id") is not None]
    seen = {note["id"] for note in rows}
    for note_id in dict.fromkeys(touched_note_ids):
        if note_id in seen:
            continue
        entry = session.get(Entry, note_id)
        if entry is None or entry.is_deleted or entry.is_private:
            continue
        seen.add(note_id)
        rows.append({"id": entry.id, "content": entry.content})
    return rows


def _attached_notes(session: Session, note_ids: list[int]) -> list[dict]:
    """The notes the user picked, in the order they picked them.

    Binned notes are skipped: attaching one would quietly resurrect content the
    user has already thrown away. Private notes are skipped too, a client-
    supplied id list is the one path into this prompt that never went through
    `tools._require_note`, which is the only thing that otherwise refuses a
    private note (CLAUDE.md's own reminder of exactly this shape of bug). A
    forged/stale `note_ids` entry for a private note would otherwise put its
    id and category straight into what the model sees, private-notebook rule
    or not: no plaintext leaks (the content column is ciphertext either way,
    unreadable without `manager.readable_content`), but its existence should
    not be either.
    """
    found = []
    for note_id in dict.fromkeys(note_ids):  # de-duplicate, keep order
        entry = session.get(Entry, note_id)
        if entry is None or entry.is_deleted or entry.is_private:
            continue
        found.append(entry)
    return found


def _attached_documents(session: Session, document_ids: list[int]) -> list[Document]:
    """The documents the user attached by hand, in the order picked.

    No privacy/soft-delete filter here, unlike Entry, Document has neither
    field (core/database.py's own Document docstring: it's the long-form
    editor, not the notebook), so there's nothing to check beyond existing.
    """
    found = []
    for document_id in dict.fromkeys(document_ids):
        document = session.get(Document, document_id)
        if document is not None:
            found.append(document)
    return found


#: How much of one attached file's text is given to the model. A file can be a
#: 300-page PDF, and every character here is resent on every round of the turn
#: -- the same budget reasoning `MEDIA_READING_CHARS` below records. Generous
#: enough for a report or a source file, bounded enough that four of them
#: cannot fill a small local model's whole context on their own.
ATTACHED_FILE_CHARS = 12000


def _attached_files(session: Session, file_ids: list[int]) -> list[dict]:
    """The Library files the user attached, as note-shaped context rows.

    Text is extracted here rather than stored: `core.docview.extract` is the
    same call `GET /files/{id}/text` makes, so an attached spreadsheet reaches
    the model as the table the Files tab would show, and a file whose text
    cannot be read (a scanned PDF with no reader available, an image) still
    reaches it as its name and kind rather than silently as nothing -- a
    filename is a real clue, and a chip in the transcript that corresponded to
    nothing at all is the failure mode `document_ids` already shipped once.
    """
    found: list[dict] = []
    uploads = deps.get_config().uploads_dir
    for file_id in dict.fromkeys(file_ids):
        attachment = session.get(Attachment, file_id)
        if attachment is None:
            continue
        body = ""
        try:
            viewed = docview.extract(
                uploads / attachment.stored_name,
                vision_reader=vision_ocr.pdf_reader_or_none(),
            )
            body = (viewed.text or "").strip()
        except Exception:  # noqa: BLE001 - an unreadable file is still worth naming
            body = ""
        if len(body) > ATTACHED_FILE_CHARS:
            body = body[:ATTACHED_FILE_CHARS] + "\n\n[…truncated]"
        header = f"File: {attachment.filename}"
        found.append(
            {
                "id": attachment.id,
                "content": f"{header}\n\n{body}" if body else f"{header}\n\n(no readable text)",
                "category": "File",
                "attached": True,
                "connected": False,
                "match_info": None,
            }
        )
    return found


#: How much of one attached map's outline reaches the model.
#:
#: Smaller than `ATTACHED_FILE_CHARS` by an order of magnitude, on purpose: a
#: file is prose the model reads once, while an outline is *structure*, and
#: past a few hundred nodes the tree stops being context and becomes the whole
#: window: `read_mindmap`'s own `MAX_OUTLINE_NODES` makes the same call for
#: the same reason. Four maps at this cap is ~12k characters, the same ceiling
#: one attached file already has, and every character is resent on every round
#: of the turn.
ATTACHED_MAP_CHARS = 3000


def _attached_boards(session: Session, board_ids: list[int]) -> list[dict]:
    """The mind maps the user attached, as note-shaped context rows holding
    the same indented outline `read_mindmap` returns.

    **One renderer, not two.** The outline is built by calling the map tool's
    own helpers rather than by walking the tree again here: the agent, the
    export and this must not disagree about what a map says, and a second walk
    is how they come to (§9.1 lists three edge cases, a dangling parent, a
    ring, board scoping: that a second copy gets subtly differently).

    A private board is skipped in silence rather than refused. Attaching is a
    deliberate act, so this is not the guard that matters, but `read_mindmap`
    refuses a private board on the AI's behalf, and a hand-attached one
    reaching the model by a different door would make that guard decorative.
    """
    from memorymap.api.routes_whiteboard import _board_settings, _build_tree, _map_objects
    from memorymap.entry import manager as entry_manager

    found: list[dict] = []
    for board_id in dict.fromkeys(board_ids):
        entry = session.get(Entry, board_id)
        if entry is None or entry.is_deleted or entry.is_private:
            continue
        board_type, _layout = _board_settings(entry)
        title = entry_manager.extract_title(entry.content) or f"Board {board_id}"
        objects = _map_objects(session, board_id)
        lines: list[str] = []
        _outline_into(_build_tree(session, objects), 0, lines)
        outline = "\n".join(lines) if lines else "(empty: no nodes yet)"
        if len(outline) > ATTACHED_MAP_CHARS:
            outline = outline[:ATTACHED_MAP_CHARS] + "\n[…truncated]"
        found.append(
            {
                "id": board_id,
                "content": (
                    f"Mind map: {title}\n"
                    f"({len(objects)} node{'' if len(objects) == 1 else 's'}, "
                    f"laid out as a {board_type})\n\n{outline}"
                ),
                "category": "Mind map",
                "attached": True,
                "connected": False,
                "match_info": None,
            }
        )
    return found


def _outline_into(nodes: list[dict], depth: int, out: list[str]) -> None:
    """The tree as indented text, two spaces per level, one node per line.

    The same shape `ai/tools/whiteboard.py::_outline_lines` produces, minus its
    `[id N]` markers: those exist so the *model* can name a node in the next
    tool call, and an attached map is context for a question, not a handle for
    an edit. Keeping the ids would spend a third of the budget on numbers
    nothing in this path can use.
    """
    for node in nodes:
        text = node["text"] or "(untitled)"
        mark = "" if node["kind"] == "topic" else f" [{node['kind']}]"
        out.append(f"{'  ' * depth}- {text}{mark}")
        _outline_into(node["children"], depth + 1, out)


#: At most this many pictures from one note are described to the model, and at
#: most this much of each reading. A note can hold a dozen scans; the readings
#: are a *hint* about what is in the note, not a second copy of the notebook,
#: and every character here is resent on every round of the turn.
MEDIA_READINGS_PER_NOTE = 4
MEDIA_READING_CHARS = 240


def _media_readings(session: Session, content: str) -> str:
    """What the app already knows about the pictures inside a note.

    Asked directly: *"if there is an image/sketch/file in that note, can the ai
    read the captions or ocr in those attachments if they already exist??"* It
    could not. A note's content carries `/media/<filename>` references and
    nothing else: so a note whose entire point was a photographed whiteboard
    reached the model as a sentence and a link, and the caption and OCR text
    the app had already generated for that exact image sat unread in the
    database two tables away.

    "If they already exist" is the operative half, and it is why this is a
    lookup and not a pipeline: nothing here generates a caption or runs vision
    OCR. Captioning is a background job that may not have run yet, may be off,
    or may have no model to run against, and a chat turn is the worst possible
    place to start one, it would block the answer on a second model load. A
    picture with no reading yet simply contributes nothing.
    """
    filenames = _MEDIA_REF.findall(content or "")
    if not filenames:
        return ""
    # De-duplicated, in the order they appear in the note, the same order the
    # reader sees them in, so "the second diagram" means the same thing to both.
    ordered = list(dict.fromkeys(filenames))[:MEDIA_READINGS_PER_NOTE]
    rows = {
        upload.filename: upload
        for upload in session.query(MediaUpload)
        .filter(MediaUpload.filename.in_(ordered))
        .all()
    }
    lines = []
    for filename in ordered:
        upload = rows.get(filename)
        if upload is None:
            continue
        caption = (upload.caption or "").strip()
        text = (upload.vision_ocr_text or upload.ocr_text or "").strip()
        if not caption and not text:
            continue
        parts = []
        if caption:
            parts.append(f"shows {caption[:MEDIA_READING_CHARS]}")
        if text:
            parts.append(f'text in it: "{text[:MEDIA_READING_CHARS]}"')
        name = (upload.original_name or filename).strip()
        lines.append(f"- {name}: {'; '.join(parts)}")
    if not lines:
        return ""
    # Bracketed and labelled so the model can tell the app's reading of a
    # picture from the user's own words. It is evidence about the note, not
    # part of it.
    return "\n\n[Pictures in this note, as this app read them:\n" + "\n".join(lines) + "]"


def _attachment_readings(session: Session, entry_id: int) -> str:
    """What's inside the *files* attached to a note (PDFs, Office documents,
    code, plain text): `_media_readings` above's own sibling, and the gap it
    left. Asked about directly in the same spirit as that function's own
    report: a note whose entire point was an attached spreadsheet or PDF
    reached the model as a filename and nothing else, even when the note
    carrying it was hand-attached to the very question being asked.

    Same "attached notes get more, retrieved ones don't" budget
    `_media_readings` already uses, and read live rather than cached: unlike
    a caption or an OCR pass (a background job that may not have run yet),
    extraction here is `docview.extract` (core/docview.py): exactly what
    `/documents/import` and `/files/{id}/text` already pay synchronously per
    request: bounded to a handful of files on a note the user explicitly
    picked, not a background sweep over the whole notebook.
    """
    attachments = (
        session.query(Attachment)
        .filter(Attachment.entry_id == entry_id)
        .order_by(Attachment.id)
        .limit(MEDIA_READINGS_PER_NOTE)
        .all()
    )
    if not attachments:
        return ""
    uploads_dir = deps.get_config().uploads_dir
    lines = []
    for attachment in attachments:
        path = uploads_dir / attachment.stored_name
        if not path.is_file():
            continue
        try:
            viewed = docview.extract(path)
        except Exception:  # noqa: BLE001  # a bad file must not cost the answer
            continue
        text = viewed.text.strip()
        if not text:
            continue
        lines.append(f"- {attachment.filename}: {text[:MEDIA_READING_CHARS]}")
    if not lines:
        return ""
    return "\n\n[Files attached to this note, as this app read them:\n" + "\n".join(lines) + "]"


def _prepare(
    session: Session,
    question: str,
    note_ids: list[int] | None = None,
    force_notes_intent: bool = False,
    attached_notes_only: bool = False,
    document_ids: list[int] | None = None,
    file_ids: list[int] | None = None,
    board_ids: list[int] | None = None,
    surface: str = ASK_SURFACE,
) -> dict:
    """The shared first half of both chat endpoints: retrieve entries,
    bump their usage counters, log the question, gather AI settings.

    A message that isn't about the notebook skips retrieval entirely, there's
    nothing to search for, and searching anyway is what made "hey" come back
    with a list of notes.
    """
    from memorymap.api.routes_entries import _to_out  # avoids a route-module cycle

    detected = intent.classify(question)
    # `body.answering_agent` (Tier 1 §4): a reply to the agent's own question
    # is about the notebook by construction, however smalltalk-shaped the
    # reply itself reads ("yes", "ok"). Same override shape as `attached`
    # below, and the same reason: this route's job is to route what the
    # request actually is, and the client already knows.
    if force_notes_intent:
        detected = intent.NOTES
    # Attaching a note (or a document) is itself a statement that this is
    # about the notebook, so it overrides the classifier, "what do you
    # think?" with three notes clipped to it is a question about those notes.
    attached = _attached_notes(session, note_ids or [])
    attached_docs = _attached_documents(session, document_ids or [])
    attached_files = _attached_files(session, file_ids or [])
    attached_boards = _attached_boards(session, board_ids or [])
    if attached or attached_docs or attached_files or attached_boards:
        detected = intent.NOTES
    #: **A question about the notebook's shape is answered by counting it.**
    #: Asked for directly: "enhance the semantic search so it can pick up stuff
    #: like if I ask 'what are my most common tags', or maybe 'categories with
    #: the most notes'."
    #:
    #: Retrieval cannot answer those, and no amount of tuning would: semantic
    #: search finds the notes most *like* a question, and "what are my most
    #: common tags" is not like any note. It used to retrieve five arbitrary
    #: notes and tell the model to answer from those alone, so the model
    #: either declined or invented a ranking from a five-note sample.
    #:
    #: The facts are computed here, exactly, from rows. The model still writes
    #: the sentence when it is running (the answer is handed to it as ground
    #: truth below), which means the phrasing is natural and the numbers cannot
    #: be invented: and with the model stopped the computed sentence is
    #: already a complete answer on its own.
    stats = notebook_stats.answer(question, session) if detected == intent.NOTES else None
    connected_ids: set[int] = set()
    match_info: dict = {}
    when_phrase = ""
    # `attached_notes_only`: the caller has already chosen the exact, closed
    # set of notes this turn should see, running retrieval on top would only
    # add notes nobody asked for, matched against whatever the turn's own
    # instruction text happens to contain rather than anything the user
    # picked. Only takes effect when there is something attached to fall
    # back to; an empty attachment list with this flag set would otherwise
    # search nothing at all and answer from silence.
    if stats is not None:
        #: Nothing to retrieve: the answer is a count, and five notes about
        #: whatever the question sounded like would only be noise beside it.
        entries, mode = [], "stats"
    elif intent.needs_retrieval(detected) and not (attached_notes_only and attached):
        found = search_manager.retrieve_detailed(
            session, question, deps.get_embeddings(), limit=5
        )
        entries, mode = found.entries, found.mode
        # Which of these are here because they are *connected* to a match
        # rather than because they matched. The user asked about one thing and
        # is being shown notes about another; without saying why, the panel
        # looks like the search misfired, and the model, told nothing, would
        # report them as results.
        connected_ids = found.connected_ids
        match_info = found.match_info
        when_phrase = found.when_phrase
    else:
        entries, mode = [], "none"

    # Attached notes come first and are never dropped by the retrieval limit.
    # Anything retrieval also found is de-duplicated against them.
    attached_ids = {entry.id for entry in attached}
    entries = attached + [e for e in entries if e.id not in attached_ids]
    if attached:
        mode = "attached" if mode == "none" else f"attached + {mode}"

    def as_note(entry) -> dict:
        content = entry.content
        if entry.id in attached_ids:
            # Only for notes the user picked by hand. A retrieved note is a
            # candidate; an attached one is the subject of the question, and
            # that is worth the extra characters, doing this for all ten
            # search hits would spend the notes budget on pictures nobody
            # asked about.
            content = f"{content}{_media_readings(session, content)}{_attachment_readings(session, entry.id)}"
        return {
            # id lets agent-mode tool calls target these notes;
            # the plain librarian prompt simply ignores it.
            "id": entry.id,
            "content": content,
            "category": manager.category_name_for(session, entry),
            # Marked so the prompt can say which notes the user chose.
            "attached": entry.id in attached_ids,
            # …and which arrived by the graph rather than by the search. The
            # prompt renders this as a caveat, so an answer can say "you linked
            # this to the note about X" instead of implying it was a hit.
            "connected": entry.id in connected_ids,
            # Already computed (match_info feeds the frontend's own similarity/
            # hops badges) and already shown to the user, just never reached
            # the model itself before. Asked for directly: "can the ai see the
            # link reasons and similarity scores in the searches?" It's the
            # score half of that; a linked note's own reason text would need
            # tracing back to the specific Link row, a bigger change not made
            # here.
            "match_info": match_info.get(entry.id),
        }

    notes = [as_note(entry) for entry in entries]
    # Same shape `as_note` builds, by hand rather than through it, a
    # Document has no category/tags and its id lives in a different table
    # than Entry's, so folding it through the Entry-shaped helper above
    # would be the wrong abstraction, not a shortcut. `connected`/
    # `match_info` are never true for a hand-picked document, same as an
    # attached note.
    notes.extend(
        {
            "id": document.id,
            "content": f"{document.title}\n\n{document.content}",
            "category": "Document",
            "attached": True,
            "connected": False,
            "match_info": None,
        }
        for document in attached_docs
    )
    # Library files, already shaped as context rows by `_attached_files`.
    notes.extend(attached_files)
    # Mind maps, likewise: `_attached_boards` builds the outline.
    notes.extend(attached_boards)
    config = deps.get_config()
    profile = (
        config.get_preference("user_profile", "")
        if config.get_preference("profile_enabled", False)
        else ""
    )

    # Every entry this question surfaced counts as "used".
    for entry in entries:
        entry.access_count += 1
    manager.log_action(session, "queried", surface, detail=question)
    session.commit()
    logging.getLogger("memorymap.chat").info(
        "chat: %d note(s) via %s search for %r",
        len(entries),
        mode,
        # The question is the user's own text, and it reaches the terminal as
        # well as the in-app viewer, a bare %r of it can forge a log line.
        safe_value(question, 80),
    )

    return {
        "notes": notes,
        "intent": detected,
        #: The computed answer, when this was a question about the notebook's
        #: shape rather than its contents. `text` is already a complete answer
        #:, which is what makes these work with the model stopped, and the
        #: prompt below hands it to the model as ground truth rather than
        #: asking it to work the numbers out.
        "stats": (
            {"kind": stats.kind, "text": stats.text, "facts": stats.facts}
            if stats is not None
            else None
        ),
        "raw_results": [_to_out(session, entry) for entry in entries],
        "search_mode": mode,
        # Ids that came along because they are *connected* to a match, so the
        # results panel can label them rather than presenting a note about
        # something else as though the search had found it. Sent beside the
        # results rather than as a field on EntryOut: it is a fact about this
        # search, not about the note, and every other route that returns an
        # entry would otherwise carry a field that is always false.
        "connected_ids": sorted(connected_ids),
        # str() keys: match_info is keyed by entry id internally, but JSON
        # object keys are always strings and Pydantic's dict[str, dict]
        # won't silently coerce an int key for us here.
        "match_info": {str(k): v for k, v in match_info.items()},
        "when_phrase": when_phrase,
        "style": config.get_preference("communication_style", "friendly"),
        "profile": profile,
    }


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    prepared = _prepare(
        session,
        body.question,
        body.note_ids,
        attached_notes_only=body.attached_notes_only,
        document_ids=body.document_ids,
        file_ids=body.file_ids,
        board_ids=body.board_ids,
        # This endpoint has no tool loop, it retrieves and answers, nothing
        # else: so every turn through it is an ask by construction.
        surface=ASK_SURFACE,
    )
    model_manager = deps.get_model_manager()
    ollama = deps.get_ollama()
    ollama_running = ollama.is_running()
    conversational = not intent.needs_retrieval(prepared["intent"])
    mode = _resolve_mode(body.mode)
    images_raw = _resolve_chat_images(session, body.image_media_ids)
    chat_sees_images = bool(images_raw) and _chat_model_sees_images(model_manager, ollama)
    images = [uri for _, uri in images_raw] if chat_sees_images else []
    image_context = (
        "" if chat_sees_images else _image_caption_context(images_raw, model_manager, ollama)
    )
    #: A counted answer *is* an answer, and it does not need a model running to
    #: be one: which is the whole point of computing it. Without this the
    #: response would carry a correct sentence and simultaneously report that
    #: nothing had been answered.
    answered = prepared["stats"] is not None or (
        (conversational or bool(prepared["notes"]) or bool(images_raw)) and ollama_running
    )
    shared = {
        "style": prepared["style"],
        "profile": prepared["profile"],
        "history": [turn.model_dump() for turn in body.history],
        "persona_prompt": _resolve_persona(body.persona, session),
    }
    if prepared["stats"] is not None:
        #: **Counted, not generated.** The answer to "what are my most common
        #: tags" is a fact about rows, and `notebook_stats` has already written
        #: it as a sentence. Handing it to the model to rephrase would put a
        #: generator between the user and a number that is already exact, for
        #: nothing but style: and would make the one feature here that works
        #: with the model stopped depend on the model. So it is returned as it
        #: stands, instantly, whether or not anything is running.
        ai_response, ai_thinking = prepared["stats"]["text"], None
    elif conversational and body.notes_only:
        # Same rule as the streaming route: this box interrogates the
        # notebook and does not chat (§35A).
        ai_response, ai_thinking = librarian.ASK_IS_FOR_NOTES, None
    elif conversational:
        ai_response, ai_thinking = librarian.converse(
            body.question,
            prepared["intent"],
            model_manager,
            ollama,
            mode=mode,
            images=images,
            image_context=image_context,
            **shared,
        )
    else:
        ai_response, ai_thinking = librarian.answer(
            body.question,
            prepared["notes"],
            model_manager,
            ollama,
            mode=mode,
            images=images,
            image_context=image_context,
            # The Ask box (`notes_only`) gets the overview brief instead of
            # the chat one: see `librarian.ASK_OVERVIEW`.
            ask_overview=body.notes_only,
            **shared,
        )
    # Direct Q&A only: conversational replies aren't grounded in retrieved
    # notes at all (there may be none), and grounding one would attach a
    # note to a sentence that has nothing to do with it.
    sentence_grounding = (
        ground_answer_sentences(ai_response, prepared["notes"])
        if not conversational and answered
        else []
    )
    return ChatResponse(
        ai_response=ai_response,
        ai_thinking=ai_thinking,
        raw_results=prepared["raw_results"],
        search_mode=prepared["search_mode"],
        connected_ids=prepared["connected_ids"],
        match_info=prepared["match_info"],
        when_phrase=prepared["when_phrase"],
        #: **A counted answer was not answered by a model, and must not say it
        #: was.** `answered` is true for one (see its own note above) but
        #: `answered_by` names *who* wrote the sentence, and for these the
        #: honest answer is nobody, the numbers came from rows. Naming the
        #: chat model here would put its name under a sentence it never saw,
        #: which is exactly the kind of small false claim this app cannot
        #: afford to make about its own AI.
        answered_by=(
            None
            if prepared["stats"] is not None
            else (model_manager.chat_model() if answered else None)
        ),
        ollama_running=ollama_running,
        sentence_grounding=sentence_grounding,
    )


def _save_ask_turn(session: Session, question: str, answer: str, prepared: dict) -> None:
    """Durable record of one Ask-box turn, for routes_ask_history.py's browse
    panel. Only ever called for `notes_only` requests (the Ask box's own
    flag, §35A) with a real answer, a small-talk turn on that box always
    exits through the "hint" branch below instead, never reaching this call,
    so nothing here needs to re-check for that case.
    """
    session.add(
        AskTurn(
            question=question,
            answer=answer,
            raw_result_ids=json.dumps([r.id for r in prepared["raw_results"]]),
            search_mode=prepared["search_mode"],
            when_phrase=prepared["when_phrase"],
            match_info=json.dumps(prepared["match_info"]),
            connected_ids=json.dumps(prepared["connected_ids"]),
        )
    )
    session.commit()


# **"Nothing in your notes" should not be the end of the answer.**
#
# Asked for directly: "idk if the ai should be able to look for related
# semantic results for alternate items like reminders, chat sessions, docs etc
# related to the notes if no notes are found?? like similar items??"
#
# Retrieval only ever searched notes, so a question whose answer sits in a
# document, a saved chat or a reminder came back as a flat "I couldn't find
# any saved notes matching that question", true, useless, and on a notebook
# that has grown documents and chats, misleading about how much the app holds.
#
# Keyword matching on purpose rather than embeddings: this runs *only* on the
# already-empty path, where being slightly less clever costs nothing and
# another model round trip would just buy a second wait for a second
# disappointment. Workspace scoping comes from `WorkspaceMixin`, as everywhere.
_RELATED_LIMIT = 4


def _related_elsewhere(session: Session, question: str) -> list[dict]:
    """Documents, saved chats and reminders matching a question no note answered."""
    words = re.findall(r"[\w']{3,}", (question or "").lower())[:6]
    if not words:
        return []
    found: list[dict] = []

    def _add(rows, kind: str, label_of, id_of) -> None:
        for row in rows:
            if len(found) >= _RELATED_LIMIT:
                return
            found.append({"kind": kind, "id": id_of(row), "label": label_of(row)})

    # One query per kind, not one per (kind, word).
    #
    # This used to loop the six words and run three queries inside the loop,
    # so a question with six usable words cost eighteen round trips, each of
    # them an `ILIKE '%word%'` whose leading wildcard no index can serve: a
    # full scan of `documents.content` and `conversations.messages`, the two
    # widest text columns in the schema. Measured on a notebook of 2,000
    # documents, 2,000 saved chats and 2,000 reminders, 400 words of body
    # each: 139.8 ms median, on the path every chat answer takes when no note
    # answered the question. Folding the words into one OR per kind does the
    # same three scans once instead of six times.
    #
    # What changes: a document matching only the sixth word can now outrank
    # one matching the first, because the order is `updated_at` across the
    # whole match set rather than word by word. That is the better order for
    # this panel anyway (it says "related elsewhere", not "related to your
    # first noun"), and the kinds still fill in the same order, documents,
    # then chats, then reminders, so a question whose matches are all
    # documents still gets four documents.
    def _any_word(*columns):
        return or_(
            *(
                col.ilike(f"%{like_escape(word)}%", escape=LIKE_ESCAPE)
                for col in columns
                for word in words
            )
        )

    _add(
        session.scalars(
            select(Document)
            .where(_any_word(Document.title, Document.content))
            .order_by(Document.updated_at.desc())
            .limit(_RELATED_LIMIT)
        ).all(),
        "document",
        lambda d: d.title or "Untitled",
        lambda d: d.id,
    )
    _add(
        session.scalars(
            select(Conversation)
            .where(_any_word(Conversation.title, Conversation.messages))
            .order_by(Conversation.updated_at.desc())
            .limit(_RELATED_LIMIT)
        ).all(),
        "chat",
        lambda c: c.title or "Untitled chat",
        lambda c: c.id,
    )
    _add(
        session.scalars(
            select(Reminder)
            .where(_any_word(Reminder.text))
            .order_by(Reminder.due_at.desc())
            .limit(_RELATED_LIMIT)
        ).all(),
        "reminder",
        lambda r: r.text,
        lambda r: r.id,
    )
    # De-duplicated on (kind, id): one word matching a document's title and
    # another matching its body would otherwise list it twice.
    seen: set[tuple[str, int]] = set()
    unique: list[dict] = []
    for item in found:
        key = (item["kind"], item["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:_RELATED_LIMIT]




@router.post("/stream")
def chat_stream(body: ChatRequest, session: Session = Depends(get_session)):
    """NDJSON stream. Line types, in order:
    {"type":"status", "stage": "searching"}   (sent immediately, so the
        browser gets a first byte at once instead of waiting on the, often
        cold-start: semantic search; this is what keeps the UI's typing
        indicator alive instead of appearing frozen)
    {"type":"meta", raw_results, search_mode, answered_by}
    {"type":"thinking", "delta": "..."}   (zero or more)
    {"type":"answer", "delta": "..."}     (one or more)
    {"type":"done"}
    """
    ollama = deps.get_ollama()
    model_manager = deps.get_model_manager()
    history = [turn.model_dump() for turn in body.history]
    persona_prompt = _resolve_persona(body.persona, session)
    mode = _resolve_mode(body.mode)
    images_raw = _resolve_chat_images(session, body.image_media_ids)
    chat_sees_images = bool(images_raw) and _chat_model_sees_images(model_manager, ollama)
    images = [uri for _, uri in images_raw] if chat_sees_images else []
    image_context = (
        "" if chat_sees_images else _image_caption_context(images_raw, model_manager, ollama)
    )
    use_tools = (
        body.use_tools
        if body.use_tools is not None
        else bool(deps.get_config().get_preference("tools_enabled", True))
    )
    # A skill run replaces the question with the skill's own instruction: 
    # steps, values and declared tools included, and narrows the toolbox to
    # what it declared. Retrieval runs on that instruction too, so a skill
    # gets the notes its own words find rather than the ones the chip's label
    # happens to match.
    # A plan run goes down exactly the same path as a skill run, the runner
    # cannot tell them apart, which is what gives a plan the ticked steps, the
    # change list and the Undo on each without a second implementation.
    skill = _resolve_skill(body) or _resolve_plan(body)
    question = skill["question"] if skill else body.question
    allowed_tools = skill["tools"] if skill else None
    if skill and skill["acts"]:
        # An action skill without tools is just a paragraph, so the route
        # insists whatever the caller asked for. The frontend now switches the
        # mode itself before it sends (INBOX 39: it announces the switch and
        # leaves it switched), so in the app this branch no longer changes
        # anything; it stays because the API is public and a caller that posts
        # `use_tools: false` with an action skill still means the skill.
        use_tools = True

    def plain_events(prepared: dict, ollama_running: bool) -> Iterator[dict]:
        """The pre-Wave-G behaviour: stream a grounded answer, no tools."""
        if prepared["stats"] is not None:
            #: **A counted answer, streamed as one piece.** See the same branch
            #: in `chat()`: the number is already exact and already a sentence,
            #: so there is nothing to generate and nothing to wait for. It
            #: arrives before a local model would have finished loading, and it
            #: arrives at all when no model is running.
            yield {"type": "answer", "delta": prepared["stats"]["text"]}
            return
        conversational = not intent.needs_retrieval(prepared["intent"])
        if conversational and body.notes_only:
            # The Notes tab's Ask box has one job (§35A). A greeting is the one
            # input it has nothing to do with, so it says what it is for rather
            # than spending a model round chatting back.
            #
            # Its own event type, not an "answer". Reported after the first
            # version shipped: a paragraph of instructions sitting where the
            # answer goes, beside a results panel reading "No matching
            # records", reads as the app having failed. As a hint the client
            # can render it as what it is, a prompt with questions you can
            # click: and can leave the empty results panel out, since nothing
            # was searched for.
            yield {
                "type": "hint",
                "text": librarian.ASK_IS_FOR_NOTES,
                "examples": librarian.ASK_EXAMPLES,
            }
            return
        if conversational:
            # Small talk: no notes, no grounding, no "I couldn't find any
            # notes matching that" in reply to "hey".
            if not ollama_running:
                offline = (
                    librarian.OFFLINE_ABOUT_APP
                    if prepared["intent"] == "about_app"
                    else librarian.OFFLINE_SMALLTALK
                )
                yield {"type": "answer", "delta": offline}
                return
            messages = librarian.build_conversational_messages(
                f"{question}\n\n{image_context}" if image_context else question,
                prepared["intent"],
                style=prepared["style"],
                profile=prepared["profile"],
                history=history,
                persona_prompt=persona_prompt,
                mode=mode,
                images=images,
            )
        elif not prepared["notes"] and not images_raw:
            # An attached image and "no matching notes" are unrelated: 
            # retrieval never sees the image, so an empty search result
            # must not stand in for "there's nothing to look at" (same fix
            # as `librarian.answer`'s own guard).
            yield {"type": "answer", "delta": librarian.NO_RESULTS_MESSAGE}
            # …but the notebook is more than its notes. See
            # `_related_elsewhere`: a question answered by a document, a saved
            # chat or a reminder used to end here regardless.
            related = _related_elsewhere(session, question)
            if related:
                kinds = sorted({item["kind"] for item in related})
                yield {
                    "type": "answer",
                    "delta": (
                        " There "
                        + ("is" if len(related) == 1 else "are")
                        + f" {len(related)} other "
                        + ("item" if len(related) == 1 else "items")
                        + " that mention it, in your "
                        + " and ".join(f"{k}s" for k in kinds)
                        + "."
                    ),
                }
                yield {"type": "related", "items": related}
            return
        elif not ollama_running:
            yield {"type": "answer", "delta": librarian.OFFLINE_MESSAGE}
            return
        else:
            messages = librarian.build_messages(
                f"{question}\n\n{image_context}" if image_context else question,
                prepared["notes"],
                style=prepared["style"],
                profile=prepared["profile"],
                history=history,
                persona_prompt=persona_prompt,
                mode=mode,
                images=images,
                # The streaming path is the one people actually use, and it was
                # the one with no cap on how much of the notebook it sent. Same
                # budget the blocking `librarian.answer` now builds: measured
                # against the model this turn will really stream from, which is
                # the same `chat_model()` passed to `chat_stream` below.
                budget=librarian.plan_budget(
                    model_manager.chat_model(),
                    ollama,
                    prepared["style"],
                    prepared["profile"],
                    persona_prompt,
                    mode,
                ),
                # The Ask box's own brief on the streaming path too, this is
                # the one people actually use, so a fix only on the blocking
                # route above would be a fix nobody sees.
                ask_overview=body.notes_only,
            )
        # §88.4 item 4: the same per-stage token estimate agent.py's tool
        # path now attaches to its own stats event (chars/4, no tool
        # schemas on this path by definition, see build_messages' own
        # docstring above). Computed once, not per streamed chunk.
        composition_tokens = {
            "system": len(messages[0]["content"]) // context.CHARS_PER_TOKEN,
            "history": sum(len(m["content"]) for m in messages[1:-1]) // context.CHARS_PER_TOKEN,
            "notes": len(messages[-1]["content"]) // context.CHARS_PER_TOKEN,
            "tool_schemas": 0,
        }
        streamed_any = False
        try:
            for piece in ollama.chat_stream(model_manager.chat_model(), messages, mode):
                if "thinking_delta" in piece:
                    yield {"type": "thinking", "delta": piece["thinking_delta"]}
                elif "stats" in piece:
                    # Token counts + timings for the message metadata line.
                    yield {"type": "stats", **piece["stats"], "composition": composition_tokens}
                else:
                    streamed_any = True
                    yield {"type": "answer", "delta": piece["content_delta"]}
        except OllamaError as exc:
            # The model died mid-answer, tell the user, keep the results.
            # By construction this is reached only after the `elif not
            # ollama_running` branch above already passed, so this is never
            # "Ollama isn't running" (see librarian.model_error_message's
            # own docstring for why that distinction matters).
            #
            # Logged, not just shown in the answer: reported directly: this
            # failure reached the chat bubble but never the Settings → Logs
            # viewer, since nothing here ever routed it through `logging` at
            # all. The exception is already fully described in the message
            # this yields; logging it is what makes it show up in the one
            # place the caveat at the top of CLAUDE.md says to check first.
            logging.getLogger("memorymap.chat").warning(
                "chat: model call failed for %r: %s", model_manager.chat_model(), exc
            )
            prefix = "\n\n" if streamed_any else ""
            yield {
                "type": "answer",
                "delta": f"{prefix}{librarian.model_error_message(model_manager.chat_model(), exc)}",
            }

    def lines() -> Iterator[str]:
        def event(payload: dict) -> str:
            return json.dumps(payload) + "\n"

        # Flush a first byte immediately. The semantic search below can be a
        # slow cold start (loading the embedding model, warming the index);
        # emitting this now means the browser's stream opens right away and
        # its "typing…" indicator keeps animating instead of looking frozen
        # while the whole request blocks (user-reported lag).
        yield event({"type": "status", "stage": "searching"})

        # Retrieval happens INSIDE the stream now, not before it, that's the
        # whole latency win. Nothing before this line touches the model.
        prepared = _prepare(
            session,
            question,
            body.note_ids,
            force_notes_intent=body.answering_agent,
            attached_notes_only=body.attached_notes_only,
            document_ids=body.document_ids,
            file_ids=body.file_ids,
            board_ids=body.board_ids,
            # Asking vs requesting, decided from what the caller can already
            # do rather than from a new flag: `notes_only` is the Notes tab's
            # Ask box, and tools-off is the Chat tab's Ask mode. Anything that
            # can reach for a tool, Request mode, the palette, a skill or plan
            # run: is a request. `use_tools` is resolved above, so the saved
            # preference is accounted for and an unset flag cannot land a
            # Request turn in the chip row.
            surface=ASK_SURFACE if (body.notes_only or not use_tools) else AGENT_SURFACE,
        )
        ollama_running = ollama.is_running()
        # In agent mode the model can act even when nothing matched, "save a
        # note about X" must work on an empty notebook.
        will_answer = ollama_running and (
            bool(prepared["notes"])
            or bool(images_raw)
            or use_tools
            or not intent.needs_retrieval(prepared["intent"])
        )

        yield event(
            {
                "type": "meta",
                "raw_results": [r.model_dump(mode="json") for r in prepared["raw_results"]],
                "search_mode": prepared["search_mode"],
                "connected_ids": prepared["connected_ids"],
                "match_info": prepared["match_info"],
                "when_phrase": prepared["when_phrase"],
                "answered_by": model_manager.chat_model() if will_answer else None,
                "ollama_running": ollama_running,
            }
        )

        events: Iterator[dict] = plain_events(prepared, ollama_running)
        # Small talk never goes near the agent: "hey" is not a request to do
        # anything, and handing it a toolbox invites it to invent an errand.
        if ollama_running and use_tools and intent.needs_retrieval(prepared["intent"]):
            shared = {
                "style": prepared["style"],
                "profile": prepared["profile"],
                "history": history,
                "persona_prompt": persona_prompt,
            }
            if skill:
                # A skill runs step by step, the runner emits the plan, ticks
                # each step, and ends with what changed. Its first event has
                # the same meaning as the agent's, so the fallback below is
                # unchanged.
                agent_events = skill_runner.run_skill(
                    session,
                    skill["skill"],
                    body.skill_inputs or {},
                    prepared["notes"],
                    model_manager,
                    ollama,
                    start_at=body.skill_from_step,
                    manual=body.skill_manual,
                    manual_note=body.skill_manual_note,
                    small_model=_small_model_mode(),
                    # The run's own budget (Brief 13), read from the user's
                    # settings here rather than inside the runner so that the
                    # runner stays testable without app state and so a caller
                    # with its own budget (an eval, a background job) can pass
                    # one instead.
                    budget=run_budget.from_settings(deps.get_config()),
                    **shared,
                )
            else:
                agent_events = agent.run_agent(
                    session,
                    question,
                    prepared["notes"],
                    model_manager,
                    ollama,
                    mode=mode,
                    allowed_tools=allowed_tools,
                    images=images,
                    image_context=image_context,
                    **shared,
                )
            # Everything `agent.run_agent`/`skill_runner.run_skill` themselves
            # expect to go wrong (OllamaError, ToolsUnsupportedError) is
            # already caught inside them and turned into a real event, this
            # is the outer boundary, for whatever isn't. Reported directly: a
            # skill run that "failed before even completing the first step
            # ... no answer and no tool call", an exception here had nothing
            # catching it, so it killed the generator and the stream just
            # ended with nothing rendered, no error, the plan card (if any)
            # never even reaching the page. Silence was the bug, not the
            # underlying failure, which is why this doesn't try to guess
            # which failure it was, it says what actually happened and stays
            # on stage instead of vanishing.
            try:
                first = next(agent_events, None)
            except Exception as exc:  # noqa: BLE001  # the outer boundary
                logging.getLogger("memorymap.chat").exception(
                    "%s: unhandled error before the first event: %s",
                    "skill run" if skill else "agent turn",
                    exc,
                )
                first = {
                    "type": "answer",
                    "delta": f"Something went wrong before it could start: {exc}",
                }
            if first is None or first.get("type") == "unsupported":
                # The active model can't do tool calls, plain Q&A, never
                # a hard dependency.
                pass
            else:
                events = chain([first], agent_events)
        # ROADMAP.md item 36's frontend half: the non-streaming /chat already
        # grounds its answer, but the live Ask box only ever calls this
        # streaming route. Accumulated here (not computed per-delta: the
        # sentence splitter needs the whole answer, and this is a handful of
        # deltas' worth of string concatenation, not a hot loop) and sent as
        # its own event once the answer is fully in, direct-Q&A only.
        answer_text = ""
        # Every note a tool read during the turn is a grounding candidate,
        # not only the retrieval set. Reported: an agent answer that named
        # three notes cited one, and a skill run cited none. The retrieval
        # set is what the *search* found before the model started; in
        # Agent mode and in a skill run the model then reads notes of its
        # own choosing through `get_note`, `search_notes`, `related_notes`,
        # and those are exactly the notes its answer is about. `touched` on
        # each tool event already names them (it is what the transcript's
        # action line opens), so this collects ids and loads the text once,
        # after the answer is in.
        touched_note_ids: list[int] = []
        # **A blank line wherever the transcript starts a new paragraph.**
        #
        # Measured while fixing INBOX 40. A multi-round turn (an agent answer,
        # every skill run) emits its prose in bursts with a step or a tool
        # call between them, and the client draws each burst as its own block
        # (`agentTimeline.startAnswer`, and `timeline.text()` joins them with
        # a blank line). Concatenating the raw deltas here instead glued the
        # last sentence of one round to the first of the next: "…in it.I
        # checked…". `split_sentences` splits on `.` followed by whitespace,
        # so that pair is one unsplittable "sentence" that exists in no
        # paragraph on screen: the grounding row it produces can never be
        # found by the client's citation walker, and both real sentences lose
        # their marker. On a nine-step run the whole answer collapsed into a
        # single such sentence and the run cited nothing at all, which is
        # exactly what was reported.
        #
        # The set below is the events that begin a new prose block in the
        # transcript, so this string keeps the same shape as what the reader
        # sees. Anything else (`meta`, `token`, `stats`) is bookkeeping and
        # must not break a paragraph in half.
        paragraph_breaks = {"thinking", "tool", "step", "plan", "result"}
        in_prose = False
        try:
            for payload in events:
                kind = payload.get("type")
                if kind == "answer":
                    if answer_text and not in_prose:
                        answer_text += "\n\n"
                    answer_text += payload.get("delta") or ""
                    in_prose = True
                elif kind in paragraph_breaks:
                    in_prose = False
                    if kind == "tool":
                        for item in payload.get("touched") or []:
                            if item.get("kind") == "note" and isinstance(item.get("id"), int):
                                touched_note_ids.append(item["id"])
                yield event(payload)
        except Exception as exc:  # noqa: BLE001  # same outer boundary as above,
            # for a failure that shows up partway through rather than before
            # the first event (a later skill step, say). Same fix: say what
            # happened instead of the stream just stopping.
            logging.getLogger("memorymap.chat").exception(
                "%s: unhandled error mid-stream: %s",
                "skill run" if skill else "agent turn",
                exc,
            )
            # CodeQL: "information exposure through an exception" (#296): 
            # `exc`'s own str() is untrusted and can embed a file path or
            # connection detail; same sanitiser librarian.model_error_message
            # already trusts for this exact shape.
            yield event({"type": "answer", "delta": f"\n\nSomething went wrong: {safe_value(exc)}"})
        conversational = not intent.needs_retrieval(prepared["intent"])
        candidates = _grounding_candidates(session, prepared["notes"], touched_note_ids)
        if not conversational and candidates and answer_text:
            grounding = ground_answer_sentences(answer_text, candidates)
            if grounding:
                # A touched note is not in `raw_results`, so the client has
                # no text to name it by; the label rides on each entry.
                labels = {
                    note["id"]: " ".join(str(note.get("content") or "").split())[:60]
                    for note in candidates
                }
                for row in grounding:
                    row["label"] = labels.get(row["note_id"], "")
                yield event({"type": "grounding", "sentences": grounding})
        if body.notes_only and answer_text:
            _save_ask_turn(session, question, answer_text, prepared)
        yield event({"type": "done"})

    # X-Accel-Buffering: no tells reverse proxies (nginx) not to buffer the
    # stream, so tokens reach the browser as they're produced.
    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/modes")
def list_modes() -> dict:
    """The response presets, and which one is currently the default (§11).

    Served rather than hard-coded in `app.js` so the picker cannot drift from
    what the server actually does, adding a fourth preset is then a change to
    `ai/presets.py` alone.
    """
    return {
        "modes": [
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
            }
            for preset in presets.MODES.values()
        ],
        "active": _resolve_mode(None),
    }


@router.get("/tools")
def list_tools() -> list[dict]:
    """The agent-tool catalog for Settings → Tools toggles."""
    return tools.tool_catalog()


# --- compressing a long conversation (§35I) -----------------------------------
#
# Asked for directly: *"there should be a tool as well as a manual command or
# something to be able to compress chat context on longer chats so the AI can
# better continue."*
#
# What happens today without it is worth stating plainly, because it is not
# "the request gets big", the client sends at most the last four turns and
# `context.fit_history` drops whole pairs from the *oldest* end until the rest
# fits. So a long conversation does not overflow; it silently forgets its own
# beginning, and the model starts re-asking things it was told an hour ago.
#
# A summary is strictly better than a drop: the same few hundred characters
# carry the gist of ten turns instead of the whole of one. And it is the
# **manual** half that shipped first, exactly as §35I argued, a button the
# user presses, whose output they can read before it is used, cannot misfire.
#
# §37I: the tool that lets the agent do it unprompted (`compress_chat` in
# ai/tools.py) shares this endpoint's summarising logic via
# `tools.summarise_turns`, and keeps the same human-review step, the model's
# turn ends and `showCompressReview` renders exactly the panel this endpoint
# already feeds, so a summary the agent asked for is never applied unread any
# more than one this button produced would be.

#: Turns to summarise in one call. Beyond this the summary itself gets long
#: enough to be worth summarising, which is the wrong direction. Re-exported
#: from ai/tools.py, the one place the ceiling is defined, so this route and
#: the agent's own compress_chat tool can't drift to different limits.
MAX_COMPRESS_TURNS = tools.MAX_COMPRESS_TURNS


class CompressBody(BaseModel):
    """The turns to summarise, oldest first."""

    history: list[ChatTurn] = Field(min_length=1, max_length=MAX_COMPRESS_TURNS)


@router.post("/compress")
def compress_history(body: CompressBody) -> dict:
    """A summary of these turns, for sending in place of them.

    Returns the text and nothing else, the client decides whether to use it,
    and keeps the original turns either way. Nothing is stored here, and the
    conversation on screen is not touched: this is a *lossless* operation as
    far as the transcript is concerned, and only the model's view narrows.
    """
    try:
        return tools.summarise_turns([(t.question, t.answer) for t in body.history])
    except OllamaError as exc:
        # Offline, or the call itself failed, either way there is no summary
        # to show, distinct from the model answering with nothing (below).
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except tools.ToolError as exc:
        # An empty reply. Better to say nothing happened than to hand back an
        # empty summary the client would send in place of ten real turns.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class ToolExecuteBody(BaseModel):
    """A tool call the user approved in the UI (confirm step)."""

    name: str
    arguments: dict = Field(default_factory=dict)


@router.post("/tools/execute")
def execute_confirmed_tool(
    body: ToolExecuteBody, session: Session = Depends(get_session)
) -> dict:
    """Run one registry tool, how the UI executes a destructive call
    after the user clicks Confirm. Only registry tools can run, and the
    result carries the same human label shown in chat."""
    if body.name not in tools.TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{body.name}'")
    result = tools.execute_tool(session, body.name, body.arguments)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
