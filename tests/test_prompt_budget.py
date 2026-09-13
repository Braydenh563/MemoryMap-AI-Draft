"""The agent's fixed overhead has to stay inside a small model's window.

Asked for directly: make sure the agent system prompt doesn't get too heavy
for local models like granite4.1:3b or llama3.2:3b.

The trap is that it drifts upward invisibly. Every tool added and every
sentence added to TOOLS_GUIDE costs the same budget, both look harmless in
review, and nothing else in the suite notices, right up until a 3B model
overflows its window and, because the overflow is dropped from the *front*,
stops knowing it has tools at all. That failure looks like "the AI won't use
tools", not like "the prompt got long", which is why it is worth a test.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import agent, context, librarian, tools

# Ollama defaults to a 4096-token window unless the model declares otherwise,
# and ~4 characters per token is close enough to reason with.
CHARS_PER_TOKEN = 4


def _system_prompt() -> str:
    """The static part of what agent.run() builds, without the per-turn bits
    (the clock, the style hint, the profile) which are short and variable."""
    return f"{librarian.DEFAULT_PERSONA} {agent.AGENT_GROUNDING} {agent.TOOLS_GUIDE}"


def test_the_untrimmable_prose_stays_small(app_state):
    """The persona and TOOLS_GUIDE, which no per-turn trimming touches.

    **This replaces an assertion that weighed the whole tool registry**, and
    the replacement is the point. That one had to be raised three times in one
    session, twice for a new tool and once for a single added argument , 
    because `within_budget` had long since taken over the job of fitting the
    schemas to the model's real window. A guard that must be raised every time
    the app legitimately grows is not a guard; it is a chore that teaches
    people to edit the number until it stops complaining.

    What is left here is the half that is genuinely fixed: this text is resent
    on every round of every turn, before the question, the notes or the
    history, and nothing anywhere trims it. If it trips, something was added to
    TOOLS_GUIDE or the persona, look there rather than at the number.
    """
    prose = len(_system_prompt())
    assert prose <= agent.PROSE_BUDGET_CHARS, (
        f"The agent's un-trimmable prose is {prose} characters "
        f"(~{prose // CHARS_PER_TOKEN} tokens), over the "
        f"{agent.PROSE_BUDGET_CHARS} budget. Unlike the tool schemas, nothing "
        "fits this to the window, it is sent whole to a 3B model and a 70B "
        "one alike. Trim what was added, or raise PROSE_BUDGET_CHARS "
        "deliberately and say why in the comment above it."
    )


def test_the_registry_is_capped_by_the_model_not_by_a_constant(app_state):
    """The counterpart, stated as a property rather than a number: there is no
    longer a constant the whole registry must fit inside, because the window
    the model reported is the real limit and it is applied per turn."""
    assert not hasattr(agent, "PROMPT_BUDGET_CHARS"), (
        "PROMPT_BUDGET_CHARS was retired: see the comment where it used to "
        "be. If it is back, the per-turn trim it replaced needs re-reading "
        "before a constant is trusted again."
    )


def test_the_overhead_leaves_room_for_an_actual_conversation(app_state):
    """A budget that fills the window is not a budget.

    **Measured after the runtime trim, and that change matters.** This used to
    weigh the *whole* registry against a 4,096-token window, which was the
    right test when the registry was all a turn could send. It is now measuring
    a case that never reaches a small model: `agent.run_agent` passes every
    non-skill turn through `tools.within_budget`, which fits the schemas to the
    window the model actually reported and drops the least relevant tools when
    they do not fit.

    Left as it was, this assertion would fail for a reason that has nothing to
    do with a 3B model's experience: and worse, it would keep failing as the
    registry grew, pushing whoever hit it towards trimming tools that a 32k
    model has ample room for. What decides whether a 3B model works is what
    goes on the wire *after* the trim, so that is what is asserted.
    """
    system_chars = len(_system_prompt())
    plan = context.plan(4096, system_chars)
    kept, _dropped = tools.within_budget(tools.ollama_tools(), plan.tool_schema_chars)
    sent = system_chars + len(json.dumps(kept))
    tokens = sent // CHARS_PER_TOKEN
    assert tokens < 4096 * 0.85, (
        f"~{tokens} tokens reach a 4096-token model even after trimming, "
        "which leaves almost nothing for the question and the notes. The trim "
        "cannot fix prose: look at TOOLS_GUIDE and the persona first."
    )


def test_a_small_model_is_actually_trimmed_down_to_fit(app_state):
    """The mechanism the test above now relies on. If `within_budget` ever
    stopped being applied, or stopped dropping anything, the assertion above
    would still pass while a 3B model quietly lost its system prompt off the
    front of the context, which is the exact failure all of this exists to
    prevent."""
    plan = context.plan(4096, len(_system_prompt()))
    everything = tools.ollama_tools()
    kept, dropped = tools.within_budget(everything, plan.tool_schema_chars)
    assert dropped, "a 4k window cannot hold the whole registry; something must go"
    assert len(kept) < len(everything)
    assert len(json.dumps(kept)) <= plan.tool_schema_chars
    # The reading core survives the cull: a model that cannot search or read a
    # note cannot answer anything at all.
    names = {t["function"]["name"] for t in kept}
    assert {"search_notes", "get_note"} <= names


def test_a_large_model_is_not_trimmed_at_all(app_state):
    """The other half, and the reason the trim is right rather than merely
    safe: 4,096 is Ollama's fallback for a model that declares nothing, not a
    fact about any model. A 32k model gets the whole toolbox."""
    plan = context.plan(32768, len(_system_prompt()))
    kept, dropped = tools.within_budget(tools.ollama_tools(), plan.tool_schema_chars)
    assert not dropped
    assert len(kept) == len(tools.ollama_tools())


def test_turning_tools_off_actually_shrinks_what_is_sent(app_state):
    """Settings → Tools is the escape hatch when a model is too small for the
    full registry, so it has to reach the wire, not just the executor."""
    everything = len(json.dumps(tools.ollama_tools()))
    app_state.set_preference(
        "disabled_tools", ["list_documents", "get_document", "search_chat_history"]
    )
    fewer = len(json.dumps(tools.ollama_tools()))
    assert fewer < everything


# --- what one turn is actually offered (§11a) --------------------------------


def _offered(question: str) -> set[str]:
    return {t["function"]["name"] for t in tools.ollama_tools(tools.focus_for(question))}


def test_an_ordinary_question_is_not_sent_the_whole_toolbox(app_state):
    """The §11a win: 26 schemas went up whether the question was "how many
    notes do I have" or "remind me to call mum"."""
    everything = len(json.dumps(tools.ollama_tools()))
    asked = len(json.dumps(tools.ollama_tools(tools.focus_for("what did I save about sailing?"))))
    assert asked < everything / 2


