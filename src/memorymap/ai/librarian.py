"""The librarian: answers a question using retrieved notes (LLM prompt #2).

Strictly read-only: it never writes to the database.
When the chat model is unavailable the caller still gets a friendly
sentence, never an exception, because the raw results are shown anyway.
"""

from __future__ import annotations

from memorymap.ai import context
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import OllamaClient, OllamaError
from memorymap.core.logbuffer import safe_value

OFFLINE_MESSAGE = (
    "The AI answer isn't available right now (Ollama doesn't seem to be "
    "running), but here are the notes that match your question."
)
NO_RESULTS_MESSAGE = "I couldn't find any saved notes matching that question."


def model_error_message(model: str, error: Exception) -> str:
    """What to show when the model call itself failed mid-turn, distinct
    from OFFLINE_MESSAGE, and never a substitute for it.

    Reported directly, and confirmed by tracing the exact code path: a turn
    that failed *after* the liveness check already passed (`ollama.is_running()`
    succeeded, so the model name and a real elapsed time show in the message
    metadata line) was still shown OFFLINE_MESSAGE, "Ollama doesn't seem to
    be running", which is simply false in that case and reads as an
    accusation against the model or Ollama itself when the real cause could
    be anything a live backend can reject a request for (the model tag isn't
    actually pulled, a template/architecture the backend can't run, a
    malformed request). OFFLINE_MESSAGE stays exactly what it was for the
    one place that's actually true: the `ollama_running` check itself came
    back negative, before any model was ever named. This is for every other
    failure, and says what actually happened instead of guessing.

    `error` is interpolated through `safe_value` (CodeQL: "information
    exposure through an exception") rather than straight into the string.
    `OllamaError`'s own message is already a controlled f-string, not a raw
    traceback, but the object reaching this function is typed as the base
    `Exception`, some standard-library exceptions embed things in their own
    `str()` that don't belong in a message shown back to whoever is running
    this session (a file path, a connection detail), and there is nothing
    here that verifies which subclass actually arrived. Same sanitiser the
    Settings -> Logs viewer already trusts for exactly this: strip control
    characters that could forge a rendered line, cap the length so one huge
    message can't dominate the reply."""
    return (
        f"The model ({model}) couldn't answer this: "
        f"{safe_value(error)}"
    )

# The persona is WHO the assistant is; the grounding is non-negotiable
# and survives any persona swap, answers always come from the notes.
DEFAULT_PERSONA = "You are the librarian of the user's personal notebook."
GROUNDING = (
    "Answer the user's question in plain English using ONLY the notes "
    "provided. If the notes don't answer the question, say so honestly."
)
SYSTEM_PROMPT = f"{DEFAULT_PERSONA} {GROUNDING}"

# **The Ask box is not a chat turn, and answering it like one is the report.**
# Reported directly: "in the ask tab, the ai needs to summarise the notes, not
# offer to do more as that isnt what the tab is for, it isnt a chatbot but
# providing an ai overview and search result like perplexity for the user's
# notes."
#
# `GROUNDING` alone produces a perfectly grounded answer in the wrong *shape*:
# it ends "Would you like me to…", because that is what a chat assistant does
# and nothing had told this surface it isn't one. The results panel beside the
# answer already offers every follow-up the user could want, opening a note,
# a similar note, the note's own links: so an offer to do more here is a
# question the UI has already answered, taking up the space the overview
# should be using.
ASK_OVERVIEW = (
    "You are writing a research overview of the user's own notes, not having "
    "a conversation. Summarise and synthesise what the notes below actually "
    "say about the question: lead with the answer, group related points, and "
    "name what the notes cover and what they leave out. Use ONLY these notes. "
    "Do NOT end by offering to do anything else, do NOT ask what they would "
    "like next, and do NOT suggest chatting further, the results beside your "
    "answer already link every note you drew on. If the notes do not answer "
    "the question, say exactly that and say what they do cover instead."
)

# GROUNDING is right for a question about the notebook and wrong for anything
# else: it's what turned "hey" into a summary of your notes. Conversational
# messages get their own brief instead, and never see retrieved notes.
CONVERSATIONAL = (
    "This message is small talk, not a question about the notebook. Reply the "
    "way a helpful assistant would: one or two short sentences, warm and "
    "natural. Do NOT list, summarise, or mention the user's notes unless they "
    "ask. Don't offer a menu of features. If a nudge fits, at most one short "
    "question about what they'd like to do."
)

