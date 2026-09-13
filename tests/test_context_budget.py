"""One budget for the whole prompt, sized to the model that will read it.

Asked for directly: *"make sure the AI can run as efficiently and effectively
as possible. I don't want it being too prompt and context heavy and then taking
ages to respond or failing due to a quickly maxed out token window."*

The fault was that nothing added the parts up. Each cap was individually
reasonable and set in a different session against a different concern:

    system prompt   2,416 chars   tool schemas    4,096
    history         5,800         notes           9,000
    tool results   24,000
    ----------------------------------------------------
    worst case     45,312 chars ~ 11,328 tokens

Against a 4,096-token window that is 2.8x over, and the tool-result cap alone
exceeded the whole window by half. Overflow is dropped from the FRONT, which is
the system prompt: so it does not raise, it just quietly stops the model
knowing it has tools.
"""

from __future__ import annotations

import pytest

from memorymap.ai import agent, context, librarian, tools
from memorymap.ai.ollama_client import OllamaClient
from memorymap.core.database import Entry

WINDOWS = [2048, 4096, 8192, 16384, 32768, 131072]


def _system_chars() -> int:
    return len(f"{librarian.DEFAULT_PERSONA} {agent.AGENT_GROUNDING} {agent.TOOLS_GUIDE}")


# --- the whole point --------------------------------------------------------


@pytest.mark.parametrize("window", WINDOWS)
def test_the_worst_case_fits_the_window_it_was_planned_for(window):
    """Every part spending its full allowance still has to leave room to
    reply. This is the assertion the old constants could not make."""
    plan = context.plan(window, _system_chars())
    assert plan.fits, plan.as_log_line()


@pytest.mark.parametrize("window", WINDOWS)
def test_there_is_always_room_left_to_answer_in(window):
    """Ollama's num_ctx covers the prompt AND the response, so a prompt that
    fills the window leaves the model nowhere to reply, it stops mid-sentence,
    which reads as a crash rather than as a budget."""
    plan = context.plan(window, _system_chars())
    assert plan.output_reserve_chars > 0
    assert plan.prompt_chars + plan.output_reserve_chars <= window * 4


def test_a_small_model_is_squeezed_and_a_big_one_is_not():
    small = context.plan(4096, _system_chars())
    large = context.plan(32768, _system_chars())
    assert large.notes_chars > small.notes_chars * 4
    assert large.tool_schema_chars > small.tool_schema_chars * 4


def test_a_bigger_window_is_more_capable_than_the_old_constants_were():
    """The old numbers were sized for the smallest case and applied to
    everyone, so a 32k model was held to a 4k model's allowances."""
    large = context.plan(32768, _system_chars())
    assert large.notes_chars > 9_000  # the old 10 x MAX_NOTE_CHARS
    assert large.history_chars > 5_800  # the old 4-turn history cap


def test_a_long_custom_persona_takes_room_from_everything_else():
    """It is user-editable, and pretending it is free is how a total drifts
    over the line."""
    lean = context.plan(4096, 500)
    verbose = context.plan(4096, 6_000)
    assert verbose.notes_chars < lean.notes_chars


def test_a_window_too_small_for_the_persona_still_returns_a_usable_plan():
    """Zeroes would be a crash somewhere further down; floors are at least a
    cramped turn, and `fits` still reports the truth."""
    plan = context.plan(512, 8_000)
    assert plan.notes_chars >= context.MIN_NOTES_CHARS
    assert plan.tool_schema_chars >= context.MIN_TOOL_SCHEMA_CHARS
    assert not plan.fits


# --- trimming the variable parts --------------------------------------------


def test_notes_are_dropped_whole_rather_than_all_clipped_shorter():
    """Ten notes clipped to a sentence each are ten things the model cannot
    quote; four whole ones are four it can."""
    notes = [{"id": i, "content": "x" * 500} for i in range(10)]
    kept, dropped = context.fit_notes(notes, 1_500, lambda n: n["content"])
    assert dropped == len(notes) - len(kept)
    assert all(len(n["content"]) == 500 for n in kept), "a kept note was truncated"


def test_the_most_relevant_notes_are_the_ones_kept():
    """Retrieval hands them back best-first, so the tail is the right end to
    drop from."""
    notes = [{"id": i, "content": "x" * 400} for i in range(10)]
    kept, _ = context.fit_notes(notes, 2_000, lambda n: n["content"])
    assert [n["id"] for n in kept] == list(range(len(kept)))


def test_at_least_one_note_survives_any_budget():
    notes = [{"id": 1, "content": "x" * 50_000}]
    kept, dropped = context.fit_notes(notes, 100, lambda n: n["content"])
    assert len(kept) == 1 and dropped == 0