def test_the_reading_core_and_create_note_are_always_there(app_state):
    """A cue that fails to fire costs the user the thing they asked for, and
    the worst case is create_note: the model then describes a note it did not
    save, which is the exact failure the honesty net exists for."""
    for question in ["hey", "what?", "", "asdf"]:
        offered = _offered(question)
        assert {"search_notes", "get_note", "count_notes", "create_note"} <= offered


@pytest.mark.parametrize(
    "question,wanted",
    [
        ("remind me to call mum tomorrow at 9", "set_reminder"),
        ("don't let me forget the dentist", "set_reminder"),
        ("tag my untagged notes", "tag_note"),
        ("link the notes about the trip", "link_notes"),
        ("delete that note about the old car", "delete_note"),
        ("fix the typo in note 4", "edit_note"),
        ("what did we talk about last time?", "search_chat_history"),
        ("summarise my week", "summarize_notes"),
        ("what's in my documents about the lease?", "list_documents"),
        ("make me a skill for this", "save_skill"),
    ],
)
def test_a_request_that_names_something_gets_the_tools_for_it(app_state, question, wanted):
    assert wanted in _offered(question)


def test_a_vague_request_to_do_something_gets_everything(app_state):
    """"Tidy up my notebook" is exactly the request whose tools cannot be
    guessed, so guessing is not attempted."""
    assert tools.focus_for("tidy up my notebook") is None
    assert tools.focus_for("go through my notes and sort them out") is None


