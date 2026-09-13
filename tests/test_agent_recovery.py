"""A failed tool call has to tell the model what to do next.

The failure used to reach the model as a bare {"error": "..."}. Small models
do one of two things with that: apologise and give up, or call the identical
thing again until MAX_ROUNDS runs out and the user is told "I stopped after
using several tools in a row" having learned nothing. Neither is a reasonable
response to a mistyped note id.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import agent


def test_a_missing_id_says_to_search_rather_than_guess():
    hint = agent._recovery_hint("get_note", "Note 999 not found")
    assert "search_notes" in hint
    assert "Do not guess" in hint


def test_a_disabled_tool_says_to_stop_calling_it():
    hint = agent._recovery_hint(
        "web_search", "The 'web_search' tool is turned off in Settings → Tools"
    )
    assert "Do not call it again" in hint


def test_an_unknown_tool_says_to_stop_calling_it():
    hint = agent._recovery_hint("nope", "Unknown tool 'nope'")
    assert "does not exist" in hint


def test_bad_arguments_say_to_reread_the_schema():
    # execute_tool prefixes handler errors with the tool's own name.
    hint = agent._recovery_hint("create_note", "create_note: 'content' is required")
    assert "schema" in hint


def test_web_off_says_not_to_retry():
    hint = agent._recovery_hint("read_url", "Web search is disabled in Settings")
    assert "Do not retry" in hint


def test_anything_else_still_gets_advice():
    hint = agent._recovery_hint("summarize_notes", "the model is unreachable")
    assert "Do not repeat it unchanged" in hint


class _Session:
    def rollback(self):
        return None

    def commit(self):
        return None


class _FakeOllama:
    """A scripted model: each round returns the next batch of tool calls."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.sent: list[dict] = []

    def chat_tools_stream(self, model, messages, offered, mode=None):
        self.sent = list(messages)
        calls = self.rounds.pop(0) if self.rounds else []
        yield {"final": {"content": "", "tool_calls": calls, "raw_tool_calls": calls}}


class _FakeModels:
    def chat_model(self):
        return "m"


def _drive(monkeypatch, rounds, results):
    """Run one agent turn and hand back the messages the model last saw."""
    fake = _FakeOllama(rounds)
    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(agent.tools, "execute_tool", lambda s, n, a, **kwargs: results.pop(0))
    list(agent.run_agent(_Session(), "q", [], _FakeModels(), fake))
    return [m for m in fake.sent if m.get("role") == "tool"]


def test_the_error_reaches_the_model_with_its_advice(monkeypatch, app_state):
    """The whole point: advice travels with the error, in the tool message."""
    tool_messages = _drive(
        monkeypatch,
        [[{"name": "get_note", "arguments": {"note_id": 999}}], []],
        [{"error": "Note 999 not found"}],
    )
    assert tool_messages, "the tool result must be handed back to the model"
    payload = json.loads(tool_messages[-1]["content"])
    assert payload["error"] == "Note 999 not found"
    assert "search_notes" in payload["what_to_do"]


def test_repeating_a_failed_call_is_called_out(monkeypatch, app_state):
    """Second identical failure gets a stronger message than the first."""
    same = {"name": "get_note", "arguments": {"note_id": 999}}
    tool_messages = _drive(
        monkeypatch,
        [[same], [same], []],
        [{"error": "Note 999 not found"}, {"error": "Note 999 not found"}],
    )
    payloads = [json.loads(m["content"]) for m in tool_messages]
    assert len(payloads) == 2
    assert "search_notes" in payloads[0]["what_to_do"]
    assert payloads[1]["what_to_do"] == agent.REPEATED_CALL_NOTE


def test_a_successful_call_carries_no_advice(monkeypatch, app_state):
    tool_messages = _drive(
        monkeypatch,
        [[{"name": "count_notes", "arguments": {}}], []],
        [{"count": 3, "label": "Counted notes"}],
    )
    payload = json.loads(tool_messages[-1]["content"])
    assert "what_to_do" not in payload


def test_the_prompt_tells_the_model_multiple_rounds_are_expected():
    """Asked for directly: 'I need agents to use tools more and better'."""
    guide = agent.TOOLS_GUIDE
    assert "several turns is normal and expected" in guide.lower()
    # A snippet is not a page, read_url before relying on a result.
    assert "read_url" in guide
    # It should stop narrating a timeline the user is already watching.
    assert "already see which tools you ran" in guide
    assert "what_to_do" in guide


# --- one tool failing over and over with *different* arguments -----------------
#
# Reported with a live log: the agent called `merge_categories` round after
# round, alternating between "There is no category called X" and "X and X are
# the same category". Every call had different arguments, so the identical-call
# guard above never fired once, and the turn burned every round it had.
#
# The tool's own error already lists the real category names (see
# `_find_category` in ai/tools/categories.py), so this is not a case of the
# model being under-informed: it is a model that has misunderstood what the
# tool is *for*, and will keep producing fresh wrong arguments for as long as
# it is allowed to. Taking the tool away is the only thing that ends it.