# What the app can actually do, for "what can you do?". Kept as prose the model
# puts in its own words rather than a list it recites verbatim.
CAPABILITIES = (
    "You help the user work with their personal notebook. You can: find and "
    "summarise notes they've written; create, edit, tag, categorise and delete "
    "notes; set and list reminders; look at their tags and categories; and "
    "search the web when they've turned that on. The app also has a graph view "
    "of how notes connect, a dashboard, and a chat that remembers the "
    "conversation."
)
ABOUT_APP_BRIEF = (
    "The user is asking what you can do, not asking about their notes. Answer "
    "from the capability description below, in your own words, in a few short "
    "sentences. Don't recite it as a list of every item, and don't mention any "
    "of their actual notes."
)

# Built-in personas. Users add their own in Settings → Personas.
BUILTIN_PERSONAS = [
    {"name": "Librarian", "prompt": DEFAULT_PERSONA},
    {
        "name": "Coach",
        "prompt": (
            "You are an encouraging personal coach reviewing the user's "
            "notes. Spot patterns, celebrate progress, and suggest one "
            "concrete next step."
        ),
    },
    {
        "name": "Analyst",
        "prompt": (
            "You are a precise analyst. Extract the facts, numbers, and "
            "patterns from the notes and organise your answer clearly."
        ),
    },
]

def resolve_persona_prompt(name: str | None, config) -> str | None:
    """Persona name → its system prompt.

    The user's saved list wins over the built-ins (that's how editing a
    built-in works: the edit is stored as an override; deleting the override
    resets it). Unknown names fall back to the default persona. Shared by the
    chat routes, the dashboard greeting, and chat auto-naming, so the voice the
    user picked is used consistently everywhere.
    """
    wanted = name or config.get_preference("active_persona", "Librarian")
    custom = config.get_preference("personas", [])
    for persona in list(custom) + BUILTIN_PERSONAS:
        if persona.get("name") == wanted and persona.get("prompt"):
            return persona["prompt"]
    return None


# The user's communication-style preference tweaks the tone.
STYLE_HINTS = {
    "friendly": "Be warm and conversational. Keep it brief.",
    "concise": "Be as brief as possible, bullet points are fine.",
    "detailed": "Be thorough: mention every relevant note and add context.",
}


def length_hint(mode: str | None) -> str:
    """How long the answer should be, as a sentence the model can follow (§11).

    Separate from `STYLE_HINTS` on purpose, because they answer different
    questions and are set in different places: style is a standing preference
    about *voice* ("be warm", "be terse"), and this is a per-turn choice about
    *effort*. Someone whose style is "friendly" can still want one quick answer.

    The reply cap alone would not do this job. A cap truncates mid-sentence,
    which reads as a crash; the hint is what makes the model produce a short
    answer that *ends*.
    """
    from memorymap.ai import presets

    return presets.resolve(mode).length_hint


# Follow-up memory (Round 1): keep the conversation short enough that a
# small local model never runs out of context. Only recent turns matter,
# and a long past answer gets clipped.
MAX_HISTORY_TURNS = 4
MAX_HISTORY_ANSWER_CHARS = 600
# Except the answer being followed up on. "Now save that as a note" refers
# to the answer just given, and a 600-character stump of it was what got
# saved: the *most recent* answer keeps enough of itself that "that" means
# what the user watched being written. Reported as "difficult to get the
# agent to explain something, and then make it as a note".
LAST_ANSWER_CHARS = 4_000


def history_messages(history: list[dict] | None) -> list[dict]:
    """The recent turns as chat messages, oldest first.

    One clipping rule for every chat path, conversational, grounded and
    agent: so a follow-up behaves the same wherever it lands: old answers
    are clipped hard, the latest one travels nearly whole (see
    LAST_ANSWER_CHARS).
    """
    recent = [
        turn
        for turn in (history or [])[-MAX_HISTORY_TURNS:]
        if str(turn.get("question", "")).strip()
        and str(turn.get("answer", "")).strip()
    ]
    messages: list[dict] = []
    for i, turn in enumerate(recent):
        limit = (
            LAST_ANSWER_CHARS if i == len(recent) - 1 else MAX_HISTORY_ANSWER_CHARS
        )
        messages.append({"role": "user", "content": str(turn["question"]).strip()})
        messages.append(
            {"role": "assistant", "content": str(turn["answer"]).strip()[:limit]}
        )
    return messages

# How much of a note goes into the prompt before it is cut short. Most notes
# are a line or two and are never touched by this; a few are pages, and those
# few would otherwise crowd out the rest of the notebook, the whole point of
# retrieving ten notes is that the model sees ten of them.
#
# Cutting is only safe because the model can undo it: `get_note` reads one in
# full, and the tools guide already tells it to before quoting. That is the
# trade, send a short form, let it ask for the original, and it is the one
# idea worth taking from the compression tooling that keeps being suggested
# (see ROADMAP §11).
MAX_NOTE_CHARS = 900

