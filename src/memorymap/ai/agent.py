"""The agent loop: the chat model can act on the notebook.

Flow: offer the tool registry to Ollama → run whatever it calls → feed
the results back → repeat (bounded) → its final text is the answer.
Yields NDJSON-ready event dicts; the chat route just serialises them.

Safety lives here and in tools.py: destructive calls are never executed
in this loop: a "confirm" event goes to the UI instead, and the model
is told the action is waiting on the user.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator

from sqlalchemy.orm import Session

from memorymap.ai import budget as run_budget, cards, context, librarian, memory, tools
from memorymap.ai.model_manager import ModelManager
from memorymap.ai.ollama_client import (
    OllamaClient,
    OllamaError,
    ToolsUnsupportedError,
)

# A runaway model must not loop forever on a local machine.
MAX_ROUNDS = 6

# Rounds a turn can *earn* beyond MAX_ROUNDS, one per round that got somewhere.
#
# **Reported, repeatedly:** *"the agent struggles with long tasks like skills,
# then cuts out half way through and has to restart, or it hits a limit for
# tool calls which has happened quite a bit."* A flat six is the whole cause of
# the second half, and it binds on exactly the requests the app is for: "tag
# these eight notes" costs one search, a read and eight writes, and the model
# is cut off after six with the work half done and a note saying so.
#
# The flat cap was never really measuring "runaway", it was counting rounds,
# and a model doing steady useful work spends rounds for the same reason a
# looping one does. What separates them is whether anything *new* happened: a
# round in which at least one tool call succeeded and was not a repeat of one
# already made this turn is progress, and it buys one more round. A model
# calling `search_notes` with the same arguments for the fourth time earns
# nothing and still stops at MAX_ROUNDS.
#
# So the ceiling is `MAX_ROUNDS + EARNED_ROUNDS` and it is only reachable by a
# turn that did twelve distinct, successful things, which is a long job, not a
# loop. A loop still stops at six.
EARNED_ROUNDS = 6

# How much of a round's own reasoning is carried into the next one.
#
# Asked for directly, and the reasoning behind the number: a plan is worth a
# paragraph, not a page. Carrying the whole of a thinking model's output would
# double the prompt every round, the thing §11a exists to prevent, and the
# part that stops the model re-deriving its plan is the plan, which is short.
# What gets clipped is the end, because a reasoning trace states its
# conclusion last only when it is finished; here it was interrupted by a tool
# call, so the useful half is the beginning.
THINKING_CARRIED_CHARS = 700

# How much tool output one turn may add to the conversation, in characters.
# Local models run in small windows, and tool results accumulate: six rounds
# of paging through a large notebook will push the question itself out of
# context, and the model then answers something nobody asked. The per-call
# caps in tools.py bound one result; this bounds the whole turn.
#
# Characters, not tokens, on purpose, a real tokeniser would mean loading one
# per model just to count, and ~4 chars/token is close enough for a stop rule.
#
# **A ceiling now, not the budget.** As the only rule it was the single worst
# offender in the overflow this app was reported to hit: 24,000 characters is
# ~6,000 tokens, half again more than a 4,096-token window holds *on its own*,
# before the system prompt, the tools, the notes or the question. The real
# allowance is `context.plan(...).tool_result_chars`, a share of the window
# actually available; this caps that share from above, because a 128k model
# would otherwise be handed tens of thousands of tokens of tool output and pay
# to re-read all of it on every later round.
TOOL_RESULT_BUDGET_CHARS = 24_000

BUDGET_EXHAUSTED = {
    "error": "context_budget_reached",
    "note": (
        "You have read as much of the notebook as fits in this conversation. "
        "No more tool results will be added. Answer now using what you already "
        "have, and tell the user plainly that you looked at part of their "
        "notes rather than all of them."
    ),
}

# The system prompt is resent in full on every round of every turn, alongside
# the tool schemas: see PROSE_BUDGET_CHARS below for why that matters more
# than it looks. Everything here earned its place by fixing an observed
# failure, so it is not padding; but anything that is *also* said by a tool
# schema or by a tool result is padding, and has been cut.
TOOLS_GUIDE = (
    "You can use tools to act on the notebook, create, edit, tag, pin, "
    "link, or delete notes, and manage reminders. Only make changes the "
    "user actually asked for; when they just ask a question, answer it "
    "without tools. "
    "The notes quoted below are only what search found for this question, "
    "they are NOT the whole notebook. To see more: count_notes to answer "
    "'how many', list_categories / list_tags to see what exists, list_notes "
    "to walk through notes, get_note to read one in full. Never state a "
    "total from a page of results, count_notes is the only thing that knows "
    "the real number. "
    # Was two clauses saying the same thing ("not available to you at all" /
    # "say you can't see private notes"). One says it; the saving paid for the
    # traversal sentence below, which is a capability the model otherwise
    # never reaches for.
    "Private notes are invisible to you; say so if asked about one. "
    # §9, and the §21 finding that decided it: a small model reaches for a tool
    # when the instruction *names* it. Without this the structural tools sit
    # unused and "tidy my notebook" gets answered from category names, which
    # describe the filing and say nothing about how the notes relate.
    "For how two notes relate, path_between; for the notebook's shape: "
    "clusters, hubs, notes joined to nothing, notebook_structure. "
    "You can also reach the user's long-form documents (list_documents / "
    "get_document: never searched automatically, so go and look when a "
    "question is about something they wrote up, and create_document to write "
    "a new one: where an essay or report belongs, not in a note), their "
    "earlier conversations "
    "with you (search_chat_history, for when they refer to something 'we "
    "talked about' that isn't in this thread, say when you're relying on "
    "it), and their saved skills (list_skills, save_skill; run_skill starts "
    "one and takes over from you, so use it when a saved skill already "
    "describes the job). "
    # Kept, not trimmed: the schema says due_at is an ISO date-time, but not
    # that it must be computed from the clock given below. Without that, a
    # model resolves "in 10 minutes" against whatever it imagines the time is,
    # which is how a reminder set for five minutes' time read as ten hours
    # overdue the moment it was saved.
    "For \"remind me… in 10 minutes / tomorrow at 9 / tonight\", call "
    "set_reminder with due_at computed from the current time given below, as "
    "an ISO 8601 datetime. "
    # Both halves of this earned their place and both were briefly cut. Without
    # the first the model acts and then says nothing, so the user watches tool
    # chips scroll past and gets no answer; without the second it narrates work
    # it never did. They are opposite failures and the pair is the fix.
    "After acting, tell the user briefly what you did. NEVER say you created, "
    "saved, edited, deleted, tagged, linked or unlinked anything unless you "
    "called the tool: \"we linked…\" is claiming it just as much as \"I "
    "linked…\", and a list of work you did not do is the worst thing you can "
    "write. Planning is fine: say it in the future tense, then call the tools. "
    # Asked for directly: "I need agents to use tools more and better if they
    # are required." The loop already allows several rounds; nothing told the
    # model that using them was expected rather than a failure to answer
    # promptly, so it tended to answer from the first page of search results.
    "Taking several turns is normal and expected: look something up, read "
    "what you found, look up anything still missing, then answer. Do not "
    "rush to an answer while something you were asked about is still "
    "unchecked. "
    # §35K: "I will say fix my categories and it will only merge two categories
    # and leave it at that." Short because the schema carries the rest, this
    # is only here because the *trigger* is a property of the request, and the
    # model has to be told to look for it.
    "If a request covers many notes, make_plan first. "
    # It under-used read_url badly: a result snippet is a sentence, and the
    # model treated it as the page.
    "A web search result is a title and one clipped sentence, enough to "
    "choose a page, never enough to answer from. Call read_url on a result "
    "that matters before relying on it, and name the sites you actually read. "
    # It re-narrated the step timeline the user was already watching.
    "The user can already see which tools you ran, in order. Do not narrate "
    "your process back to them ('let me search…', 'I will now check…'), just "
    "do it, then give the answer. "
    # Reported: "I don't know what 'Note #12' is when the ai refers to it."
    # Ids are the app's handle, not the user's: nothing in the interface shows
    # one, so a bare id names a note the user has no way to identify.
    "Users never see note ids: name a note by a few of its own words (\"your "
    "gym routine note\"), not \"note 28\". "
    # Screenshotted: a bullet reading "Jokes $\rightarrow$ Social Skills".
    # The renderer translates the common escapes now, but not writing them is
    # cheaper than translating them.
    "Write symbols plainly (→ × ≤), never as LaTeX. "
    "If a tool fails, its result carries a 'what_to_do' field. Follow it. "
    "Never repeat a call that has just failed in exactly the same way."
)

#: The window below which a model gets `COMPACT_TOOLS_GUIDE` instead. Same
#: threshold `tools.SMALL_WINDOW_CHARS` uses for holding back orchestration
#: tools, expressed in tokens: below this, the fixed cost of the prompt is the
#: thing squeezing out the notes, and the guide is the largest fixed piece.
SMALL_WINDOW_TOKENS = 8_192

#: The load-bearing half of TOOLS_GUIDE, for a model that cannot afford the
#: whole thing.
#:
#: Measured on a real turn: TOOLS_GUIDE is 2,807 characters, about 700 tokens
#:, and it is re-sent on **every round** of an agent loop. On a 4k-window
#: model that is 17% of the entire context spent, per round, on static prose,
#: which is a large part of the reported *"agent mode and chats are too heavy
#: for small models and have a too small context window"*.
#:
#: What is kept is what a model gets *wrong* without being told, and what
#: cannot be recovered from: claiming work it never did, treating a page of
#: search results as the whole notebook, quoting note ids at the user, and
#: repeating a call that just failed. What is dropped is elaboration the tool
#: schemas already carry: which tool to reach for is in each tool's own
#: description, and a small window is exactly the case where saying it twice
#: is unaffordable.
#:
#: Deliberately not a truncation of the constant above: a guide cut at 1,100
#: characters would lose the honesty rule, which sits at the end and is the one
#: sentence in this file that most needs to survive.
COMPACT_TOOLS_GUIDE = (
    "You can use tools to act on the notebook. Only make changes the user "
    "actually asked for; answer plain questions without tools. "
    "The notes quoted below are only what search found, NOT the whole "
    "notebook. Use count_notes for totals, list_notes to walk through, "
    "get_note to read one in full. Never state a total from a page of "
    "results. Private notes are invisible to you; say so if asked. "
    "For reminders, compute due_at from the current time below as ISO 8601. "
    "NEVER say you created, saved, edited, deleted, tagged or linked "
    "anything unless you actually called the tool, claiming work you did "
    "not do is the worst thing you can write. Planning ahead is fine: say "
    "it in the future tense, then call the tools. "
    "Taking several turns is normal: look something up, read it, then "
    "answer. Do not narrate ('let me search…'), just do it, then answer. "
    "Name a note by its own words, never 'note 28'. Write symbols plainly "
    "(→ × ≤), never as LaTeX. If a tool fails, follow its 'what_to_do' "
    "field, and never repeat a call that just failed the same way."
)


#: Appended when the tool list was narrowed by reading the question's words.
#:
#: The narrowing is a guess made from wording, and a guess the model is
#: entitled to disagree with, asked for directly: *"if the program detects
#: words and suggests that specific tools or skills might need to be used, and
#: the AI thinks that's wrong then it doesn't have to use them"*.
#:
#: It already may. `permitted` is None on an ordinary turn, so a tool the model
#: names runs whether or not it was in the list, and reaching past the list
#: widens it for the rest of the turn (see the focus-correction block in the
#: round loop). What was missing was the model being *told* that, without it,
#: a well-behaved model treats the list as exhaustive, which is exactly the
#: behaviour that makes a narrow guess expensive.
#:
#: One sentence, because it is on every round of every focused turn, and it
#: is appended to the system message, joining the clock in its volatile tail
#: (see build_agent_messages): narrowed-or-not is decided per turn, so this
#: can never be part of the prefix-cached head wherever it is put.
FOCUS_NOTE = (
    " The tools listed were picked from the wording of the request and are a "
    "suggestion, not a limit: if the right one is not there, call it by name "
    "anyway, and ignore any that do not fit."
)


def tools_guide(window_tokens: int | None) -> str:
    """The tool guide sized to the window, see COMPACT_TOOLS_GUIDE.

    ``None`` means the window is not known yet, which is the safe case for the
    long guide: an unknown window is usually a provider that did not report
    one, not a tiny one.
    """
    # `<=`, so an 8k model is included rather than sitting just outside. At 8k
    # the fixed prompt measured 32% of the window before a single turn of
    # history; at 16k the same prompt is 16%, which is a budget rather than a
    # squeeze. 8k is the last size that needs the help.
    if window_tokens is not None and window_tokens <= SMALL_WINDOW_TOKENS:
        return COMPACT_TOOLS_GUIDE
    return TOOLS_GUIDE


# What the model is handed before a single word of the question, the notes or
# the history, the system prompt plus every tool schema, resent on each of
# up to MAX_ROUNDS rounds.
#
# This is the number that decides whether the agent is usable on the 3B-class
# models people actually run here (granite4.1:3b, llama3.2:3b, qwen3.5:2b).
# Ollama defaults to a 4096-token window unless a model says otherwise, so at
# ~4 chars per token this overhead alone can be most of it, and everything
# past the limit is silently dropped from the *front*, which is the system
# prompt, so a model that overflows stops knowing it has tools at all.
#
# It is asserted rather than noted because it drifts upward invisibly: every
# tool added and every sentence added to the guide costs the same budget, and
# nothing else in the codebase would notice. When this needs raising, raise it
# deliberately and say why here.
#
# 13,000 → 13,800, for the four category tools (§14). The guard did its job:
# adding them took the all-tools overhead straight past the old figure, and
# the first version of those schemas, with a per-parameter description on
# each, matching the older tools, went past the *window* too. They were
# rewritten terse (no "old: the current name" when the field is called `old`)
# and now cost 1,112 characters between them.
#
# **This is now a backstop, not the mechanism.** It was briefly the binding
# constraint on §14's tool list, "room for about one more tool, then none" , 
# which was the wrong shape of answer, because the ceiling it described was
# never a fact about the app. 4096 is what Ollama falls back to when a model
# declares nothing; most current models declare 8k, 32k or far more.
#
# `tools.within_budget` now fits the schemas to the window the model actually
# reports (`ollama_client.usable_context`), dropping the least relevant tools
# when they do not fit and logging what it held back. So a 32k model gets the
# whole registry, a genuine 3B at 4096 gets a prioritised subset, and adding a
# tool is no longer a question of whether it fits inside a constant.
#
# What this number still does is catch the *prose* growing, the system prompt
# and TOOLS_GUIDE are sent whatever the window, and no per-turn trimming
# applies to them. If it trips, look at what was added to the guide before
# reaching for the number.
#
# 13,800 → 14,400, for `ask_user` (§33). The guard did its job again, and the
# useful part was *how* it tripped: the registry was sitting at 13,743 of
# 13,800, so it would have fired on whoever added the next tool, whatever it
# was. The first version of the schema was 784 characters of prose explaining
# when to ask; it was cut to 507 by keeping only the two rules that stop it
# being misused (stop after asking, don't ask what you could look up) and
# deleting the rest. `ask_user` is in CORE_TOOLS, so unlike most tools it is
# paid for on every single turn, which is exactly why it had to be terse.
#
# 14,400 → 15,000, for `related_notes` (§9). Second raise in one session, and
# that pattern is worth naming rather than repeating silently: **this number
# was measuring the wrong thing.** It weighed the *whole* registry, and no turn
# has sent the whole registry since `within_budget` started fitting the schemas
# to the model's real window: a 4k model receives about 1,450 tokens of it, a
# 32k model receives all of it and has ample room. So what tripped was not "the
# prompt is too heavy for a small model" but "the registry grew again", which
# is a thing that is *supposed* to happen.
#
# **Retired at that point, exactly as the note above it said to.** It asked for
# retirement if it ever needed raising a third time for a *tool* rather than
# for prose: and the third time came in the same session, for one added
# argument on `save_skill`. A guard that has to be raised every time the app
# grows is not a guard; it is a chore that teaches people to edit the number.
#
# What replaces it is two assertions that each measure something real:
#
#   - `PROSE_BUDGET_CHARS` below: the persona and TOOLS_GUIDE, which are sent
#     whatever the window and are *never* trimmed. This is the half the old
#     constant measured honestly, and the half that can still quietly bloat.
#   - `test_prompt_budget.test_the_overhead_leaves_room_for_an_actual_
#     conversation`, what actually reaches a 4,096-token model *after* the
#     trim. That is the number that decides whether a 3B model works.
#
# The tool registry is deliberately no longer capped by a constant. It is
# capped by the model's real window, per turn, by code that is tested.

# The un-trimmable half. Every character here is resent on every round of every
# turn, before the question, the notes or the history, and unlike the tool
# schemas, nothing fits it to the window. If this trips, something was added to
# TOOLS_GUIDE or the persona; look there rather than at the number.
PROSE_BUDGET_CHARS = 3_000

#: Re-exported so the constant keeps resolving from `agent` for anything that
#: already reads it there. It lives in `ai/memory.py` now, next to the code
#: that enforces it.
MEMORY_STREAM_BUDGET_CHARS = memory.MEMORY_STREAM_BUDGET_CHARS

# What to do about a failed tool call.
#
# A failure used to be handed to the model as a bare `{"error": "..."}` and
# nothing else. Small models do one of two things with that: give up and
# apologise, or call the identical thing again, and again, until MAX_ROUNDS
# runs out and the user gets "I stopped after using several tools in a row"
# having been told nothing. Neither is a reasonable response to, say, a
# mistyped note id.
#
# The error now travels with a recovery instruction. The wording is
# deliberately concrete about the *next call to make*, because "try something
# else" is exactly the advice a small model cannot act on.
_RECOVERY_HINTS = {
    "unknown_tool": (
        "That tool does not exist. Do not call it again. Use one of the tools "
        "you were given, or answer without tools."
    ),
    "disabled": (
        "The user has turned this tool off in Settings. Do not call it again. "
        "Tell them it is off and what turning it on would let you do."
    ),
    "not_found": (
        "Nothing exists with that id. Do not guess another id. Call "
        "search_notes (or list_notes) to find the real one, then retry with "
        "the id that search returned."
    ),
    "arguments": (
        "The arguments were wrong. Read the tool's schema again and retry "
        "once with corrected arguments. If you cannot work out what it wants, "
        "stop calling it and tell the user what you were trying to do."
    ),
    "web_off": (
        "Web access is off in Settings. Do not retry. Answer from the "
        "notebook, and say that a web lookup would need turning on."
    ),
    "generic": (
        "That call failed. Do not repeat it unchanged. Either retry once with "
        "different arguments, try a different tool, or tell the user plainly "
        "what failed and answer with what you already have."
    ),
    "not_in_skill": (
        "This skill does not include that tool. Use only the tools listed for "
        "the run, or finish and tell the user what the skill could not do."
    ),
    "already_running": (
        "You are already inside a run that is working through steps, you "
        "cannot start another one from in here. Do this step with the tools "
        "you have, and the next step will get its own turn."
    ),
    "empty_result": (
        "That search or list returned nothing. Do not repeat the same call. "
        "Try a different, broader search term, or tell the user you couldn't find it."
    ),
    "timeout": (
        "That tool call took too long and was aborted. Do not retry it right now. "
        "Tell the user the operation timed out and they may need to try again later."
    ),
    "rate_limited": (
        "The model or service is currently rate limited. Stop making tool calls "
        "and tell the user they are being rate limited."
    ),
}


def _recovery_hint(name: str, message: str) -> str:
    """Pick the advice that fits this failure."""
    lowered = message.lower()
    if "not part of this skill" in lowered:
        return _RECOVERY_HINTS["not_in_skill"]
    if lowered.startswith("unknown tool"):
        return _RECOVERY_HINTS["unknown_tool"]
    if "turned off in settings" in lowered:
        return _RECOVERY_HINTS["disabled"]
    if "web search is disabled" in lowered:
        return _RECOVERY_HINTS["web_off"]
    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return _RECOVERY_HINTS["rate_limited"]
    if "timeout" in lowered or "timed out" in lowered:
        return _RECOVERY_HINTS["timeout"]
    # "nothing found" and "returned nothing" are about the *search*; "empty" on
    # its own is not, and matching it here sent "the note body is empty", an
    # argument mistake the model can fix, down the "it isn't there, stop
    # looking" path. Match the phrases that mean an empty result, not the word.
    if "nothing found" in lowered or "returned nothing" in lowered or "no results" in lowered:
        return _RECOVERY_HINTS["empty_result"]
    if "not found" in lowered or "no note" in lowered or "no such" in lowered:
        return _RECOVERY_HINTS["not_found"]
    # ValueError/KeyError/TypeError from a handler are argument problems, and
    # execute_tool prefixes those with the tool's own name.
    if lowered.startswith(f"{name}:"):
        return _RECOVERY_HINTS["arguments"]
    return _RECOVERY_HINTS["generic"]


REPEATED_CALL_NOTE = (
    "You have already made this exact call and it failed the same way. "
    "Calling it a third time will not help. Change the arguments, use a "
    "different tool, or stop and tell the user what you could not do."
)

# How many times one tool may fail in a turn, with *any* arguments, before
# it is taken away for the rest of that turn. See `tool_failures` in
# `run_agent` for the logged loop this exists for. Three is deliberate: two
# failures is a model correcting itself, which is the behaviour the recovery
# hints are there to produce and worth allowing; a third means it is not
# converging and every further round is spent, not invested.
#: What the chat transcript's tool disclosure shows when a tool did not write
#: its own `summary`.
#:
#: Reported with a screenshot: "tools render fine in the chat initially but
#: then I come back to them after reloading the app later and they look like
#: this", rows reading `Listed your categories{'categories': [{'name':
#: 'Games', 'notes': 3}], 'total_notes': 27, 'label': 'ph:folders Listed your
#: categories'}`. That is Python's `repr` of the result dict, which is what
#: the fallback here used to be: single quotes, `True`/`False`, no line
#: breaks, and the app's own display `label` repeated inside the body of the
#: row whose heading already is that label.
#:
#: JSON instead, indented, for three reasons: it is the format the arguments
#: block directly above it in the same disclosure already uses
#: (`JSON.stringify(args, null, 2)`), so the two halves stop looking like they
#: came from different programs; it is what the tool actually returned over
#: the wire; and it wraps at field boundaries instead of running as one line.
#: `label` is dropped because it is presentation the row has already shown,
#: and `default=str` keeps a stray datetime from turning the whole disclosure
#: into an error.
#:
#: 4000 is unchanged and deliberate, see the note at the call site: the box
#: it lands in already scrolls (`.tool-chip-result`, 12rem), so this only
#: bounds a pathological single result from bloating the SSE event.
RESULT_SUMMARY_CHARS = 4000


def _result_summary(result: dict) -> str:
    """A tool's result as the transcript shows it."""
    summary = result.get("summary")
    if summary:
        return str(summary)
    body = {k: v for k, v in result.items() if k != "label"}
    try:
        text = json.dumps(body, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        # A result that will not serialise is still worth showing.
        text = str(body)
    if len(text) > RESULT_SUMMARY_CHARS:
        return text[:RESULT_SUMMARY_CHARS] + "…"
    return text


#: **What a tool call actually touched, as things the reader can open.**
#:
#: Asked for: "is it also possible to have live action lines show on the chat
#: ui, to show and visually show as the ai accesses specific notes, files and
#: stuff??"
#:
#: The transcript already said *that* a tool ran and, in a disclosure, what it
#: returned as JSON. What it could not say is *which note*, and a note id in a
#: blob of JSON is not something a person can act on, the same complaint that
#: produced the palette's note links.
#:
#: Read from the tool's own result rather than from the arguments it was called
#: with. Arguments are what the model *asked for*, which may be wrong, may be a
#: search string rather than an id, and may name a note the call then refused.
#: The result is what happened. A tool that touched nothing contributes
#: nothing, which is why this returns a list and the UI omits the row when it
#: is empty.
#:
#: Capped, because a `list_notes` over a big notebook would otherwise put fifty
#: chips under one row and bury the answer beneath its own evidence.
TOUCHED_LIMIT = 6


def _touched_kind(candidate: dict) -> str | None:
    """Which kind of thing a result row is, or None if it is not one.

    **The order matters and is the whole correctness of this function.** A
    document result carries `id`, `title` *and* `content` (see
    ai/tools/documents.py), so a check for `content` alone calls a document a
    note: and the UI would then open the *note* with that id, which is a
    different object entirely, or nothing at all. `title` is what only a
    document has; `content` is what a note has and a document also has. So
    document is tested first, and note is the fallback.
    """
    if "title" in candidate:
        return "document"
    if "content" in candidate:
        return "note"
    return None


def _touched_items(result: dict) -> list[dict]:
    """What a tool result names, as {kind, id, label} for the transcript."""
    if not isinstance(result, dict):
        return []
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def _take(candidate: object) -> None:
        if len(rows) >= TOUCHED_LIMIT or not isinstance(candidate, dict):
            return
        item_id = candidate.get("id")
        if not isinstance(item_id, int):
            return
        kind = _touched_kind(candidate)
        if kind is None or (kind, item_id) in seen:
            return
        seen.add((kind, item_id))
        # A document is known by its title; a note has none, so its opening
        # words stand in for one, the same thing `noteLabel` shows in a list.
        source = candidate.get("title") if kind == "document" else candidate.get("content")
        label = " ".join(str(source or "").split())[:60]
        rows.append({"kind": kind, "id": item_id, "label": label or f"{kind} #{item_id}"})

    # The single-item shape (`get_note`, `edit_note`, `read_document`) is the
    # result itself; the many-item shapes nest under a handful of stable keys.
    _take(result)
    for key in ("notes", "documents", "results", "matches", "linked", "created"):
        value = result.get(key)
        if isinstance(value, list):
            for item in value:
                _take(item)

    #: **A mind map, which is named by `board_id` and not by `id`.**
    #: MINDMAP_PLAN.md §5 item 12 asks for a map chip in the chat transcript,
    #: and without this the four map tools contributed *nothing* to it:
    #: `read_mindmap`, `create_mindmap`, `add_map_node` and `link_map_nodes`
    #: all return `board_id` (plus `board_title` or `title`), so `_take`'s
    #: `candidate.get("id")` found no id and the row was dropped, a turn that
    #: read a whole map showed a bare tool name and no way to open it.
    #:
    #: Read here rather than by teaching `_take` about a second id field: `id`
    #: means "a note or a document" everywhere else in this function, and a
    #: board id in that space would be opened as a note by the front end,
    #: which is the exact confusion `_touched_kind`'s own comment is about.
    board_id = result.get("board_id")
    if isinstance(board_id, int) and len(rows) < TOUCHED_LIMIT:
        title = result.get("board_title") or result.get("title") or ""
        label = " ".join(str(title).split())[:60] or f"map #{board_id}"
        if ("map", board_id) not in seen:
            seen.add(("map", board_id))
            rows.append({"kind": "map", "id": board_id, "label": label})
    return rows


#: How many ids one read may contribute to a run's `seen_ids` (Brief 13).
#: Generous where `TOUCHED_LIMIT` is deliberately mean: `touched` draws chips
#: in the transcript, where six is already a crowd, while this is the run's
#: own ledger of what it has actually looked at, and the whole point of paging
#: a notebook is that the number is larger than one page. Ints only, so the
#: cost of carrying the full page is a few dozen bytes on the event.
SEEN_LIMIT = 500


def _seen_ids(result: dict) -> list[int]:
    """Every note id one read returned, in order, without the chip cap.

    **Why this is not `touched`.** `_touched_items` is the transcript's list
    and stops at six, which is right for a row of chips and wrong for the one
    question a paging step has to answer: *have I now seen all of them?* A
    step told to look at every note used to have no way to know, because the
    only record of what a page contained was capped at a quarter of a page.
    """
    if not isinstance(result, dict):
        return []
    ids: list[int] = []
    seen: set[int] = set()

    def _take(candidate: object) -> None:
        if len(ids) >= SEEN_LIMIT or not isinstance(candidate, dict):
            return
        item_id = candidate.get("id")
        # Notes only: an id here is read back as a note id by the state line
        # and by every id-targeting tool, and a document id in that space
        # names a different object entirely (see `_touched_kind`).
        if not isinstance(item_id, int) or item_id in seen or "title" in candidate:
            return
        if "content" not in candidate:
            return
        seen.add(item_id)
        ids.append(item_id)

    _take(result)
    for key in ("notes", "results", "matches", "linked", "created"):
        value = result.get(key)
        if isinstance(value, list):
            for item in value:
                _take(item)
    return ids


#: How many web/file sources one tool call may contribute to the answer's
#: Sources panel. Five is what `web_search` itself asks the engine for.
SOURCE_LIMIT = 8

#: How much of a result's own text stands in as a preview. Long enough to tell
#: whether the source is the one you want, short enough that eight of them do
#: not become a second answer under the answer.
SOURCE_SNIPPET_CHARS = 220


def _tool_sources(name: str, result: dict) -> list[dict]:
    """The pages and files one read-only call actually consulted, as
    ``{title, url, snippet}`` rows for the chat's Sources panel.

    Reported: *"improve the ui of the sources… what is shown about the
    sources, dropdown previews, hyperlinks etc."* The panel could not show any
    of that, because none of it was ever sent: a tool event carried a prose
    label and a bounded `result_summary` blob, so the front end had a sentence
    where it needed a title, an address and a line of the page.

    Read-only tools only. A write tool's result is a change, and changes are
    already carried by `change`/`touched`, a source is something the answer
    *drew on*.
    """
    if not isinstance(result, dict) or "error" in result:
        return []
    rows: list[dict] = []

    def _clip_text(value: object) -> str:
        text = " ".join(str(value or "").split())
        return text[:SOURCE_SNIPPET_CHARS]

    if name == "web_search":
        for hit in (result.get("results") or [])[:SOURCE_LIMIT]:
            if not isinstance(hit, dict):
                continue
            rows.append(
                {
                    "title": _clip_text(hit.get("title")) or str(hit.get("url") or ""),
                    "url": str(hit.get("url") or ""),
                    "snippet": _clip_text(hit.get("snippet")),
                }
            )
    elif name == "read_url":
        rows.append(
            {
                "title": _clip_text(result.get("title")) or str(result.get("url") or ""),
                "url": str(result.get("url") or ""),
                "snippet": _clip_text(result.get("text")),
            }
        )
    elif name in {"read_file", "search_files"}:
        matches = result.get("matches") or result.get("results") or []
        if isinstance(matches, list) and matches:
            for hit in matches[:SOURCE_LIMIT]:
                if not isinstance(hit, dict):
                    continue
                rows.append(
                    {
                        "title": _clip_text(hit.get("path") or hit.get("name")),
                        "url": "",
                        "snippet": _clip_text(hit.get("snippet") or hit.get("text")),
                    }
                )
        elif result.get("path") or result.get("name"):
            rows.append(
                {
                    "title": _clip_text(result.get("path") or result.get("name")),
                    "url": "",
                    "snippet": _clip_text(result.get("text") or result.get("content")),
                }
            )
    #: A row with nothing to say is not a source. Dropping it here keeps the
    #: "is there anything to show" test in the front end a length check.
    return [row for row in rows if row["title"] or row["url"]]


MAX_TOOL_FAILURES = 3

# How many confirm cards one destructive tool may put in front of the user in
# a single turn. See the `parked` check in `run_agent`.
MAX_PARKED_CONFIRMS = 2

TOOL_EXHAUSTED_NOTE = (
    "This tool has now failed several times in this turn with different "
    "arguments, so it has been switched off for the rest of this turn. Do "
    "not call it again, you will get this same message. Either do the job "
    "with a different tool, or stop now and tell the user plainly what you "
    "were trying to do and what went wrong."
)


# Write tools whose absence makes a "I saved it" claim a lie (safety net).
# Defined in the registry, so the settings screen and the skill list can mark
# "this one changes things" from the same list rather than a second copy.
_WRITE_TOOLS = tools.WRITE_TOOLS

# Which key each note-touching write tool's own result carries the note's id
# under. Not "id" for all of them (`link_notes` says `linked`, `delete_note`
# says `deleted`) and not present at all for tools that touch something else
# entirely (`create_document`'s "id" is a *document* id).
#
# **Reported as "the agent does things that don't make sense":** a change
# event used to read `result.get("id")` unconditionally and call it
# `note_id`, so creating a document during a skill run produced a change
# whose "note_id" was really that document's id: the change list's own View
# button (§21/§22) would then take you to whatever note happened to share
# that id, or nowhere. `_change_note_id` only fills the field in for tools
# that actually touched a note, and reads it from the field that tool really
# uses.
_NOTE_ID_FIELD = {
    "create_note": "id",
    "edit_note": "id",
    "tag_note": "tagged",
    "pin_note": "id",
    "restore_note": "id",
    "link_notes": "linked",  # [source_id, target_id]: the note the call was made on
    "unlink_notes": "unlinked",
    "delete_note": "deleted",
}


def _change_note_id(name: str, result: dict) -> int | None:
    """The note this write actually touched, or None for a write that
    touched something else (a document, a reminder, a tag, a skill)."""
    field = _NOTE_ID_FIELD.get(name)
    if field is None:
        return None
    value = result.get(field)
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, int) else None