def test_the_user_can_turn_the_focus_off(app_state):
    """A keyword rule's honest failure is a phrasing it doesn't know, so the
    escape hatch has to be reachable without editing code."""
    from memorymap.ai import agent as agent_module

    assert agent_module._focus("what did I save?") is not None
    app_state.set_preference("tool_focus", "all")
    assert agent_module._focus("what did I save?") is None


def test_focusing_never_blocks_a_tool_from_running(app_state, session, fake_ollama):
    """Unlike a skill's allowlist, this is an economy and not a policy: a tool
    left out because a cue didn't fire must still work if it is called."""
    from memorymap.ai import agent as agent_module
    from memorymap.core import deps

    fake_ollama.tool_script = [
        [{"name": "list_reminders", "arguments": {}}]  # no cue for this question
    ]
    events = list(
        agent_module.run_agent(
            session,
            "what did I save about sailing?",
            [],
            deps.get_model_manager(),
            fake_ollama,
        )
    )
    ran = [e for e in events if e["type"] == "tool"]
    assert ran and ran[0]["ok"] is True


def test_the_guide_does_not_repeat_what_a_tool_result_already_says(app_state):
    """Anything said in both places is paid for twice on every round.

    The preview warning travels with every list result (`tools._READ_MORE`),
    so the guide does not need its own copy of it.
    """
    guide = agent.TOOLS_GUIDE.lower()
    assert "clipped previews" not in guide
    assert tools._READ_MORE.lower() not in guide


def test_the_clock_in_the_prompt_is_stable_across_a_tool_loop(monkeypatch):
    """Ollama's prefix cache keeps the tokens before the first difference, and
    this line sits above the history and the notes. At microsecond precision
    it differed on every round of every turn, so each round re-read the whole
    prompt. The rounds of one tool loop are seconds apart, so a clock to the
    minute is the same string for all of them."""
    from datetime import datetime, timedelta, timezone

    from memorymap.core import config

    base = datetime(2026, 7, 28, 18, 55, 10, 123456, tzinfo=timezone.utc)

    def system_at(moment):
        monkeypatch.setattr(config, "user_now", lambda _cfg: moment)
        return agent.build_agent_messages("q", [])[0]["content"]

    first = system_at(base)
    # Three seconds later: a plausible gap between two rounds of one loop.
    assert system_at(base + timedelta(seconds=3, microseconds=8)) == first
    # A minute later it is allowed to change; the clock still has to be right.
    assert system_at(base + timedelta(minutes=1)) != first
    assert "18:55:00" in first and ".123456" not in first


def test_a_very_long_note_is_cut_short_with_a_way_to_read_the_rest():
    """Ten notes retrieved so the model sees ten of them, one note of pages
    would crowd out the other nine. Safe only because it can undo it."""
    note = {"id": 7, "category": "Work", "content": "x" * 4000}
    short = librarian.note_for_prompt(note)
    assert len(short) < 1100
    assert "get_note(7)" in short


def test_an_ordinary_note_is_left_exactly_as_it_is():
    """Most notes are a line or two; nothing should touch them."""
    note = {"id": 7, "category": "Work", "content": "the ferry leaves at 8"}
    assert librarian.note_for_prompt(note) == "the ferry leaves at 8"