# The same cut, for a turn with no tools on the wire, the Notes tab's Ask box.
#
# Reported (§35A): "the notes that come up in the semantic search that are
# given to the ai when asked smth in the ask section are cut off or truncated."
# They were, and the escape hatch above did not exist there: a clipped note
# said "call get_note(12) to read it in full" to a model that had been offered
# no tools at all, so the missing text was simply missing and the instruction
# was noise.
#
# Two things follow. The marker has to stop naming a tool that isn't there,
# and the allowance can be much larger, because this turn is not paying for
# any tool schemas: the ~1,400-2,500 tokens the agent spends on those is
# budget the Ask box has and was not using. Five notes at this size is still
# far inside the window `ai/context.py` rations for them.
UNTOOLED_NOTE_CHARS = 2_400


def note_for_prompt(note: dict, limit: int = MAX_NOTE_CHARS, can_fetch: bool = True) -> str:
    """A note's text, short enough to sit beside nine others.

    `can_fetch` says whether the model has `get_note` available. It changes
    only the marker, and the marker is the whole difference between a cut the
    model can undo and a hole it cannot see the shape of.
    """
    content = str(note.get("content", ""))
    if len(content) <= limit:
        return content
    note_id = note.get("id")
    if can_fetch and note_id:
        # Naming the tool and the id: a truncation the model cannot act on is
        # just a missing piece of the note.
        where = f", call get_note({note_id}) to read it in full"
    else:
        # No tools this turn. Say it is cut and say nothing about fixing it,
        # so the model reports the gap instead of promising to look.
        where = ", the rest is in the note itself"
    return f"{content[:limit].rstrip()}… [cut{where}]"


def build_conversational_messages(
    question: str,
    intent: str,
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    mode: str | None = None,
    images: list[str] | None = None,
) -> list[dict]:
    """Prompt for a message that isn't about the notebook.

    Same persona and history as a normal answer, so it still sounds like the
    assistant the user chose, but no notes, and no instruction to ground the
    reply in them.
    """
    persona = (persona_prompt or DEFAULT_PERSONA).strip()
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["friendly"])
    profile_hint = f" About the user: {profile.strip()}" if profile.strip() else ""
    if intent == "about_app":
        brief = f"{ABOUT_APP_BRIEF}\n\nWhat you can do: {CAPABILITIES}"
    else:
        brief = CONVERSATIONAL
    messages = [
        {
            "role": "system",
            "content": f"{persona} {brief} {style_hint}{profile_hint}{length_hint(mode)}",
        }
    ]
    messages.extend(history_messages(history))
    user_message = {"role": "user", "content": question}
    if images:
        user_message["images"] = images
    messages.append(user_message)
    return messages


def _match_info_hint(match_info: dict | None) -> str:
    """" (similarity: 0.81)" or " (matched: gym, membership)", a short,
    honest note on *why* this result showed up, the same reasoning the
    "(attached by me)"/"(not a match)" flags beside it already use: told
    nothing, the model has no way to weigh a strong semantic match against
    a loose keyword one, or a borderline result the relative-floor logic
    only just let through."""
    if not match_info:
        return ""
    if match_info.get("type") == "semantic" and "score" in match_info:
        return f" (similarity: {match_info['score']})"
    if match_info.get("type") == "keyword" and match_info.get("terms"):
        return f" (matched: {', '.join(match_info['terms'][:5])})"
    if match_info.get("type") in ("connected", "connected_2hop") and match_info.get("reason"):
        # search_manager._retrieve already traces a connected note back to
        # the specific EntryLink row and its `reason` text: it just never
        # reached this render function. Asked for directly ("can the ai see
        # the link reasons... in the searches?"); the similarity-score half
        # of that question was answered already (the branches above), this
        # is the other half.
        return f" (why: {match_info['reason']})"
    return ""


def system_content(
    style: str = "friendly",
    profile: str = "",
    persona_prompt: str | None = None,
    mode: str | None = None,
    ask_overview: bool = False,
) -> str:
    """The system message, on its own.

    Pulled out of `build_messages` so `plan_budget` below can *measure* it
    rather than estimate it. `context.plan` takes `system_chars` precisely
    because the persona is user-editable, a long custom persona genuinely
    does leave less room for notes and history, and a budget built against an
    assumed persona length is a budget that drifts over on exactly the
    notebooks that have one.
    """
    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["friendly"])
    # The profile is context about the user, never an instruction source.
    profile_hint = f" About the user: {profile.strip()}" if profile.strip() else ""
    persona = (persona_prompt or DEFAULT_PERSONA).strip()
    # `ASK_OVERVIEW` replaces `GROUNDING` rather than being added to it: both
    # say "use only these notes", and a prompt that says it twice in different
    # words is two chances for a small model to weigh them against each other.
    brief = ASK_OVERVIEW if ask_overview else GROUNDING
    return f"{persona} {brief} {style_hint}{profile_hint}{length_hint(mode)}"