# The document equivalent of `_NOTE_ID_FIELD` above: only `create_document`
# needs one: `delete_document` is destructive, so it never reaches this code
# path at all (it is parked for a confirm, not executed here).
_DOCUMENT_ID_FIELD = {"create_document": "id"}


def _change_document_id(name: str, result: dict) -> int | None:
    """The document this write actually created, or None otherwise. A
    sibling of `_change_note_id` for the same reason: a later skill step
    that needs to reference "the document I just wrote" is working from
    `step_history`, not from this turn's own tool results, so the id has to
    survive into the next step's context under a field that names what it
    actually is."""
    field = _DOCUMENT_ID_FIELD.get(name)
    if field is None:
        return None
    value = result.get(field)
    return value if isinstance(value, int) else None


# ROADMAP.md Tier 2 §13: reminders and categories had no `_change_*_id`
# resolver at all, so `changeRow`'s View button: built for notes and
# documents: had nothing to extend to. Both tools' own results already
# carry what's needed; this just names the field the same way the two
# resolvers above do.
_REMINDER_ID_FIELD = {"set_reminder": "id", "complete_reminder": "id"}


def _change_reminder_id(name: str, result: dict) -> int | None:
    """The reminder this write actually touched, or None otherwise."""
    field = _REMINDER_ID_FIELD.get(name)
    if field is None:
        return None
    value = result.get(field)
    return value if isinstance(value, int) else None