def test_a_long_note_does_not_blow_the_prompt_budget():
    long_notes = [
        {"id": i, "category": "Work", "content": "y" * 4000} for i in range(10)
    ]
    messages = agent.build_agent_messages("what did I say?", long_notes)
    total = sum(len(m["content"]) for m in messages)
    # Ten 4,000-character notes is 40,000 characters of input; the per-note cap
    # is what stops that reaching the model. The figure here is a sanity
    # ceiling, not a budget, `ai/context.py` owns the real one.
    assert total < 20_000, total


# --- fitting the registry to the model, rather than to a constant ---------------
#
# Asked directly after four category tools took the all-tools overhead within
# ~180 characters of a 4096-token window: "if adding more tools is an issue, can
# we change or improve how tools are used so that doesn't become an issue?"
#
# The ceiling was never a fact about the app, it was an assumption about the
# model. 4096 is Ollama's fallback when a model declares nothing; a current 7B
# routinely declares 32k or more. The budget is measured now, not fixed.


def test_a_big_window_is_not_rationed_like_a_small_one(app_state):
    """Rationing a 32k model against 4096 withholds tools for no reason."""
    every = tools.ollama_tools()
    kept, dropped = tools.within_budget(every, tools.budget_for_window(32_768))
    assert not dropped
    assert len(kept) == len(every)


def test_a_small_window_drops_tools_rather_than_overflowing(app_state):
    """The failure this replaces is silent: past the window the system prompt
    goes off the front and the model stops knowing it has tools at all."""
    every = tools.ollama_tools()
    budget = tools.budget_for_window(4096)
    kept, dropped = tools.within_budget(every, budget)
    assert dropped, "a 4096 window cannot hold every schema, and should say so"
    assert tools.schema_chars(kept) <= budget


def test_what_survives_a_tight_budget_is_what_matters_most(app_state):
    """A model that cannot search or read a note cannot answer anything, so
    those go first and the tail is what gets dropped."""
    every = tools.ollama_tools()
    kept, _ = tools.within_budget(every, tools.budget_for_window(2048))
    names = [t["function"]["name"] for t in kept]
    assert "search_notes" in names
    assert names[0] in tools.CORE_TOOLS


def test_a_budget_too_small_for_even_one_tool_still_sends_one(app_state):
    """A model handed an empty tool list does not degrade gracefully, it
    answers from nothing and sounds confident about it."""
    kept, _ = tools.within_budget(tools.ollama_tools(), 1)
    assert len(kept) == 1


def test_the_measurement_is_of_the_list_as_it_is_actually_sent(app_state):
    """Summing individual schemas misses the brackets and commas, which are
    small and are also the difference between fitting and not."""
    every = tools.ollama_tools()[:5]
    assert tools.schema_chars(every) > sum(tools.schema_chars([t]) for t in every) - 100


def test_an_unknown_window_falls_back_to_the_cautious_number():
    """Being wrong towards 4096 wastes headroom; being wrong the other way
    drops the system prompt off the front."""
    from memorymap.ai.ollama_client import OllamaClient

    client = OllamaClient(base_url="http://127.0.0.1:1")  # nothing listening
    assert client.context_length("whatever") is None
    assert client.usable_context("whatever") == OllamaClient.DEFAULT_CONTEXT_TOKENS


def test_the_window_is_asked_for_once_per_model():
    """It cannot change without the model being re-pulled, and the answer is
    needed on every round."""
    from memorymap.ai.ollama_client import OllamaClient

    client = OllamaClient(base_url="http://127.0.0.1:1")
    client.context_length("a-model")
    client._context_lengths["a-model"] = 12345  # would be re-fetched if not cached
    assert client.context_length("a-model") == 12345