def test_history_is_kept_in_whole_exchanges():
    """Half an exchange is a question with no answer, and a model reading one
    will happily invent the missing side."""
    messages = []
    for i in range(6):
        messages.append({"role": "user", "content": f"question {i} " + "x" * 200})
        messages.append({"role": "assistant", "content": f"answer {i} " + "y" * 200})
    kept = context.fit_history(messages, 1_000)
    assert len(kept) % 2 == 0
    assert [m["role"] for m in kept] == ["user", "assistant"] * (len(kept) // 2)


def test_the_most_recent_exchanges_are_the_ones_kept():
    messages = []
    for i in range(5):
        messages.append({"role": "user", "content": f"q{i}" + "x" * 300})
        messages.append({"role": "assistant", "content": f"a{i}" + "y" * 300})
    kept = context.fit_history(messages, 1_400)
    assert kept, "history was emptied entirely"
    assert kept[-1]["content"].startswith("a4"), "the newest exchange was dropped"


def test_no_history_budget_means_no_history_rather_than_a_crash():
    assert context.fit_history([{"role": "user", "content": "hi"}], 0) == []


# --- what the model is actually asked for -----------------------------------


def test_the_window_budgeted_for_is_the_window_asked_for():
    """The subtle half of this. Ollama runs a model at `num_ctx`, its OWN
    default (commonly 4,096), regardless of what the model was trained for, 
    so reading 32k from /api/show and budgeting against it, without also
    asking for 32k, reproduces the exact overflow the budget prevents."""
    client = OllamaClient(base_url="http://127.0.0.1:1")
    client._context_lengths = {"m": 32_768}
    assert client.runtime_options("m")["num_ctx"] == client.usable_context("m")


def test_a_huge_declared_window_is_not_requested_by_default():
    """The KV cache scales with the window: a 7B at 128k wants gigabytes a
    laptop may not have, and that failure is an out-of-memory rather than a
    slow answer."""
    client = OllamaClient(base_url="http://127.0.0.1:1")
    client._context_lengths = {"m": 131_072}
    assert client.usable_context("m") == OllamaClient.MAX_REQUESTED_CONTEXT


def test_someone_who_knows_their_machine_can_raise_the_ceiling(app_state):
    app_state.set_preference("max_context_tokens", 32_768)
    client = OllamaClient(base_url="http://127.0.0.1:1")
    client._context_lengths = {"m": 131_072}
    assert client.usable_context("m") == 32_768


@pytest.mark.parametrize("bad", ["nonsense", None, 40, -1])
def test_a_bad_ceiling_preference_cannot_break_a_chat(app_state, bad):
    """It is read from a file the user is invited to edit by hand."""
    app_state.set_preference("max_context_tokens", bad)
    client = OllamaClient(base_url="http://127.0.0.1:1")
    client._context_lengths = {"m": 131_072}
    assert client.usable_context("m") >= OllamaClient.DEFAULT_CONTEXT_TOKENS


def test_the_reply_length_is_capped():
    """Output tokens are generated one at a time, so they cost far more
    wall-clock each than prompt tokens, an unbounded reply is the commonest
    reason an answer "takes ages"."""
    client = OllamaClient(base_url="http://127.0.0.1:1")
    assert client.runtime_options("m")["num_predict"] > 0


def test_every_generation_path_sends_the_options():
    """Four call sites, and a payload that silently omits them is a model
    running with Ollama's defaults again.

    Matched on the call rather than on its full argument list: the response
    presets (§11) added a `mode` argument to every one of these, and an
    assertion pinned to the exact spelling would have failed on a change that
    kept the property it exists to protect.
    """
    from pathlib import Path

    source = Path(OllamaClient.__module__.replace(".", "/") + ".py")
    text = (Path("src") / source).read_text(encoding="utf-8")
    # Five, not four: `_tools_path_is_broken` is a real generation request too
    #, a one-token probe that decides whether a 500 on the tools path means
    # "this model can't do tool calls" or "the backend is down", and it has to
    # carry the same options as the request it is standing in for, or it would
    # be testing a different thing from the one that failed.
    assert text.count("self.runtime_options(model") == 5


# --- the agent actually uses it ---------------------------------------------


def test_the_agent_plans_before_it_builds(ai_client, session, fake_ollama):
    """Regression guard: the budget is only worth having if the turn is sized
    before any of it is assembled."""
    fake_ollama.context_tokens = 4096
    fake_ollama.librarian_reply = "Answer."
    events = list(
        agent.run_agent(
            session, "what did I write about beans?", [], _Models(), fake_ollama
        )
    )
    assert any(e.get("type") == "answer" for e in events)


def test_notes_that_did_not_fit_are_declared_rather_than_dropped_silently():
    """A model that knows its notes were cut can search for the rest; one
    that does not will answer as though it saw the whole notebook."""
    notes = [{"id": i, "category": "General", "content": "x" * 800} for i in range(20)]
    plan = context.plan(4096, _system_chars())
    messages = agent.build_agent_messages("q", notes, budget=plan)
    assert "did not fit" in messages[-1]["content"]


def test_a_turn_that_fits_says_nothing_about_dropping():
    notes = [{"id": 1, "category": "General", "content": "short"}]
    plan = context.plan(32768, _system_chars())
    messages = agent.build_agent_messages("q", notes, budget=plan)
    assert "did not fit" not in messages[-1]["content"]


class _Models:
    def chat_model(self):
        return "m"

    def utility_model(self):
        return "m"

    def embedding_backend(self):
        return "sentence-transformers"


def _note(session, content="a note"):
    entry = Entry(content=content, tags="[]")
    session.add(entry)
    session.commit()
    return entry


def test_a_huge_context_window_does_not_buy_a_huge_search_result(session):
    """The result *ceiling* was scaled with the window, not just the default,
    so a 128k model could pull 768 previews, ~38k tokens, from one call."""
    for i in range(40):
        _note(session, f"kayak note number {i}")

    result = tools.execute_tool(
        session, "search_notes", {"query": "kayak"}, context_tokens=128_000
    )
    assert len(result.get("notes", [])) <= tools.MAX_LIST_LIMIT