# Categories are identified by name, not id, every category tool's own
# arguments and results already work in names, so this names the field that
# carries the category a note ended up in rather than inventing an id
# nothing else uses. `delete_category` is destructive (like
# `delete_document`) and never reaches this code path, it's parked for a
# confirm card, not executed here.
_CATEGORY_NAME_FIELD = {
    "create_category": "name",
    "rename_category": "name",
    "merge_categories": "into",
}


def _change_category_name(name: str, result: dict) -> str | None:
    """The category this write actually created or landed notes in, or None
    otherwise."""
    field = _CATEGORY_NAME_FIELD.get(name)
    if field is None:
        return None
    value = result.get(field)
    return value if isinstance(value, str) and value else None

# --- claiming work that never happened -------------------------------------------
#
# The failure this catches is the one that costs the most trust, because the
# user has no way to see it: the model writes a confident list of what it did
# and calls no tool at all. A reported turn (§35B) narrated linking note 12 to
# three others and unlinking a fourth, having called `related_notes` once.
#
# That turn got past the original net twice over, and both gaps are worth
# naming because they are the shape of the next one:
#
# 1. The pattern only knew the first person singular, "I linked". The model
#    wrote "**Linked Notes:** We connected your main Social Skills Guide to…"
#    and "we" matched nothing.
# 2. It asked one question of the whole turn, "did *any* write run?", so a
#    turn that legitimately linked one pair and then claimed four more passed
#    on the strength of the one that was real.
#
# So claims are matched *per action* and checked against the tools that
# actually ran. That is §33's "completion verifier" in its cheap form: no
# second model round, just what was said against what was called.