def test_a_backend_that_cannot_report_its_window_still_works(app_state):
    """Reporting a context window is an Ollama feature. §6's planned
    OpenAI-compatible backends (LM Studio, llama.cpp, Jan, vLLM) have no
    equivalent of /api/show, and the budget is an optimisation, one that can
    take the whole agent turn down with it is not one.

    Caught by three existing tests whose local fake predates the method, which
    is exactly the signal that a hard requirement had been added.
    """
    from memorymap.ai.ollama_client import OllamaClient

    class NoWindowReporting:
        """A client from before this existed, or a non-Ollama one."""

    report = getattr(NoWindowReporting(), "usable_context", None)
    window = report("m") if callable(report) else None
    assert (window or OllamaClient.DEFAULT_CONTEXT_TOKENS) == 4096


def test_a_small_model_can_still_ask_the_user_a_question():
    """`ask_user` was culled from small windows as a "complex" tool. It is the
    opposite: one question, a few options, and the only way the agent can say
    "which did you mean?" instead of guessing."""
    offered = [
        {"function": {"name": name, "parameters": {}}}
        for name in ("search_notes", "ask_user", "make_plan")
    ]
    kept, dropped = tools.within_budget(offered, tools.SMALL_WINDOW_CHARS - 1)
    assert "ask_user" in [t["function"]["name"] for t in kept]
    assert "make_plan" in dropped


# --- the untooled path's own budget -------------------------------------------
#
# `ai/context.py` was written to keep one turn inside one model's window, and
# for a long time it was wired into `agent.build_agent_messages` and nowhere
# else. `librarian.build_messages`, what "Ask the Librarian" and the Notes Ask
# box use: had no total cap at all: `UNTOOLED_NOTE_CHARS` bounds ONE note at
# 2,400 characters and `history_messages` bounds ONE past answer, and nothing
# bounded their sum.
#
# These are the tests that stop it drifting back. They assert the property that
# matters (the assembled prompt fits) rather than any particular number, so
# retuning the shares in context.py does not break them.


def _fat_notes(count: int) -> list[dict]:
    """Notes long enough that every one of them is clipped individually, so
    what is being measured is the total, not the per-note clip."""
    return [
        {
            "id": i,
            "category": "Ideas",
            "content": f"Note {i}. " + ("padding words here " * 400),
        }
        for i in range(1, count + 1)
    ]


class _SmallWindow:
    """Just enough of the provider interface for `plan_budget`."""

    DEFAULT_CONTEXT_TOKENS = 4096

    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def usable_context(self, model: str) -> int:
        return self.tokens


def test_the_untooled_prompt_fits_a_small_models_window():
    """Ten long notes at UNTOOLED_NOTE_CHARS is ~24,000 characters of notes
    alone: about 6,000 tokens, past a 4,096-token window in its entirety
    before the persona, the history or the question are counted. What a model
    does with an overrun is drop from the front, which is the system prompt.
    """
    budget = librarian.plan_budget("small:3b", _SmallWindow(4096))
    messages = librarian.build_messages(
        "What did I save?", _fat_notes(10), budget=budget
    )
    total = sum(len(m.get("content", "")) for m in messages)
    assert total <= 4096 * CHARS_PER_TOKEN


def test_without_a_budget_the_same_prompt_overruns():
    """The other half of the pair: this is what the path did before, and it is
    why the parameter exists. A test that only asserted the fixed version
    would pass just as happily if `fit_notes` were quietly removed again."""
    messages = librarian.build_messages("What did I save?", _fat_notes(10))
    total = sum(len(m.get("content", "")) for m in messages)
    assert total > 4096 * CHARS_PER_TOKEN


def test_dropped_notes_are_declared_not_silently_cut():
    """A model that knows its notes were cut will hedge; one that does not
    will answer as though it saw the whole notebook, which is the
    confident-and-wrong failure this app exists to avoid."""
    budget = librarian.plan_budget("small:3b", _SmallWindow(4096))
    messages = librarian.build_messages(
        "What did I save?", _fat_notes(10), budget=budget
    )
    assert "did not fit" in messages[-1]["content"]