# Driven through `get_note` rather than `merge_categories` itself: that one is
# `destructive`, so it parks for the user's approval and never reaches a
# handler at all (which is its own cap, see the confirm test below). The
# mechanism under test is keyed on the tool's *name*, not on which tool it is.
def _merge(note_id: int) -> dict:
    return {"name": "get_note", "arguments": {"note_id": note_id}}


def test_one_tool_failing_with_different_arguments_is_taken_away(monkeypatch, app_state):
    calls: list[str] = []

    def _fail(session, name, arguments, **kwargs):
        calls.append(name)
        return {"error": f"There is no note {arguments['note_id']}"}

    fake = _FakeOllama([[_merge(1)], [_merge(2)], [_merge(3)], [_merge(4)], []])
    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(agent.tools, "execute_tool", _fail)
    list(agent.run_agent(_Session(), "merge my categories", [], _FakeModels(), fake))

    payloads = [json.loads(m["content"]) for m in fake.sent if m.get("role") == "tool"]
    # Three real attempts, and the fourth never reached the handler at all.
    assert calls == ["get_note"] * agent.MAX_TOOL_FAILURES
    assert len(payloads) == agent.MAX_TOOL_FAILURES + 1
    # The failure that *reaches* the cap already says the tool is spent, so the
    # model is not made to spend another round discovering that.
    assert payloads[agent.MAX_TOOL_FAILURES - 1]["what_to_do"] == agent.TOOL_EXHAUSTED_NOTE
    assert payloads[-1]["what_to_do"] == agent.TOOL_EXHAUSTED_NOTE
    assert "no longer available" in payloads[-1]["error"]


def test_a_tool_that_fails_twice_is_still_allowed_to_correct_itself(monkeypatch, app_state):
    """Two failures is a model fixing its own mistake, the recovery hints
    exist to produce exactly that, so the cap must not cut it off."""
    calls: list[dict] = []

    def _run(session, name, arguments, **kwargs):
        calls.append(arguments)
        if len(calls) < 3:
            return {"error": f"There is no note {arguments['note_id']}"}
        return {"id": 7, "label": "Read note", "content": "found it"}

    fake = _FakeOllama([[_merge(1)], [_merge(2)], [_merge(7)], []])
    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(agent.tools, "execute_tool", _run)
    list(agent.run_agent(_Session(), "merge my categories", [], _FakeModels(), fake))

    assert len(calls) == 3, "the third attempt must still be allowed to run"
    payloads = [json.loads(m["content"]) for m in fake.sent if m.get("role") == "tool"]
    assert "what_to_do" not in payloads[-1], "the call that succeeded carries no advice"


def test_failures_are_counted_per_tool_not_across_all_of_them(monkeypatch, app_state):
    """A turn where three *different* tools each fail once is not a loop, and
    must not cost any of them their fourth call."""
    ran: list[str] = []

    def _fail(session, name, arguments, **kwargs):
        ran.append(name)
        return {"error": f"{name} could not do that"}

    fake = _FakeOllama(
        [
            [{"name": "get_note", "arguments": {"note_id": 1}}],
            [{"name": "search_notes", "arguments": {"query": "x"}}],
            [{"name": "count_notes", "arguments": {}}],
            [{"name": "get_note", "arguments": {"note_id": 2}}],
            [],
        ]
    )
    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(agent.tools, "execute_tool", _fail)
    list(agent.run_agent(_Session(), "q", [], _FakeModels(), fake))

    assert ran == ["get_note", "search_notes", "count_notes", "get_note"]


def test_a_destructive_tool_cannot_paper_the_turn_with_confirm_cards(monkeypatch, app_state):
    """`merge_categories` is destructive: it parks for the user's approval
    instead of running. Parking is not a stop signal to a model that has
    misread the job, so the number of cards one tool may queue is capped, 
    the user should never come back to a wall of approvals they never asked
    for."""
    def _merge_cat(n: str) -> dict:
        return {"name": "merge_categories", "arguments": {"from": n, "into": "Hobbies"}}

    fake = _FakeOllama(
        [[_merge_cat("Movies")], [_merge_cat("Games")], [_merge_cat("Music")], []]
    )
    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(
        agent.tools, "execute_tool", lambda *a, **k: pytest.fail("a destructive tool ran")
    )
    events = list(agent.run_agent(_Session(), "tidy my categories", [], _FakeModels(), fake))

    confirms = [e for e in events if e.get("type") == "confirm"]
    assert len(confirms) == agent.MAX_PARKED_CONFIRMS
    payloads = [json.loads(m["content"]) for m in fake.sent if m.get("role") == "tool"]
    assert "Nothing more can be queued" in payloads[-1]["error"]