#: Who the model says did it. Past and perfect only, "we could link these" is
#: a suggestion and must not be reported as a false claim.
_CLAIMANT = r"(?:i|we)(?:'ve)?\s+(?:have\s+|just\s+|now\s+|also\s+|then\s+|successfully\s+)*"

#: What was claimed, how it reads, and the tools that would make it true.
#: The label is written to be shown to the user, because a warning that says
#: *which* claim was unsupported is actionable where "something" is not.
_CLAIMED_ACTIONS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        # `create_document` counts here too: "I wrote that up for you" is a
        # true claim when the document tool ran, and warning about it would be
        # the net crying wolf on work that really happened.
        "saved a note",
        r"(?:created|added|saved|made|wrote)",
        frozenset({"create_note", "create_document"}),
    ),
    ("edited a note", r"(?:edited|updated|rewrote|amended|revised)", frozenset({"edit_note"})),
    ("deleted a note", r"(?:deleted|removed|binned|trashed)", frozenset({"delete_note"})),
    (
        "tagged a note",
        r"(?:tagged|re-?tagged|labelled|labeled)",
        frozenset({"tag_note", "rename_tag"}),
    ),
    ("pinned a note", r"(?:pinned|unpinned)", frozenset({"pin_note"})),
    # Checked before "linked": \b keeps "linked" from matching inside
    # "unlinked", but the ordering makes that guarantee visible rather than
    # something a reader has to work out from the regex.
    (
        "unlinked notes",
        r"(?:unlinked|disconnected|detached)",
        frozenset({"unlink_notes"}),
    ),
    ("linked notes", r"(?:linked|connected)", frozenset({"link_notes"})),
    (
        "set a reminder",
        r"(?:set|scheduled|added)\s+(?:a|the|your)?\s*remind",
        frozenset({"set_reminder"}),
    ),
)

#: A verb carried on from an earlier subject: "I linked 12 to 13 **and
#: tagged** them both". Models write this constantly, and requiring an
#: explicit "I"/"we" in front of every verb missed the whole second half of
#: such a sentence. Only trusted once the answer has claimed something
#: outright somewhere: otherwise "the notes you tagged in March" would read
#: as a claim.
_CARRIED_ON = r"(?:and|then|,)\s+(?:also\s+|successfully\s+|later\s+)*"

_CLAIM_MATCHERS = tuple(
    (
        label,
        re.compile(rf"\b{_CLAIMANT}{verb}\b", re.IGNORECASE),
        re.compile(rf"\b{_CARRIED_ON}{verb}\b", re.IGNORECASE),
        needs,
    )
    for label, verb, needs in _CLAIMED_ACTIONS
)

# Kept because it is the cheapest check for the commonest case, a model that
# describes a note it never saved, and it catches phrasings with no claimant
# at all. Widened from the original to cover "we" as well as "I".
_CLAIM_PATTERN = re.compile(
    rf"\b({_CLAIMANT}(?:created|added|saved|made|updated|edited|deleted|tagged|"
    r"pinned|linked)|new note titled|created a? ?note)\b",
    re.IGNORECASE,
)


def unsupported_claims(answer: str, ran: set[str]) -> list[str]:
    """Actions the answer says happened that no tool call performed.

    `ran` is the write tools that actually executed this turn (or were parked
    for the user's approval, which is its own visible signal). A claim whose
    tool is in there is taken at face value, this is a net for fabrication,
    not an auditor of whether the right note was edited.
    """
    # Whether this answer speaks in the claiming voice at all. A carried-on
    # verb is only a claim inside a sentence that already made one, so this is
    # checked first and gates the looser half of every matcher below.
    claiming = any(direct.search(answer) for _, direct, _, _ in _CLAIM_MATCHERS)
    said = []
    for label, direct, carried, needs in _CLAIM_MATCHERS:
        hit = direct.search(answer) or (claiming and carried.search(answer))
        if hit and not (needs & ran):
            said.append(label)
    return said

# Agent-mode grounding: tool results are a legitimate second source.
AGENT_GROUNDING = (
    "Answer the user in plain English using ONLY the notes provided and "
    "your tool results. If neither answers the question, say so honestly."
)