def plan_budget(
    model: str,
    ollama: OllamaClient,
    style: str = "friendly",
    profile: str = "",
    persona_prompt: str | None = None,
    mode: str | None = None,
) -> "context.ContextBudget":
    """This turn's share-out of `model`'s window, for the untooled path.

    A mirror of the block at the top of `agent.answer_with_tools`, kept as a
    function here because two callers need it, `answer` below and
    routes_chat's streaming path: and the version that was inlined in the
    agent is precisely the one that never made it to this side.

    `usable_context` is asked for defensively: it is part of the provider
    interface, but a fake or a future backend may not carry it, and the
    fallback window is a working turn where an AttributeError is a 500.
    """
    report = getattr(ollama, "usable_context", None)
    window = report(model) if callable(report) else None
    return context.plan(
        window or OllamaClient.DEFAULT_CONTEXT_TOKENS,
        len(system_content(style, profile, persona_prompt, mode)),
    )


def build_messages(
    question: str,
    notes: list[dict],
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    mode: str | None = None,
    images: list[str] | None = None,
    budget: "context.ContextBudget | None" = None,
    ask_overview: bool = False,
) -> list[dict]:
    """The librarian's prompt: shared by the blocking and streaming
    chat endpoints so they can never drift apart.

    `history` is prior [{"question", "answer"}] turns, replayed as
    user/assistant messages so follow-ups ("and what about…") keep
    context. The freshly retrieved `notes` still ground the current
    answer, so a follow-up searches the notebook anew.

    `budget` is what stops this prompt overrunning the model's window.
    ``ai/context.py`` was written for exactly this and then only ever wired
    into ``agent.build_agent_messages``, this path, which is what "Ask the
    Librarian" and the Notes Ask box use, had *no total cap of any kind*. The
    per-part clips below are all local: ``UNTOOLED_NOTE_CHARS`` caps one note
    at 2,400 characters and ``history_messages`` caps one past answer, but
    nothing capped their sum. Ten retrieved notes at that allowance is 24,000
    characters of notes alone, around 6,000 tokens, comfortably past a
    4,096-token model's entire window before the persona, the history or the
    question are counted, and what a model does when its window overruns is
    silently drop from the front, which is the system prompt. That is
    ``context.py``'s own opening example, unfixed on this path.

    None keeps the old unbudgeted behaviour, for the callers that genuinely
    have no model to measure against (tests building a prompt to inspect it).
    Every real caller passes one."""
    messages = [
        {
            "role": "system",
            "content": system_content(style, profile, persona_prompt, mode, ask_overview),
        }
    ]
    past = history_messages(history)
    if budget is not None:
        past = context.fit_history(past, budget.history_chars)
    messages.extend(past)

    dropped_notes = 0
    if budget is not None:
        # Same render function the loop below uses, so what `fit_notes`
        # measures is what actually goes on the wire, measuring one shape and
        # sending another is how a budget passes its own check and overruns
        # anyway.
        notes, dropped_notes = context.fit_notes(
            notes,
            budget.notes_chars,
            lambda note: note_for_prompt(note, UNTOOLED_NOTE_CHARS, can_fetch=False),
        )

    numbered = "\n".join(
        # A note the user attached by hand is flagged, so the model treats it
        # as the subject rather than as one more search hit, and a note that
        # arrived because it is *linked* to a hit is flagged too, for the
        # opposite reason: it did not match, and an answer that presents it as
        # though it did is telling the user their search found something it
        # did not.
        f"{i}. [{note['category']}]"
        f"{' (attached by me)' if note.get('attached') else ''}"
        f"{' (not a match: linked to one of the above)' if note.get('connected') else ''}"
        f"{_match_info_hint(note.get('match_info'))} "
        # No tools on this path by definition, it is the plain librarian
        # prompt: so notes get the larger allowance and an honest marker.
        f"{note_for_prompt(note, UNTOOLED_NOTE_CHARS, can_fetch=False)}"
        for i, note in enumerate(notes, start=1)
    )
    attached_hint = (
        " The notes marked \"attached by me\" are the ones I specifically chose "
        "for this question: focus on those."
        if any(note.get("attached") for note in notes)
        else ""
    )
    # Said rather than silently done, for the same reason the agent path says
    # it: a model that knows its notes were cut will hedge, where one that does
    # not will answer as though it saw the whole notebook. It has no tools on
    # this path, so unlike the agent's version this cannot point at a way to
    # get the rest: it says what happened and stops there.
    dropped_hint = (
        f"\n({dropped_notes} more matching note"
        f"{'' if dropped_notes == 1 else 's'} did not fit in this answer's "
        "context: say so if it matters.)"
        if dropped_notes
        else ""
    )
    user_message = {
        "role": "user",
        "content": (
            f"My notes:\n{numbered}{dropped_hint}\n\nMy question: {question}{attached_hint}"
        ),
    }
    if images:
        user_message["images"] = images
    messages.append(user_message)
    return messages