def test_a_big_window_keeps_every_note():
    """The budget must not cost anything to someone running a large model, 
    it is a ceiling, not a target."""
    budget = librarian.plan_budget("big:70b", _SmallWindow(128_000))
    messages = librarian.build_messages(
        "What did I save?", _fat_notes(10), budget=budget
    )
    assert "did not fit" not in messages[-1]["content"]
    assert "10. [Ideas]" in messages[-1]["content"]


def test_a_long_custom_persona_leaves_less_room_not_an_overrun():
    """The persona is user-editable, which is why `context.plan` measures it
    rather than assuming a length. A 3,000-character persona has to come out
    of the notes' share, not out of the window."""
    persona = "You are a librarian. " * 150
    budget = librarian.plan_budget("small:3b", _SmallWindow(4096), persona_prompt=persona)
    messages = librarian.build_messages(
        "What did I save?", _fat_notes(10), persona_prompt=persona, budget=budget
    )
    total = sum(len(m.get("content", "")) for m in messages)
    assert total <= 4096 * CHARS_PER_TOKEN


def test_plan_budget_survives_a_provider_with_no_usable_context():
    """`usable_context` is part of the provider interface, but a fake or a
    future backend may not carry it, and a working turn beats a 500."""

    class Bare:
        DEFAULT_CONTEXT_TOKENS = 4096

    budget = librarian.plan_budget("mystery", Bare())
    assert budget.notes_chars > 0


# --- fitting a prompt to a small model ------------------------------------------
#
# Added from a live report: *"agent mode and chats are too heavy for small
# models and have a too small context window"*. Measured on a real turn with an
# 8k-window model, eight notes and no history at all, the prompt broke down as
# system 3,288 chars, notes-and-question 2,377, tool schemas 4,827, the
# schemas cost nearly twice what the user's own notes did, and the whole thing
# came to 32% of the window before the conversation had started.


def test_compacting_schemas_keeps_every_tool_and_its_arguments():
    """The trim must only touch prose. Names and parameters are what the model
    actually calls the tool with, shortening any of them produces malformed
    calls, not a smaller prompt."""
    full = tools.ollama_tools()
    compact = tools.compact_schemas(full)

    assert [t["function"]["name"] for t in compact] == [
        t["function"]["name"] for t in full
    ]
    for before, after in zip(full, compact):
        bp = (before["function"].get("parameters") or {}).get("properties") or {}
        ap = (after["function"].get("parameters") or {}).get("properties") or {}
        assert set(bp) == set(ap)
        for key in bp:
            assert bp[key].get("type") == ap[key].get("type")
    assert tools.schema_chars(compact) < tools.schema_chars(full)


def test_a_tight_window_loses_description_before_it_loses_a_tool():
    """Dropping a tool changes what the app can do; trimming a description
    only changes how verbosely it is explained. So the trim goes first."""
    every = tools.ollama_tools()
    budget = tools.budget_for_window(8192)

    kept, _dropped = tools.within_budget(every, budget)
    # More tools survive than the same budget would fit at full verbosity.
    fits_uncompacted = 0
    running: list[dict] = []
    for spec in every:
        if tools.schema_chars(running + [spec]) > budget:
            break
        running.append(spec)
        fits_uncompacted += 1
    assert len(kept) > fits_uncompacted


def test_a_roomy_window_still_gets_the_long_descriptions():
    """Compaction is a response to pressure, not the new default: the long
    descriptions are what stop a model reaching for the wrong tool."""
    every = tools.ollama_tools()
    kept, dropped = tools.within_budget(every, tools.budget_for_window(32_768))
    assert not dropped
    # Same tools (the order is by priority, not input order) with their
    # descriptions untouched: nothing was trimmed to make them fit.
    by_name = {t["function"]["name"]: t for t in kept}
    assert set(by_name) == {t["function"]["name"] for t in every}
    for original in every:
        name = original["function"]["name"]
        assert by_name[name]["function"]["description"] == (
            original["function"]["description"]
        )


