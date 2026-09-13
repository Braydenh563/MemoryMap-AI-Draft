"""What the agent carries between rounds, and what it stops repeating.

Two reported failures, both about a turn that costs more than it should:

*"It often calls the same tools to read all notes or to read the same note's
context in full after no changes."*, a repeated read returns identical data
and appends it to the prompt a second time, so the round costs the window twice
and brings back nothing.

*"It thinks up this whole plan, then it does a tool call and either loses track
or has to rethink up the plan again."*, the reasoning was streamed to the user
and then dropped from the messages, so the next round saw its own tool calls
with no record of why it made them.
"""

from __future__ import annotations

import json

from memorymap.ai import agent


class _Session:
    def rollback(self):
        return None

    def commit(self):
        return None


class _FakeOllama:
    """A scripted model. Each round returns the next batch of calls, and
    optionally some thinking, so what the *next* round is sent can be read
    back off `sent`."""

    def __init__(self, rounds, thinking=None):
        self.rounds = list(rounds)
        self.thinking = list(thinking or [])
        self.sent: list[dict] = []

    def chat_tools_stream(self, model, messages, offered, mode=None):
        self.sent = [dict(m) for m in messages]
        calls = self.rounds.pop(0) if self.rounds else []
        think = self.thinking.pop(0) if self.thinking else None
        yield {
            "final": {
                "content": "",
                "thinking": think,
                "tool_calls": calls,
                "raw_tool_calls": calls,
            }
        }


class _FakeModels:
    def chat_model(self):
        return "m"


def _drive(monkeypatch, rounds, results, thinking=None):
    """Run one turn. Returns (the messages the model last saw, calls executed)."""
    fake = _FakeOllama(rounds, thinking)
    executed: list[tuple[str, dict]] = []

    def execute(session, name, arguments, **kwargs):
        executed.append((name, arguments))
        return results.pop(0)

    monkeypatch.setattr(agent.tools, "ollama_tools", lambda allowed=None: [])
    monkeypatch.setattr(agent.tools, "execute_tool", execute)
    events = list(agent.run_agent(_Session(), "q", [], _FakeModels(), fake))
    return fake.sent, executed, events


# --- not reading the same thing twice ------------------------------------------


def test_an_identical_read_is_not_run_again(monkeypatch, app_state):
    """The reported waste. Same tool, same arguments, nothing written in
    between: the second call is answered from what the turn already has."""
    same = {"name": "list_notes", "arguments": {"limit": 10}}
    _sent, executed, _events = _drive(
        monkeypatch,
        [[same], [same], []],
        [{"notes": [], "label": "Listed notes"}],  # only ONE result available
    )
    assert executed == [("list_notes", {"limit": 10})], (
        "the second identical read should never have reached the tool, if it "
        "did, this would have raised on the empty results list"
    )


def test_the_model_is_told_it_already_has_that_result(monkeypatch, app_state):
    """Suppressing the call silently would leave the model waiting for data it
    is never handed. It gets a pointer instead, and the pointer says what to do
    next: otherwise the obvious next move is to call it a third time."""
    same = {"name": "get_note", "arguments": {"note_id": 4}}
    sent, _executed, _events = _drive(
        monkeypatch,
        [[same], [same], []],
        [{"content": "the note", "label": "Read note"}],
    )
    payloads = [json.loads(m["content"]) for m in sent if m.get("role") == "tool"]
    assert payloads[-1]["already_done"] is True
    assert "move on" in payloads[-1]["note"]


def test_a_read_is_run_again_after_something_is_written(monkeypatch, app_state):
    """The freshness rule, and the only way this cache could be *wrong* rather
    than merely thrifty: once the notebook changes, an earlier read of it is
    out of date and re-reading is real work."""
    read = {"name": "list_notes", "arguments": {}}
    write = {"name": "tag_note", "arguments": {"note_id": 1, "tags": ["x"]}}
    _sent, executed, _events = _drive(
        monkeypatch,
        [[read], [write], [read], []],
        [
            {"notes": [], "label": "Listed"},
            {"id": 1, "label": "Tagged"},
            {"notes": [], "label": "Listed again"},
        ],
    )
    assert [name for name, _args in executed] == ["list_notes", "tag_note", "list_notes"]


def test_a_repeated_write_still_earns_nothing(monkeypatch, app_state):
    """The trap in the fix. The freshness cache is cleared by a write, and if
    that cleared the earned-round ledger too, a model repeating one identical
    write would buy itself a fresh round every time, which is the exact loop
    EARNED_ROUNDS exists to starve."""
    write = {"name": "tag_note", "arguments": {"note_id": 1, "tags": ["x"]}}
    rounds = [[write] for _ in range(agent.MAX_ROUNDS + agent.EARNED_ROUNDS + 4)]
    _sent, executed, _events = _drive(
        monkeypatch,
        rounds,
        [{"id": 1, "label": "Tagged"} for _ in rounds],
    )
    # The *first* write is new work and legitimately earns a round; every
    # identical one after it earns nothing, so the turn stops at the granted
    # cap plus that one rather than climbing to the ceiling.
    assert len(executed) <= agent.MAX_ROUNDS + 1, (
        "a turn repeating one identical write must not keep earning rounds, "
        f"it ran {len(executed)} times against a ceiling of "
        f"{agent.MAX_ROUNDS + agent.EARNED_ROUNDS}"
    )


# --- keeping its own plan ------------------------------------------------------


def test_the_round_s_reasoning_is_carried_into_the_next_one(monkeypatch, app_state):
    plan = "First I will list the categories, then merge the two duplicates."
    sent, _executed, _events = _drive(
        monkeypatch,
        [[{"name": "list_categories", "arguments": {}}], []],
        [{"categories": [], "label": "Listed"}],
        thinking=[plan],
    )
    assistant = [m for m in sent if m.get("role") == "assistant"]
    assert assistant, "the round's own turn is replayed to the model"
    assert plan in assistant[-1]["content"]
    # Marked, so the model reads it as its own note rather than as something
    # the user said.
    assert "my reasoning so far" in assistant[-1]["content"]


def test_carried_reasoning_is_clipped(monkeypatch, app_state):
    """A plan is worth a paragraph, not a page: carrying the whole of a
    thinking model's output would double the prompt every round."""
    sent, _executed, _events = _drive(
        monkeypatch,
        [[{"name": "count_notes", "arguments": {}}], []],
        [{"count": 1, "label": "Counted"}],
        thinking=["x" * 5_000],
    )
    assistant = [m for m in sent if m.get("role") == "assistant"][-1]
    assert len(assistant["content"]) < agent.THINKING_CARRIED_CHARS + 100


def test_a_round_with_no_thinking_is_replayed_unchanged(monkeypatch, app_state):
    """Most models emit none, and they must not gain an empty marker."""
    sent, _executed, _events = _drive(
        monkeypatch,
        [[{"name": "count_notes", "arguments": {}}], []],
        [{"count": 1, "label": "Counted"}],
    )
    assistant = [m for m in sent if m.get("role") == "assistant"][-1]
    assert "my reasoning so far" not in assistant["content"]