def answer(
    question: str,
    notes: list[dict],
    model_manager: ModelManager,
    ollama: OllamaClient,
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    use_utility_model: bool = False,
    mode: str | None = None,
    images: list[str] | None = None,
    model_override: str | None = None,
    image_context: str | None = None,
    ask_overview: bool = False,
) -> tuple[str, str | None]:
    """(answer text, model's thinking or None) for `question` given
    retrieved `notes` (dicts with 'content' and 'category').

    `use_utility_model` routes background jobs (the weekly digest) to the
    small fast model instead of the main chat model. `model_override` and
    `images`/`image_context` are routes_chat.py's own resolution of an
    image-carrying turn, and are mutually exclusive: when the model this
    turn would use can see an image directly, `images` carries the raw data
    URIs and `model_override` is usually unset (the chat model handles it
    itself); when it can't, `image_context` carries a vision model's own
    caption of the image instead, folded into the question text, and
    `images` stays empty: asked for directly, so a chat model with no
    vision of its own still "sees" what was attached without silently
    swapping the whole turn to a different model the user did not choose."""
    # An attached image (raw, or captioned into image_context) and "no
    # matching notes" are unrelated: "what's in this photo" has nothing to
    # do with the notebook and should never hit NO_RESULTS_MESSAGE just
    # because retrieval (which never sees the image) came back empty.
    if not notes and not images and not image_context:
        return NO_RESULTS_MESSAGE, None
    if not ollama.is_running():
        return OFFLINE_MESSAGE, None

    model = model_override or (
        model_manager.utility_model() if use_utility_model else model_manager.chat_model()
    )
    full_question = f"{question}\n\n{image_context}" if image_context else question
    try:
        reply = ollama.chat(
            model,
            build_messages(
                full_question,
                notes,
                style=style,
                profile=profile,
                history=history,
                persona_prompt=persona_prompt,
                mode=mode,
                images=images,
                budget=plan_budget(model, ollama, style, profile, persona_prompt, mode),
                ask_overview=ask_overview,
            ),
            mode=mode,
        )
        return reply["content"].strip(), reply["thinking"]
    except OllamaError:
        return OFFLINE_MESSAGE, None


# Said without the model, when Ollama isn't up. A greeting shouldn't produce an
# error message: the assistant can still say hello.
OFFLINE_SMALLTALK = "Hello. The AI model isn't running, but your notes are all still here."

#: What the Notes tab's Ask box says instead of chatting back (§35A).
#:
#: Reported: saying "hey" there got a chatbot answer. That box is for
#: interrogating the notebook, and a greeting is the one input it has nothing
#: to do with: so it says what it is for and gets out of the way, which costs
#: no model round and cannot misfire the way a classifier can.
#:
#: Written as a prompt rather than a scolding: the useful thing here is an
#: example of the kind of question that works.
ASK_IS_FOR_NOTES = (
    "This box searches your notes and answers from them. Try one of these, or "
    "ask about anything you've written. For a general chat, use the Chat tab."
)

#: Offered as buttons, not prose. The first version of this said the same
#: thing in a paragraph and read as a dead end beside an empty results panel, 
#: a wall of text telling someone what they did wrong. A question they can
#: click is a way forward from the same place, and it teaches the shape of a
#: question that works better than a description of one does.
ASK_EXAMPLES = [
    "What have I written about recently?",
    "Summarise my notes from last week",
    "What are my most common tags?",
]
OFFLINE_ABOUT_APP = (
    "I help you work with your notebook, finding, writing, tagging and "
    "summarising notes, and setting reminders. The AI model isn't running "
    "right now, so start it to ask me anything."
)


def converse(
    question: str,
    intent: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    mode: str | None = None,
    images: list[str] | None = None,
    model_override: str | None = None,
    image_context: str | None = None,
) -> tuple[str, str | None]:
    """Reply to a message that isn't a question about the notebook.

    Deliberately never touches retrieved notes: this is the path that stops
    "hey" being answered with a summary of the user's notebook.

    `images`/`model_override`/`image_context` mirror `answer()`'s own
    (routes_chat.py resolves them the same way for both, a casual "what's
    this?" with a photo attached used to drop the photo entirely here, since
    this path never accepted images at all before now)."""
    if not ollama.is_running():
        return (OFFLINE_ABOUT_APP if intent == "about_app" else OFFLINE_SMALLTALK), None
    model = model_override or model_manager.chat_model()
    full_question = f"{question}\n\n{image_context}" if image_context else question
    try:
        reply = ollama.chat(
            model,
            build_conversational_messages(
                full_question,
                intent,
                style=style,
                profile=profile,
                history=history,
                persona_prompt=persona_prompt,
                mode=mode,
                images=images,
            ),
            mode=mode,
        )
        return reply["content"].strip(), reply["thinking"]
    except OllamaError:
        return (OFFLINE_ABOUT_APP if intent == "about_app" else OFFLINE_SMALLTALK), None