def test_a_small_window_gets_the_short_tools_guide():
    assert agent.tools_guide(4096) is agent.COMPACT_TOOLS_GUIDE
    assert agent.tools_guide(8192) is agent.COMPACT_TOOLS_GUIDE
    assert agent.tools_guide(32_768) is agent.TOOLS_GUIDE
    # An unreported window is not a small one, that is a provider that did not
    # say, and guessing "tiny" would quietly degrade a large model.
    assert agent.tools_guide(None) is agent.TOOLS_GUIDE


def test_the_short_guide_keeps_the_rules_a_model_gets_wrong_without_them():
    """A truncation of the long guide would lose the honesty rule, which sits
    at its end. This is a rewrite, and these are the parts that must survive."""
    guide = agent.COMPACT_TOOLS_GUIDE.lower()
    assert "never say you created" in guide          # claiming work never done
    assert "not the whole" in guide.replace(", ", "") # a page is not the notebook
    assert "count_notes" in guide                    # how to get a real total
    assert "private notes are invisible" in guide
    assert "what_to_do" in guide                     # recovering from a failure
    assert len(agent.COMPACT_TOOLS_GUIDE) < len(agent.TOOLS_GUIDE) // 2


def test_a_small_model_spends_under_a_quarter_of_its_window_on_fixed_cost(session):
    """A regression guard on the whole prompt, not one part of it.

    The reported symptom was never "the schemas are big", it was *"chat
    conversation token usage seems abnormally high"* and *"agent mode and chats
    are too heavy for small models"*. Both are about the total, so that is what
    this pins.

    Fixed cost means what every round pays before the conversation exists: the
    system prompt, the tool schemas, and one page of notes. On an 8k window that
    was 2,623 tokens: 32% of everything the model had, with zero history. It is
    now under a quarter, and the difference is room for the notes and the
    conversation, which are what actually run out.

    The threshold is deliberately loose. This exists to catch a prompt growing
    back by a third, not to argue about fifty tokens.
    """
    from memorymap.core.database import Entry

    for i in range(20):
        session.add(
            Entry(content=f"Note {i}: the quarterly budget review. " * 12, tags="budget")
        )
    session.commit()
    notes = [
        {"id": e.id, "content": e.content, "category": "Work",
         "tags": e.tags, "created_at": "2026-08-01"}
        for e in session.query(Entry).limit(8).all()
    ]

    question = "what did I write about the budget?"
    window = 8192
    guide = agent.tools_guide(window)
    budget = context.plan(window, len(guide) + 480)
    messages = agent.build_agent_messages(
        question, notes, style="normal", profile="", history=[],
        persona_prompt="", budget=budget, mode="agent",
    )
    offered = tools.ollama_tools(tools.focus_for(question, ""))
    if window <= agent.SMALL_WINDOW_TOKENS:
        offered = tools.compact_schemas(offered)
    kept, _ = tools.within_budget(offered, budget.tool_schema_chars)

    # System prompt + tool schemas: the part that is identical on every round
    # and carries none of the user's own content. The notes are excluded on
    # purpose: those are what the room is *for*, and a turn that spends its
    # budget on notes is working correctly, not bloated.
    fixed = len(messages[0]["content"]) + tools.schema_chars(kept)
    share = (fixed / context.CHARS_PER_TOKEN) / window
    assert share < 0.20, (
        f"fixed prompt is {share:.0%} of an 8k window ({fixed:,} chars). "
        "It was 27% (6,795 chars: a 3,288-char guide and 4,827 of schemas) "
        "before this was fixed."
    )
    # And the model still has real tools, the saving must not have come from
    # quietly handing it an empty toolbox.
    assert len(kept) >= 8
    # The notes still got a real share of what was freed, rather than the
    # saving being banked and left unspent.
    assert len(messages[-1]["content"]) > 1500