def build_agent_messages(
    question: str,
    notes: list[dict],
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    budget: "context.ContextBudget | None" = None,
    mode: str | None = None,
    images: list[str] | None = None,
) -> list[dict]:
    """Like librarian.build_messages, but the system prompt allows
    acting, and each note shows its id so tools can target it.

    `budget` trims the notes and the history to what the model can actually
    hold. Optional so every existing caller keeps working untrimmed, the
    agent loop passes one, having measured the window first.
    """
    style_hint = librarian.STYLE_HINTS.get(style, librarian.STYLE_HINTS["friendly"])
    profile_hint = f" About the user: {profile.strip()}" if profile.strip() else ""
    persona = (persona_prompt or librarian.DEFAULT_PERSONA).strip()
    # The model needs "now" to turn "in 10 minutes" into a real time.
    from memorymap.core import deps
    from memorymap.core.config import user_now

    # The user's wall clock. This line is what "remind me in 10 minutes"
    # is computed from, so resolving it against the server's zone instead
    # puts every relative time out by the offset between them.
    local = user_now(deps.get_config())
    # To the minute, not the microsecond. This string sits near the top of a
    # prompt that is resent on every round of every turn, and Ollama's prefix
    # cache keeps only the tokens *before* the first difference, so a clock
    # that ticked every microsecond invalidated the history and the notes
    # below it every single time, and each round re-read the whole prompt from
    # scratch. A tool loop runs its rounds seconds apart, so a minute-precision
    # clock is identical across all of them, and no answer this app gives
    # needs the seconds: "remind me in 10 minutes" is not resolved to one.
    now_hint = (
        f" The current date and time is {local.replace(second=0, microsecond=0).isoformat()}"
        f" ({local.tzname() or 'local time'})."
    )
    # **The clock goes last, and that ordering is the whole point.** A
    # prefix cache (Ollama's, llama.cpp's, every backend that has one) keeps
    # the tokens *before the first difference* and re-reads everything after
    # it. Rounding to the minute above stops the clock changing between the
    # rounds of one turn; putting it at the end of the message stops the
    # minute it does change from invalidating anything ahead of it. Persona,
    # grounding and the tools guide, by far the largest part of this prompt,
    # and the part that is identical turn after turn, now sit in front of
    # every volatile byte, so they are re-read from cache instead of
    # re-processed. Asked for directly: "keep the system prompt + persona
    # byte-identical turn to turn so the cache is reused."
    #
    # Everything between them is stable *within* a conversation: the style
    # hint, the profile and the length hint only change when the user changes
    # a setting or the mode, which is a new prefix either way.
    messages = [
        {
            "role": "system",
            "content": f"{persona} {AGENT_GROUNDING} "
            f"{tools_guide(budget.window_tokens if budget else None)} "
            f"{style_hint}{profile_hint}{librarian.length_hint(mode)}{now_hint}",
        }
    ]
    past = librarian.history_messages(history)
    if budget is not None:
        past = context.fit_history(past, budget.history_chars)
    messages.extend(past)

    dropped_notes = 0
    if budget is not None:
        notes, dropped_notes = context.fit_notes(
            notes, budget.notes_chars, librarian.note_for_prompt
        )

    numbered = "\n".join(
        # Same caveats the plain (no-tools) librarian prompt already gives, 
        # attached-by-hand, linked-not-matched (with its reason, when the
        # link has one), similarity/keyword match info, reused rather than
        # left agent-mode-only silent about them. Nothing new to compute:
        # `prepared["notes"]` already carries this from routes_chat.py; the
        # agent path just never read it before.
        f"{i}. (note id {note.get('id', '?')}) [{note['category']}]"
        f"{' (attached by me)' if note.get('attached') else ''}"
        f"{' (not a match: linked to one of the above)' if note.get('connected') else ''}"
        f"{librarian._match_info_hint(note.get('match_info'))} "
        f"{librarian.note_for_prompt(note)}"
        for i, note in enumerate(notes, start=1)
    )
    body = f"My notes:\n{numbered}\n\n" if notes else "My notebook looks empty.\n\n"
    if dropped_notes:
        # Said rather than silently done. A model that knows its notes were
        # cut short can search for the rest; one that doesn't will answer as
        # though it saw the whole notebook, which is the confident-and-wrong
        # failure this app exists to avoid.
        body = (
            f"{body[:-2]}\n({dropped_notes} more matching note"
            f"{'' if dropped_notes == 1 else 's'} did not fit: use search_notes "
            f"or get_note if you need them.)\n\n"
        )
    user_message = {"role": "user", "content": f"{body}My request: {question}"}
    if images:
        user_message["images"] = images
    messages.append(user_message)
    return messages


# Handed back when an `ask_user` call is malformed, so the model can recover
# in the same turn instead of the question silently failing.
# What a turn-ending tool is told when its handover was malformed. Per tool,
# because the useful advice differs: a bad question is worth re-asking, a
# skill that doesn't exist usually means there was no skill for this job.
_HANDOFF_RECOVERY = {
    "ask_user": (
        "Fix the question and call ask_user again with 2-6 short options, or, "
        "if you can work it out yourself, just answer without asking."
    ),
    "run_skill": (
        "Call list_skills to see the exact names and what each one needs, then "
        "run_skill again: or, if none of them fits, just do the job yourself "
        "with the ordinary tools."
    ),
    "compress_chat": (
        "There isn't enough conversation yet to compress, keep going, or "
        "just answer without calling this."
    ),
}
_ASK_RECOVERY = _HANDOFF_RECOVERY["ask_user"]  # kept: named in tests and §33

# What the model is told when a destructive call is parked for approval.
AWAITING_CONFIRMATION = {
    "status": "awaiting_user_confirmation",
    "note": (
        "The app is showing the user a confirm button for this action. "
        "It has NOT run yet, tell the user it's waiting for their approval."
    ),
}


#: How much of the previous exchange a follow-through turn is read against.
#: Two turns' worth of text, capped, this is only ever used for keyword
#: matching, so the whole of a long answer adds nothing but false positives
#: from words the model happened to use in passing.
FOLLOW_THROUGH_CONTEXT_CHARS = 1_200


def _recent_text(history: list[dict] | None) -> str:
    """The last exchange, as plain text, for reading a follow-through against.

    Newest first and clipped, so what survives the cap is the turn the user is
    actually following through *on* rather than the start of the conversation.
    """
    if not history:
        return ""
    parts: list[str] = []
    for turn in reversed(history[-2:]):
        for key in ("question", "answer", "content"):
            value = turn.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
    # Clipped once, at the end, rather than per piece: clipping each and then
    # joining put the separators outside the budget, so the cap was not a cap.
    return " ".join(parts)[:FOLLOW_THROUGH_CONTEXT_CHARS]


def _focus(question: str, history: list[dict] | None = None) -> list[str] | None:
    """Which tools this turn is offered, unless the user asked for all of them.

    Settings → Tools has the switch, because the honest failure mode of a
    keyword rule is a request phrased in words it doesn't know, and the fix
    for that has to be reachable without editing code.

    `history` is passed so a turn that means "now do what we just discussed"
    can be read against what was discussed, reported directly, and the cause
    of an agent that answered "implement those suggestions" with the same
    suggestions again. See `tools.focus_for`.
    """
    from memorymap.core import deps

    if str(deps.get_config().get_preference("tool_focus", "auto")) == "all":
        return None
    return tools.focus_for(question, _recent_text(history))