# --- AI writing help -----------------------------------------------------

IMPROVE_MODES = {
    "proofread": (
        "Fix spelling, grammar, and punctuation in the user's note. Keep "
        "their wording and meaning as close to the original as possible, "
        "correct mistakes, don't rewrite."
    ),
    "rewrite": (
        "Rewrite the user's note so it reads clearly and well, keeping the "
        "same meaning, facts, and rough length. Keep their voice."
    ),
    "concise": (
        "Tighten the user's note: remove filler and repetition so it says "
        "the same thing in fewer words. Keep every fact."
    ),
}


def improve_writing(
    text: str,
    mode: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
    custom_instruction: str = "",
) -> str:
    """Return an improved version of `text` (proofread / rewrite / concise /
    custom). Raises OllamaError if the model is unavailable, the caller
    decides what to tell the user. Uses the utility model: this is a quick
    fix, not a conversation.

    `custom_instruction` is read only when `mode == "custom"`, asked for
    directly, so a person isn't limited to the three fixed presets ("make it
    sound more professional", "translate to French", …). It's the same
    person's own note either way, not a second, untrusted party, but it's
    still placed as the instruction's *content* rather than spliced into the
    surrounding sentence, and the "reply with ONLY the edited text" rule is
    restated after it: last word wins for a model reading top to bottom, so
    a custom instruction that tried to talk the model into adding commentary
    still loses to the app's own constraint on the reply shape.
    """
    if mode == "custom" and custom_instruction:
        instruction = f'The user asked for this change: "{custom_instruction}"'
    else:
        instruction = IMPROVE_MODES.get(mode, IMPROVE_MODES["proofread"])
    system = (
        f"You are a careful copy-editor. {instruction} Reply with ONLY the "
        "edited note text: no preamble, no quotes, no explanation."
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    # Thinking models may reason first; content already has think-tags split.
    return reply["content"].strip()


#: A generated title this long or longer reads as a summary sentence, not a
#: title: the model is asked to keep it shorter than this, and this is the
#: hard backstop if it doesn't.
GENERATED_TITLE_MAX_CHARS = 80


def generate_title(text: str, model_manager: ModelManager, ollama: OllamaClient) -> str:
    """A short title for a note that doesn't have one, on request, asked
    for directly as the AI half of "a note's own `# Heading` becomes its
    title": recognising one the user wrote is free (`manager.extract_title`,
    no model call), but *writing* one costs a real request, so this is
    opt-in per note rather than automatic on every save.

    Raises OllamaError if the model is unavailable, the caller decides what
    to tell the user, same as `improve_writing`.
    """
    system = (
        "You write short titles for personal notes. Reply with ONLY the "
        "title: 3 to 8 words, no quotes, no trailing punctuation, no "
        "leading '#'. It must actually describe what this specific note "
        "says, not a generic label like 'Quick note'."
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    title = reply["content"].strip().strip("\"'").lstrip("#").strip()
    return title[:GENERATED_TITLE_MAX_CHARS].strip()


def generate_link_reason(source_text: str, target_text: str, model_manager: ModelManager, ollama: OllamaClient) -> str:
    """Generate a very short, SPECIFIC reason (3-8 words) for why two notes
    are linked. Uses the utility model. Raises OllamaError if the model is
    unavailable.

    This exists to fix a reported complaint: the reason shown for almost
    every link was the literal string "similar in meaning"
    (`entry.manager.AUTO_REASON_TEXT`), true of any two notes an embedding
    thought were close, and useless for telling *which* two. The system
    prompt below asks for the concrete thing the two notes share, not a
    restatement that they're related; the caller (`ai.links.audit_vague_links`)
    is the other half, it rejects a reply that comes back vague anyway
    rather than trust the instruction alone.
    """
    system = (
        "You write short, SPECIFIC reasons explaining why two notes are "
        "connected. Name the concrete thing they share: a project, person, "
        "place, tool, decision, or date that appears in both notes. Do NOT "
        "just assert that they are similar or related, that is exactly the "
        "kind of vague answer to avoid.\n\n"
        "Bad (too vague, never write these): 'similar in meaning', 'both "
        "notes discuss this', 'related programming concepts', 'both mention "
        "studying techniques'.\n"
        "Good (names the specific thing): 'both about the Denver move', "
        "'shared deadline: 12 May', 'both mention Sarah', 'same client: "
        "Riverside project'.\n\n"
        "If you can't find anything specific two notes share, still name "
        "the closest concrete overlap you can see, never fall back to a "
        "generic 'they are related' sentence.\n\n"
        "Reply with ONLY the reason, 3 to 8 words, no quotes, no leading "
        "'because', no trailing punctuation."
    )
    prompt = (
        f"Note 1:\n{source_text[:1000]}\n\n"
        f"Note 2:\n{target_text[:1000]}\n\n"
        "What specific thing do these two notes share?"
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    reason = reply["content"].strip().strip("\"'").strip()
    return reason



def suggest_tags(
    text: str,
    existing: list[str],
    model_manager: ModelManager,
    ollama: OllamaClient,
    limit: int = 5,
) -> list[str]:
    """Suggest a few short topic tags for a note (Wave: re-evaluate). Uses
    the utility model. Raises OllamaError if the model is unavailable, 
    the caller decides what to do. Returns lowercased, de-duplicated tags,
    excluding any already on the note."""
    have = ", ".join(existing) if existing else "none"
    system = (
        "You label notes with short topic tags. Reply with ONLY a comma-separated "
        f"list of {limit} or fewer tags, each one or two lowercase words, no "
        "hashtags, no explanation. Tags already on the note (don't repeat): " + have
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    seen = {t.lower() for t in existing}
    tags: list[str] = []
    for raw in reply["content"].replace("\n", ",").split(","):
        tag = raw.strip().lstrip("#").lower()
        if tag and tag not in seen and len(tag) <= 30:
            seen.add(tag)
            tags.append(tag)
    return tags[:limit]


def summarize_meeting(
    text: str,
    model_manager: ModelManager,
    ollama: OllamaClient,
) -> str:
    """Pull a decisions/action-items block out of a raw meeting transcript
    (§25: Whisper's `/voice/transcribe-meeting` returns only the transcript
    itself, nothing structured). Same shape as `suggest_tags`: one
    utility-model completion, raises `OllamaError` if the model is
    unavailable and leaves it to the caller, never blocks a save on its own.

    Returns "" when the model replied but found nothing worth extracting
    (a short or off-topic recording), so the caller can skip prepending an
    empty block rather than showing one."""
    system = (
        "You read meeting transcripts and pull out only what's actionable. "
        "Reply in this exact Markdown shape, omitting a section entirely if "
        "it has nothing in it:\n\n"
        "**Decisions**\n- ...\n\n**Action items**\n- ...\n\n"
        "Each bullet is one short sentence. No preamble, no closing remarks. "
        "If the transcript has no decisions and no action items, reply with "
        "exactly: NONE"
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    )
    summary = reply["content"].strip()
    if not summary or summary.upper() == "NONE":
        return ""
    return summary


#: How many notes one map proposal is built from. A mind map of two hundred
#: notes is not a mind map, and the prompt below has to fit a 4B model's
#: context beside its own instructions: forty titles is about a page.
MAP_PROPOSAL_NOTES = 40

#: How much of a note the proposal prompt carries. The title is what a node is
#: called; the first line is there so the model can group two notes it has
#: never seen by what they are about, and no more than that, because forty
#: notes' worth of body text is the context this has to fit inside.
MAP_PROPOSAL_CHARS = 120


def propose_map_outline(
    notes: list[tuple[str, str]],
    model_manager: ModelManager,
    ollama: OllamaClient,
) -> str:
    """Ask the model to group notes into a mind map, as an indented outline.

    MINDMAP_PLAN.md section 5 item 15. The differentiator recorded there is
    that the nodes are *the user's real notes*, not invented text, so the
    instruction is written around one rule: a note's title is reproduced
    exactly, and everything the model writes of its own is a grouping topic
    above them. `routes_whiteboard.propose_map` matches those lines back to
    note ids by their titles, and a model that paraphrases a title breaks the
    match, which is why the rule is stated three ways here.

    An indented `- ` outline rather than JSON: it is the same shape
    `read_mindmap` hands the model and the same shape the Markdown import
    parses, so a small model is answering in a format it has already seen in
    this app, and a malformed reply degrades into fewer nodes rather than into
    a parse error. Raises `OllamaError` if the model is unavailable, like
    every other helper here; the caller decides what to do.
    """
    system = (
        "You organise notes into a mind map. Reply with ONLY an indented "
        "outline, no preamble and no closing remarks.\n\n"
        "Rules:\n"
        "- one node per line, each line starting with '- '\n"
        "- two spaces of indentation per level, up to three levels\n"
        "- the first line is the map's central topic\n"
        "- group the notes under short topic headings you write yourself\n"
        "- copy each note's title EXACTLY as given, character for character, "
        "on its own line: do not rephrase, shorten or re-title a note\n"
        "- every note appears exactly once\n\n"
        "Example:\n- Thesis\n  - Method\n    - Interview protocol\n"
        "  - Reading\n    - Kolmogorov complexity"
    )
    listing = "\n".join(
        f"- {title}" + (f" ({summary})" if summary else "")
        for title, summary in notes[:MAP_PROPOSAL_NOTES]
    )
    reply = ollama.chat(
        model_manager.utility_model(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Notes to map:\n{listing}"},
        ],
    )
    return reply["content"].strip()


# --- filing corrections (Brief 13; WORLD_CLASS_PLAN 4 B5) ---------------------
#
# **The one thing the filing prompt never had: a memory of being wrong.**
#
# Reported directly: *"what's the point of having an ai managed notebook if it
# is filed inaccurately and I need to manually fix it"*. The janitor's answer
# to that was to ask the model harder (it now consults the model first rather
# than trusting a centroid; see `ai/janitor.py`), which helps with the general
# case and does nothing at all about the specific one: the model files work
# notes about a side project under "Work", the user moves them to "Side
# project" every single time, and the next note goes back under "Work",
# because nothing anywhere records that this has already been settled.
#
# A correction is that record. `entry/manager.update_entry` writes one when a
# note the AI filed is moved by hand, and the next filing prompt that could
# land in the same category carries the last few. Which is the smallest
# possible version of learning: no training, no embeddings, no per-user model,
# five lines of the user's own history in the prompt that is about to make the
# same decision again.

#: How many corrections per category ride in a filing prompt. Five, because
#: they are the *last* five and a sixth adds a repetition rather than a fact:
#: the same correction made twice says one thing, and a prompt made of
#: examples is a prompt with no room left for the note being filed.
CORRECTIONS_REMEMBERED = 5

#: How much of a corrected note's own text is quoted. Enough to recognise the
#: kind of note it was, short enough that five of them are still a hint rather
#: than a second notebook. Prompt text is budgeted (`agent.PROSE_BUDGET_CHARS`)
#: and this is the field that would otherwise grow without limit.
CORRECTION_EXCERPT_CHARS = 80


def filing_corrections(session, categories: list[str]) -> list[dict]:
    """The last corrections that moved a note *into* one of `categories`.

    Keyed on where the note ended up rather than on where it came from,
    because that is the shape of the lesson: "notes like this belong in B" is
    usable when filing a new note, and "notes like this do not belong in A" is
    only usable if the model was about to choose A anyway.
    """
    from memorymap.core.database import AuditLog

    wanted = {name.strip().lower() for name in categories if str(name or "").strip()}
    if not wanted:
        return []
    out: list[dict] = []
    rows = (
        session.query(AuditLog)
        .filter(AuditLog.action == "correction")
        .order_by(AuditLog.id.desc())
        # Read more rows than are kept: the filter below is on the payload,
        # which SQL cannot see, and a category corrected once a month would
        # otherwise be crowded out by a busier one.
        .limit(CORRECTIONS_REMEMBERED * 20)
        .all()
    )
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        to = str(payload.get("to") or "").strip()
        if not to or to.lower() not in wanted:
            continue
        out.append(
            {
                "from": str(payload.get("from") or "").strip(),
                "to": to,
                "excerpt": str(payload.get("excerpt") or "").strip(),
            }
        )
        if len(out) >= CORRECTIONS_REMEMBERED:
            break
    return out


def corrections_note(session, categories: list[str]) -> str:
    """The corrections block of a filing prompt, or "" when there are none."""
    found = filing_corrections(session, categories)
    if not found:
        return ""
    lines = []
    for item in found:
        excerpt = item["excerpt"][:CORRECTION_EXCERPT_CHARS]
        where = f" from {item['from']}" if item["from"] else ""
        lines.append(f'- "{excerpt}" was moved{where} to {item["to"]}')
    return (
        "I have corrected your filing before. Follow these unless the note "
        "clearly says otherwise:\n" + "\n".join(lines)
    )


def filing_prompt(session, content: str, categories: list[str]) -> str:
    """The user half of the filing prompt: the choices, what the person has
    already corrected about them, and the note itself.

    Lives here rather than in `ai/janitor.py` because the corrections are a
    property of the *prompt*, not of the filing algorithm: the centroid and
    neighbour paths in the janitor never ask a model anything and have nothing
    to put them in.
    """
    parts = [f"Existing categories: {', '.join(categories) if categories else '(none yet)'}"]
    note = corrections_note(session, categories)
    if note:
        parts.append(note)
    parts.append(f"Note: {content}")
    return "\n".join(parts)


def filing_prompt_for_test(session, category) -> str:
    """The filing prompt a note being considered for `category` would get.

    A seam, in the spirit of `core/events.exercise_for_test`: the property
    worth pinning is *"a correction reaches the next prompt for that
    category"*, and asserting it through a full janitor run would be asserting
    the janitor's routing as well, which is a different test.
    """
    name = getattr(category, "name", category)
    return filing_prompt(session, "(a note being filed)", [str(name)])