def run_agent(
    session: Session,
    question: str,
    notes: list[dict],
    model_manager: ModelManager,
    ollama: OllamaClient,
    style: str = "friendly",
    profile: str = "",
    history: list[dict] | None = None,
    persona_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    blocked_tools: frozenset[str] | set[str] | None = None,
    max_rounds: int = MAX_ROUNDS,
    earned_rounds: int = EARNED_ROUNDS,
    exhausted_note: str | None = None,
    mode: str | None = None,
    use_utility_model: bool = False,
    images: list[str] | None = None,
    model_override: str | None = None,
    image_context: str | None = None,
) -> Iterator[dict]:
    """Yields event dicts:
    {"type": "unsupported"}, model can't do tools; caller
                                                 should fall back to plain Q&A
                                                 (always the first and only event)
    {"type": "thinking", "delta": str}
    {"type": "tool", "label": str, "ok": bool, "error": str|None}
    {"type": "confirm", "name", "arguments", "label"}
    {"type": "limit", "reason": "rounds", ...}, ran out of rounds mid-job;
                                                 the answer that follows is a
                                                 stopping notice, not a result
    {"type": "answer", "delta": str}: the final text
    """
    # Size the whole turn against the window before building any of it.
    #
    # Every part used to carry its own constant, each reasonable alone and
    # never added up: the worst case came to ~11,300 tokens against a 4,096
    # window, and the tool-result cap alone exceeded that window by half.
    # Overflow is dropped from the FRONT, so the failure is not an error, it
    # is the model quietly losing its system prompt and answering from nothing.
    report = getattr(ollama, "usable_context", None)
    agent_model = model_override or (
        model_manager.utility_model() if use_utility_model else model_manager.chat_model()
    )
    window = report(agent_model) if callable(report) else None
    persona = memory.persona_with_memory(session, persona_prompt)

    system_chars = len(
        f"{persona} "
        f"{AGENT_GROUNDING} {tools_guide(window)}{librarian.length_hint(mode)}"
    )
    budget = context.plan(
        window or OllamaClient.DEFAULT_CONTEXT_TOKENS, system_chars
    )
    logging.getLogger("memorymap.agent").info(budget.as_log_line())

    # Same fallback as librarian.answer()/converse(): a vision model's own
    # caption of an attached image, for when agent_model above can't see the
    # image itself: folded into the question text here rather than mutating
    # `question` in place, since later rounds of this same loop reuse it.
    full_question = f"{question}\n\n{image_context}" if image_context else question
    messages = build_agent_messages(
        full_question,
        notes,
        style=style,
        profile=profile,
        history=history,
        persona_prompt=persona,
        budget=budget,
        mode=mode,
        images=images,
    )
    # A skill's declared tools are the only ones offered for its run: fewer
    # schemas on the wire (roadmap §11a) and a narrower thing to go wrong.
    # An ordinary turn declares nothing, so the question is read for what it
    # plausibly needs: see tools.focus_for. Note the asymmetry: the skill's
    # list is also *enforced* below, while the focus is only an economy. A
    # tool left out because a cue didn't fire must still run if the model
    # somehow calls it.
    focus_names = (
        allowed_tools if allowed_tools is not None else _focus(question, history)
    )
    offered = tools.ollama_tools(focus_names)
    # Tools this turn may not use whatever it was offered. The one caller is a
    # run refusing to start another run (`tools.RUN_STARTERS`): each run brings
    # its own fresh rounds, so nesting them means the bound on a turn stops
    # meaning anything, and the plan on screen stops describing what is
    # happening. Withdrawn from the wire *and* refused below, because a model
    # that calls a tool it was never offered must not get it either.
    barred = set(blocked_tools or ())
    if barred:
        offered = [t for t in offered if t["function"]["name"] not in barred]
    # On a small window, trim the descriptions even when the full set would
    # fit. `within_budget` compacts only once the schemas overflow their share,
    # which is the right rule for a large model, but on an 8k window the
    # focused set measured 4,827 chars against a 7,901-char allowance, so it
    # "fits" and is sent in full, spending 1,206 tokens where 996 does the same
    # job. Affordable is not the same as wise: what the allowance leaves unspent
    # is what the notes and the conversation get, and on a small model those are
    # exactly what runs out first.
    #
    # Safe for a skill's declared list too (hence above the `allowed_tools`
    # branch): compaction never removes a tool, so nothing a skill asked for
    # can go missing this way.
    if budget is not None and budget.window_tokens <= SMALL_WINDOW_TOKENS:
        offered = tools.compact_schemas(offered)
    # Then fit what is left to the window the model actually has, rather than
    # to a constant. See tools.within_budget: 4096 is Ollama's fallback, not a
    # fact, and a model declaring 32k was being rationed as if it were a 3B.
    # A skill's declared list is exempt, it asked for exactly those tools, and
    # silently dropping one would break the run rather than trim it.
    # --- the focus is a guess, and the model gets to overrule it ---------------
    #
    # `focus_for` reads the words of the question to decide which tools are
    # worth the room. It is deterministic and testable, and it is still a guess:
    # a request can want a tool whose name shares no word with it. So the guess
    # is never allowed to be final.
    #
    # Two mechanisms, and they are different things. The escape hatch already
    # existed: `permitted` is None on an ordinary turn, so a tool the model
    # calls anyway still runs even if it was never offered. What is added here
    # is the correction: a call for something unoffered is *evidence the focus
    # was wrong*, so the next round of this same turn gets the full toolbox
    # rather than the same narrow guess that already failed the model once.
    #
    # This is why the focus can afford to be narrow. A wrong guess costs one
    # round, not the request.
    focused_only = allowed_tools is None
    every_tool = offered
    # Say so, once, in the system prompt, but only when the list really was
    # narrowed. On a broad request the model already has everything, and a note
    # explaining that the list is partial would simply be false.
    if focused_only and focus_names is not None and messages:
        messages[0]["content"] += FOCUS_NOTE
    if allowed_tools is None:
        every_tool = tools.ollama_tools()
        if barred:
            every_tool = [
                t for t in every_tool if t["function"]["name"] not in barred
            ]
        if budget is not None and budget.window_tokens <= SMALL_WINDOW_TOKENS:
            every_tool = tools.compact_schemas(every_tool)
        every_tool, _ = tools.within_budget(every_tool, budget.tool_schema_chars)
        offered, dropped = tools.within_budget(offered, budget.tool_schema_chars)
        if dropped:
            # Visible in Settings → Logs, because "the AI didn't use the tool I
            # expected" is otherwise indistinguishable from the model choosing
            # not to.
            logging.getLogger("memorymap.agent").info(
                "tool budget: %d-token window fits %d tools; held back %s",
                budget.window_tokens,
                len(offered),
                ", ".join(dropped[:8]) + ("…" if len(dropped) > 8 else ""),
            )
    # Roadmap §11a's prescribed first step: measure before cutting. One line
    # per turn saying what the prompt is made of, so "which half dominates a
    # real chat: the notes or the history?" is answered from the log rather
    # than argued about. Chars, not tokens: the ratio is what matters, and
    # the true token counts already arrive in each round's stats event.
    system_chars = len(messages[0]["content"])
    history_chars = sum(len(m["content"]) for m in messages[1:-1])
    notes_chars = len(messages[-1]["content"])
    tool_schema_chars = len(json.dumps(offered))
    logging.getLogger("memorymap.agent").info(
        "prompt composition: system=%d history=%d notes+question=%d "
        "tool_schemas=%d chars (%d tools offered)",
        system_chars,
        history_chars,
        notes_chars,
        tool_schema_chars,
        len(offered),
    )
    # §88.4 item 4's next step past the log line above: the same breakdown,
    # as a rough token estimate (chars/4: the same approximation
    # ai/context.py's own budgeting uses), attached to the first round's
    # stats event so the UI's metadata line can show it rather than it
    # being visible only in Settings -> Logs. Measured once, here, before
    # the loop below appends any tool-result rounds to `messages`, a
    # later round's true composition would need re-measuring inside the
    # loop, which this does not attempt; the first round is also the one
    # every turn actually has, tool calls or not.
    composition_tokens = {
        "system": system_chars // context.CHARS_PER_TOKEN,
        "history": history_chars // context.CHARS_PER_TOKEN,
        "notes": notes_chars // context.CHARS_PER_TOKEN,
        "tool_schemas": tool_schema_chars // context.CHARS_PER_TOKEN,
    }
    permitted = set(allowed_tools) if allowed_tools else None
    did_write = False  # did any real write tool run this turn?
    # *Which* ones ran, so a claim can be checked against the action that
    # would have made it true rather than against the turn as a whole. A
    # turn that legitimately linked one pair and then claimed four more
    # passed the old boolean on the strength of the one that was real.
    ran_writes: set[str] = set()
    spent = 0  # characters of tool output added to the conversation so far
    # (tool, arguments) pairs that have already failed, so a model looping on
    # the same broken call can be told so rather than burning every round.
    failed_calls: set[tuple[str, str]] = set()
    # **How many times each tool has failed this turn, regardless of its
    # arguments.** `failed_calls` above only catches a model repeating the
    # *identical* call, and the loop this exists for never does that.
    #
    # Reported with a live log: the agent called `merge_categories` over and
    # over, alternating between "There is no category called X" and "X and X
    # are the same category", different arguments every round, so the
    # signature guard never fired once, and the turn burned every round it
    # had before telling the user nothing. The tool's own error message even
    # listed the real category names (see `_find_category`), so this is not
    # fixable by explaining harder: a small model that has misunderstood
    # *what the tool is for* will keep producing fresh wrong arguments for it
    # indefinitely. The only thing that ends that is taking the tool away.
    tool_failures: dict[str, int] = {}
    # Destructive calls parked for the user's approval this turn, per tool.
    parked: dict[str, int] = {}

    def _count_failure(tool_name: str) -> int:
        tool_failures[tool_name] = tool_failures.get(tool_name, 0) + 1
        return tool_failures[tool_name]

    # …and the ones that have already *succeeded*, which is the other half of
    # the same idea: a repeat of a call that worked is not progress either. The
    # model has that result in its context already.
    done_calls: set[tuple[str, str]] = set()

    # Reads whose result is already in this turn's messages and still current.
    # Separate from `done_calls` on purpose: that one is the earned-round
    # ledger and must never be cleared, while this is a freshness cache and is
    # emptied the moment a write makes the notebook different from what these
    # reads saw.
    fresh_reads: set[tuple[str, str]] = set()

    # Rounds are granted, then earned (see EARNED_ROUNDS). `allowance` is what
    # this turn has so far; a round that does something new adds one to it, up
    # to `ceiling`. A turn that loops never adds anything and stops where the
    # flat cap always stopped it.
    granted = max(1, max_rounds)
    ceiling = granted + max(0, earned_rounds)
    allowance = granted
    round_number = -1

    #: **The run this turn belongs to, if it belongs to one** (Brief 13).
    #: None for an ordinary chat turn: that is bounded per turn already, by
    #: `allowance` immediately below, and has no notion of a run to belong to.
    #: See `ai/budget.py` for why this is a scope rather than a parameter.
    spend = run_budget.current()

    while round_number + 1 < allowance:
        #: Checked between rounds, never mid-stream: stopping inside a model
        #: call would leave half an answer on screen and a tool result nobody
        #: read, so the most a run can overshoot its budget by is one round.
        if spend is not None and spend.exceeded():
            yield {
                "type": "limit",
                "reason": "budget",
                "detail": spend.exceeded(),
                "rounds": round_number + 1,
                "tokens": spend.spent_tokens,
                "wrote": sorted(ran_writes),
            }
            yield {
                "type": "answer",
                "delta": f"I stopped here: {spend.exceeded()}",
            }
            return
        round_number += 1
        # Set by any tool call that succeeded and had not been made before, 
        # the definition of "this round got somewhere". Read at the bottom of
        # the loop, where it buys the next round.
        progressed = False
        # Streamed: the model's prose reaches the user as it's written. The
        # non-streamed call this used to make is why an agent answer landed in
        # one lump after a visible pause (user-reported): every other chat
        # path streamed, and the default path (tools on) didn't.
        reply: dict = {}
        streamed_any = False
        try:
            for piece in ollama.chat_tools_stream(agent_model, messages, offered, mode=mode):
                if "thinking_delta" in piece:
                    yield {"type": "thinking", "delta": piece["thinking_delta"]}
                elif "content_delta" in piece:
                    streamed_any = True
                    yield {"type": "answer", "delta": piece["content_delta"]}
                elif "final" in piece:
                    reply = piece["final"]
        except ToolsUnsupportedError:
            yield {"type": "unsupported"}
            return
        except OllamaError as exc:
            # Mid-answer death: say so, but don't wipe what already streamed.
            # `offline: True` alongside the normal answer shape (Tier 1 §3): 
            # an ordinary chat turn renders this exactly like any other
            # answer and needs no change, but skill_runner cannot tell this
            # boilerplate apart from a real answer without it, and was
            # ticking the step "done" and moving on to repeat the identical
            # failure on every later step. `skill_runner` only ever checks
            # this flag's truthiness (never the message text), so swapping
            # in the real error below changes nothing about that contract.
            #
            # This used to be librarian.OFFLINE_MESSAGE unconditionally, 
            # "Ollama doesn't seem to be running", which is simply false
            # whenever this except is reached at all (the loop had already
            # gotten at least one successful round trip to be here) and the
            # same misdiagnosis routes_chat.py's plain_events() had for the
            # Ask mode (see librarian.model_error_message's own docstring).
            # Logged too, for the same reason that fix added logging: this
            # failure used to reach the chat bubble but never Settings → Logs.
            logging.getLogger("memorymap.chat").warning(
                "agent: model call failed for %r: %s", agent_model, exc
            )
            prefix = "\n\n" if streamed_any else ""
            yield {
                "type": "answer",
                "delta": f"{prefix}{librarian.model_error_message(agent_model, exc)}",
                "offline": True,
            }
            return

        # Report what this round cost. Agent turns used to emit nothing here,
        # so switching tools on, the default, silently stripped the token
        # counts out of the message metadata line.
        # Charged whatever the provider reported, once per round, before
        # anything is done with the result: a round that ran is a round that
        # cost something even if the answer it produced is thrown away.
        if spend is not None:
            spend.charge(reply.get("stats"))
        if reply.get("stats"):
            stats = {**reply["stats"], "round": round_number + 1}
            if round_number == 0:
                stats["composition"] = composition_tokens
            yield {"type": "stats", **stats}

        calls = reply.get("tool_calls") or []
        if not calls:
            # No tools wanted → this text IS the final answer. It has usually
            # already streamed; send it only if the tool-call gate held it back.
            answer = reply.get("content", "").strip()
            if not reply.get("streamed") and answer:
                yield {"type": "answer", "delta": answer}
            # Safety net: if the model claims it saved/created something but no
            # write tool actually ran, it hallucinated, say so instead of
            # letting the user believe a note exists that doesn't.
            unsupported = unsupported_claims(answer, ran_writes)
            if unsupported:
                # Named, not vague. "It looks like I didn't actually save it"
                # is useless when the answer claimed five different things, 
                # the user needs to know which of them did not happen, because
                # the rest of the list may well be true.
                listed = ", ".join(unsupported)
                yield {
                    "type": "answer",
                    "delta": (
                        f"\n\nHeads up: I said I {listed}, but I didn't "
                        "actually run the tool that does it, so that part did "
                        "not happen and nothing was changed by it. Ask me again "
                        "and I'll do it properly."
                    ),
                }
            elif not did_write and _CLAIM_PATTERN.search(answer):
                # The looser net, for a claim with no recognisable action in
                # it ("new note titled…"). Only when nothing at all was
                # written, since it can't say which action it means.
                yield {
                    "type": "answer",
                    "delta": (
                        "\n\nHeads up: I described that, but it looks like I "
                        "didn't actually save it (my model didn't run the tool). "
                        "Nothing was changed: try again, or paste the text into "
                        "a new note yourself."
                    ),
                }
            return

        # Replay the assistant turn (with its calls) so the model keeps
        # its own context, then answer each call.
        #
        # **Including the round's own reasoning**, asked for directly: *"it
        # often thinks up this whole plan, then it does a tool call and either
        # loses track or has to rethink the plan again."* That is exactly what
        # happened: `thinking` was streamed to the user and then dropped, so
        # the next round saw its own tool calls with no record of why it made
        # them, and a thinking model spent its output budget re-deriving the
        # same plan every round.
        #
        # Carried as content rather than as a `thinking` field because that
        # field is not portable: Ollama accepts one, the OpenAI-compatible
        # dialect does not, and a message shape one backend rejects is an
        # outage rather than a degradation. Marked and clipped, so it reads as
        # a note-to-self and cannot grow into the round's whole budget.
        replay = reply.get("content") or ""
        reasoning = (reply.get("thinking") or "").strip()
        if reasoning:
            clipped = reasoning[:THINKING_CARRIED_CHARS]
            if len(reasoning) > THINKING_CARRIED_CHARS:
                clipped += "…"
            replay = f"[my reasoning so far: {clipped}]{chr(10) if replay else ''}{replay}"
        messages.append(
            {
                "role": "assistant",
                "content": replay,
                "tool_calls": reply.get("raw_tool_calls") or [],
            }
        )
        # Did the model reach for something it was not shown? Then the focus
        # misread the request, and the rounds after this one should not be
        # working from the same misreading. Widening is deliberately one-way
        # and lasts the rest of the turn: a request whose subject the words did
        # not carry does not become readable later in the same turn.
        if focused_only and offered is not every_tool:
            shown = {t["function"]["name"] for t in offered}
            reached_past = [c["name"] for c in calls if c["name"] not in shown]
            if reached_past:
                logging.getLogger("memorymap.agent").info(
                    "focus corrected: model called %s, which the question's "
                    "words did not suggest, offering the full set from here",
                    ", ".join(sorted(set(reached_past))[:5]),
                )
                offered = every_tool

        for call in calls:
            name, arguments = call["name"], call.get("arguments") or {}
            spec = tools.TOOLS.get(name)
            signature = (name, json.dumps(arguments, sort_keys=True))
            if name in barred:
                # A run trying to start a run. Refused with the reason, not
                # silently: the model asked for this because it has decided the
                # job is bigger than one step, and the useful answer is "you
                # are already inside the mechanism you are reaching for".
                failed_calls.add(signature)
                _count_failure(name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(
                            {
                                "error": f"{name} cannot be used inside a run",
                                "what_to_do": _RECOVERY_HINTS["already_running"],
                            }
                        ),
                    }
                )
                yield {
                    "type": "tool",
                    "label": f"ph:warning {name.replace('_', ' ')} isn't available here",
                    "ok": False,
                    "error": f"{name} cannot be used inside a run",
                }
                continue
            if permitted is not None and name not in permitted:
                # The allowlist is a safety property, not only a prompt: a
                # model that calls a tool it was never offered does not get to
                # run it just because the registry has one by that name.
                result = {"error": f"{name} is not part of this skill's tools"}
                result["what_to_do"] = (
                    REPEATED_CALL_NOTE
                    if signature in failed_calls
                    else _RECOVERY_HINTS["not_in_skill"]
                )
                failed_calls.add(signature)
                _count_failure(name)
                yield {
                    "type": "tool",
                    "label": f"ph:warning {name} isn't part of this skill",
                    "ok": False,
                    "error": result["error"],
                }
            elif spec is not None and spec.ends_turn:
                # `ask_user` and `run_skill`. The turn stops here, and in both
                # cases that is the feature rather than a limitation: the model
                # asked because it does not know what to do next, or it handed
                # the job to a skill that will do it step by step. Carrying on
                # after either would mean carrying on with the guess the
                # handover exists to avoid.
                #
                # No state is parked on the server. The user's choice: or the
                # skill run: is sent as the next message, which means it
                # arrives through the ordinary history the model already reads:
                # nothing to expire, nothing to lose on a reload, and the
                # exchange is visible in the saved conversation like any other.
                try:
                    handover = tools.handoff_event(name, arguments, history)
                except tools.ToolError as exc:
                    # A malformed question, or a skill named that doesn't
                    # exist. Recoverable mistakes, not dead turns: hand the
                    # model the reason and let it try again or answer directly.
                    failed_calls.add(signature)
                    _count_failure(name)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(
                                {
                                    "error": str(exc),
                                    "what_to_do": _HANDOFF_RECOVERY.get(
                                        name, _ASK_RECOVERY
                                    ),
                                }
                            ),
                        }
                    )
                    yield {
                        "type": "tool",
                        "label": f"ph:warning couldn't {name.replace('_', ' ')}",
                        "ok": False,
                        "error": str(exc),
                    }
                    continue
                yield handover
                return
            elif spec is not None and spec.destructive and parked.get(name, 0) >= MAX_PARKED_CONFIRMS:
                # **A destructive tool cannot paper the turn with confirm
                # cards.** Parking one hands the model `AWAITING_CONFIRMATION`
                # rather than a result, which is honest but is not a *stop*:
                # a model that has misread the job re-parks the same tool with
                # fresh arguments, and every round of that is another card in
                # front of the user for something they never asked for. Two is
                # enough for a genuine "delete this, and that" turn; past that
                # the model is guessing, and guessing at destructive calls is
                # the one place this app should be least willing to keep up.
                result = {
                    "error": (
                        f"{name} is already waiting for the user's approval "
                        f"{parked[name]} times in this turn. Nothing more can be "
                        "queued for them."
                    ),
                    "what_to_do": (
                        "Stop. The user has to approve what is already waiting "
                        "before anything else destructive can be prepared. Tell "
                        "them what is queued and why, and do not call this tool again."
                    ),
                }
                _count_failure(name)
                yield {
                    "type": "tool",
                    "label": f"ph:prohibit {name.replace('_', ' ')}, too many waiting for approval",
                    "ok": False,
                    "error": result["error"],
                }
            elif spec is not None and spec.destructive:
                # Park it for the user, never auto-run a destructive tool.
                # The confirm card is the honest signal, so count it as an
                # action (don't fire the "nothing happened" safety net): the
                # user can see for themselves that it is waiting on them.
                did_write = True
                ran_writes.add(name)
                parked[name] = parked.get(name, 0) + 1
                yield {
                    "type": "confirm",
                    "name": name,
                    "arguments": arguments,
                    "label": tools.confirm_label(name, arguments),
                }
                result = AWAITING_CONFIRMATION
            elif tool_failures.get(name, 0) >= MAX_TOOL_FAILURES:
                # **The tool is spent for this turn.** Unlike the signature
                # check just below, this fires however much the arguments
                # change: which is the whole point, since the loop it was
                # written for produced fresh wrong arguments every round (see
                # `tool_failures`). Blocked *before* execution, so a tool that
                # writes cannot land a change on a fourth guess either.
                result = {
                    "error": (
                        f"{name} has failed {tool_failures[name]} times in this "
                        "turn and is no longer available for it"
                    ),
                    "what_to_do": TOOL_EXHAUSTED_NOTE,
                }
                yield {
                    "type": "tool",
                    "label": f"ph:prohibit {name.replace('_', ' ')}, stopped after repeated failures",
                    "ok": False,
                    "error": result["error"],
                }
            elif signature in failed_calls:
                # --- NEW INTERCEPTION: Duplicate Failed Calls ---
                # The model is looping on a broken call. Intercept before execution.
                # Counted as a failure too, so a model that alternates between
                # repeating a call and inventing new arguments for the same
                # tool still reaches MAX_TOOL_FAILURES rather than ping-ponging
                # between the two interceptions forever.
                _count_failure(name)
                result = {
                    "error": (
                        f"You already called {name} with these exact arguments "
                        "and it failed. You must try a different approach, "
                        "change your arguments, or stop and ask the user."
                    ),
                    "what_to_do": REPEATED_CALL_NOTE,
                }
                yield {
                    "type": "tool",
                    "label": f"ph:warning {name.replace('_', ' ')}, repeated failure",
                    "ok": False,
                    "error": "Repeated failure intercepted",
                }
            elif signature in done_calls and name in _WRITE_TOOLS:
                # --- NEW INTERCEPTION: Duplicate Writes ---
                # A write that already succeeded this turn. Intercept before executing again.
                result = {
                    "error": (
                        f"You already called {name} with these exact arguments "
                        "earlier in this turn and it succeeded. Do not run the same "
                        "write tool twice with the same arguments."
                    ),
                    "what_to_do": "Move on to the next step of your plan.",
                }
                yield {
                    "type": "tool",
                    "label": f"ph:warning {name.replace('_', ' ')}, already done",
                    "ok": False,
                    "error": "Duplicate write intercepted",
                }
            # --- OLD: elif (name, json.dumps(arguments, sort_keys=True)) in fresh_reads: ---
            elif (name, json.dumps(arguments, sort_keys=True)) in fresh_reads:
                # note's context in full, after no changes."*
                #
                # Re-running it is not merely wasted time, the result is
                # identical and gets appended to the prompt a second time, so
                # the round that repeats a read costs the window twice and
                # brings back nothing. Handing back a pointer instead is
                # cheaper than the data by an order of magnitude and says the
                # one thing the model needs to hear: you already have this,
                # move on.
                #
                # `done_calls` is emptied whenever a write succeeds (below), so
                # this can never serve a stale read of something the turn
                # itself just changed: which is the only way a cache here
                # could produce a wrong answer rather than a slow one.
                result = {
                    "already_done": True,
                    "note": (
                        f"You already called {name} with these exact arguments. "
                        "The information was provided in your previous tool calls "
                        "above. Please refer to your chat history to find it, rather "
                        "than running the tool again, and move on."
                    ),
                }
                yield {
                    "type": "tool",
                    "label": f"↩︎ {name.replace('_', ' ')}, already read",
                    "ok": True,
                }
            else:
                result = tools.execute_tool(session, name, arguments, context_tokens=window)
                # What changed, and the call that would put it back. Popped
                # rather than read: `undo` is for the user, and every field
                # left in the result is resent to the model on every later
                # round of the turn.
                undo = result.pop("undo", None)
                change = None
                signature = (name, json.dumps(arguments, sort_keys=True))
                if "error" not in result and signature not in done_calls:
                    # Something new worked. That is what buys another round, 
                    # see EARNED_ROUNDS. Reads and writes both count: paging
                    # through a notebook to find the right note is the work,
                    # not a preamble to it.
                    done_calls.add(signature)
                    progressed = True
                if "error" not in result and name not in _WRITE_TOOLS:
                    # Its result is now in the messages above, and stays valid
                    # until something writes.
                    fresh_reads.add(signature)
                if "error" not in result and name in _WRITE_TOOLS:
                    did_write = True
                    ran_writes.add(name)
                    # The notebook just changed, so every read taken before now
                    # may be out of date. Clearing this is what keeps the
                    # repeat-suppression above from ever serving a stale
                    # answer: after a write, re-reading is legitimate work
                    # rather than a loop, and it has to be allowed through.
                    #
                    # Deliberately *not* `done_calls`, which is the earned-round
                    # ledger: clearing that would let a model repeating one
                    # identical write buy a fresh round every time it did so,
                    # which is the exact loop EARNED_ROUNDS exists to starve.
                    #
                    # Deliberately not `failed_calls` either, for the same
                    # reason one step removed. A write briefly cleared it here,
                    # which sounds symmetrical and is not: a call that failed on
                    # its own arguments, a bad note id, a malformed date, fails
                    # again for exactly the same reason after an unrelated note
                    # is written, and forgetting it hands the model back the
                    # infinite retry that `_RECOVERY_HINTS` and the repeat
                    # interception exist to break. Only a read can go stale.
                    fresh_reads.clear()
                    change = {
                        "tool": name,
                        "label": result.get("label") or name,
                        "note_id": _change_note_id(name, result),
                        "document_id": _change_document_id(name, result),
                        "reminder_id": _change_reminder_id(name, result),
                        "category_name": _change_category_name(name, result),
                        "undo": undo,
                    }
                if "error" in result:
                    # Hand back advice with the error, not just the error.
                    repeated = signature in failed_calls
                    failed_calls.add(signature)
                    exhausted = _count_failure(name) >= MAX_TOOL_FAILURES
                    result = {
                        **result,
                        "what_to_do": (
                            # Said on the failure that *reaches* the cap, not
                            # only on the blocked call after it, otherwise the
                            # model spends one more round discovering a rule it
                            # could have been told here.
                            TOOL_EXHAUSTED_NOTE
                            if exhausted
                            else REPEATED_CALL_NOTE
                            if repeated
                            else _recovery_hint(name, str(result["error"]))
                        ),
                    }
                event = {
                    "type": "tool",
                    #: **The tool's own name.** The front end has always tried
                    #: to read it (`SOURCE_TOOLS[event.tool || event.name]`,
                    #: app.js) and it was never sent, so every web page and
                    #: every file this app read was silently missing from the
                    #: answer's Sources panel: a feature that could not have
                    #: worked once.
                    "tool": name,
                    "label": result.get("label") or name,
                    "ok": "error" not in result,
                    "error": result.get("error"),
                    "arguments": arguments,
                    #: Titles, addresses and one line each of what was read, 
                    #: see `_tool_sources`. This is what the Sources panel
                    #: draws its cards, previews and links from.
                    "sources": _tool_sources(name, result),
                    # UI display only: the version fed back to the model as
                    # conversation context is `payload` below, with its own
                    # separate, real token budget (`result_cap`). This is just
                    # what the chat transcript's tool-call disclosure shows,
                    # and that box already scrolls (.tool-chip-result, 12rem
                    # max-height): 300 chars cut it down to a couple of
                    # lines for no reason tied to cost. Reported live: "make
                    # the tool call output view a scrollable text box rather
                    # than it being truncated", the box already was one;
                    # this is what was starving it. 4000 is generous enough
                    # that raw JSON from a typical note/search/fetch result
                    # reads in full, while still bounding a pathological
                    # single result (a huge page fetch) from bloating the
                    # SSE event.
                    "result_summary": _result_summary(result),
                    # What this call actually touched, for the chat's live
                    # action line: see `_touched_items`.
                    "touched": _touched_items(result),
                    #: **The ids this read returned, and whether there are
                    #: more pages of them** (Brief 13; CHAT_PLAN decision 10).
                    #: A paging read already tells the *model* there is more
                    #: (`note_to_model`, `next_offset`); nothing told the
                    #: *app*, so `skill_runner` could only see that a tool had
                    #: been called once and ticked the step off with four
                    #: fifths of the notebook unread. Read off the result here
                    #: rather than parsed back out of `result_summary` in the
                    #: runner: the shape is this module's to know, and a
                    #: regex over a truncated JSON blob is the version of this
                    #: that breaks silently.
                    "seen": _seen_ids(result),
                    "more": bool(result.get("has_more")),
                    "next_offset": result.get("next_offset"),
                    #: **The same call, as things with actions** (PLAN.md §4
                    #: A1). `touched` is notes and documents; this is all five
                    #: kinds: a file, a board and a reminder are equally
                    #: openable and had no representation at all. Kept beside
                    #: `touched` rather than replacing it because a saved
                    #: transcript from before this existed has only `touched`,
                    #: and `skill_runner._absorb` reads it to carry ids across
                    #: a run's steps.
                    "cards": cards.result_cards(name, result),
                }
                if change:
                    event["change"] = change
                if result.get("proposal"):
                    # `save_user_preference` no longer saves anything: it asks.
                    # The row exists but is inactive and flagged `proposed`, and
                    # it stays out of every system prompt until somebody says
                    # yes. Carrying the id and the text on the event is what
                    # lets the chat draw the accept/decline card next to the
                    # tool chip, so the answer is given where the suggestion was
                    # made rather than three clicks away in Settings.
                    event["proposal"] = result["proposal"]
                yield event
            payload = json.dumps(result)
            # The window's share, but never more than the absolute ceiling, 
            # a 128k model would otherwise be allowed tens of thousands of
            # tokens of tool output, which is prefill time on every subsequent
            # round for material the model has usually finished with.
            result_cap = min(budget.tool_result_chars, TOOL_RESULT_BUDGET_CHARS)
            if spent + len(payload) > result_cap:
                # Over budget. Hand back the notice instead of the result and
                # withdraw the tools, so the next round has to be an answer.
                # Dropping the result rather than truncating it is deliberate:
                # half a JSON object is worse than none, the model reads it
                # as data and answers from a note that got cut mid-sentence.
                payload = json.dumps(BUDGET_EXHAUSTED)
                offered = []
            spent += len(payload)
            messages.append(
                {"role": "tool", "tool_name": name, "content": payload}
            )

        if progressed and allowance < ceiling:
            # This round did something new, so the turn gets another one. The
            # cap that stops a runaway is still there, a round that repeats
            # itself or errors buys nothing, so a loop never reaches `ceiling`.
            allowance += 1

    # Out of rounds with tools still being called: the job is unfinished, and
    # saying so is the honest end. The `limit` event is what distinguishes this
    # from an answer: the skill runner uses it to mark the step stalled rather
    # than ticking it off, and the chat UI uses it to offer Continue instead of
    # making the user type "carry on" (both reported: a run that "cuts out half
    # way through and has to restart").
    yield {
        "type": "limit",
        "reason": "rounds",
        "rounds": round_number + 1,
        "wrote": sorted(ran_writes),
    }
    yield {
        "type": "answer",
        "delta": exhausted_note
        or (
            "I stopped after "
            f"{round_number + 1} rounds of tool calls, here's where things "
            "stand. Continue and I'll pick up from here."
        ),
    }
